# sharadar-dataset

Point-in-time, survivorship-bias-free dataset construction for fundamentals-based
stock classification models.

This repo is responsible for everything **up to and including** the production of a
model-agnostic training dataset. Model training, evaluation, and portfolio
construction live in a separate repo (`value-ml-models`) that consumes the output
of this one — start from the **[dataset user manual](docs/manual.md)** if that's
what you're here for.

## Goals

Produce a wide, versioned dataset of the form:

```
(permaticker, snapshot_date, feature_1 ... feature_N, label_1 ... label_M, split_tag)
```

- Every **feature** reflects only information publicly available on or before
  `snapshot_date` — strict point-in-time discipline (as-reported fundamentals,
  filing-date availability).
- Every **label** is a forward-looking total-return outcome, defined for *every*
  snapshot — including stocks that delist during the forward window. Dropping
  delisted rows is forbidden; it would reintroduce survivorship bias.
- **Splits** are temporally purged and embargoed per horizon, so downstream
  validation metrics are honest rather than memorization artifacts.
- Dataset versions are immutable, named, and fully reproducible from `data/raw/`
  by a single command; the downstream repo pins a version.

The full design — point-in-time rules, universe definition, snapshot and label
conventions, and the leakage/splitting theory — lives in **[PLAN.md](PLAN.md)**.

## Data source

All data comes from **Sharadar via Nasdaq Data Link**:

| Table | Contents | Role |
|---|---|---|
| `SF1` | Fundamentals (quarterly/annual/TTM, multiple dimensions) | Features |
| `SEP` | Equity prices, daily, incl. `closeadj` | Labels, price-based features |
| `SFP` | Fund prices (SPY etc.) | Benchmark labels |
| `TICKERS` | Metadata: permaticker, category, sector/industry, isdelisted, SIC, FF industry | Universe definition, identifier mapping |
| `ACTIONS` / `EVENTS` | Corporate actions, delisting events | Delisting-return conventions |
| `DAILY` | Daily-computed metrics (marketcap, ev, pe, pb, ps) | Convenience features |

## Architecture

Deliberately simple. Parquet everywhere, queried with DuckDB — laptop-scale
(full SF1 is a few GB, SEP ~10–20 GB). A batch pipeline with a single output;
no database service, no live serving.

```
sharadar-dataset/
├── data/
│   ├── raw/          # bulk parquet exports from Data Link, immutable
│   ├── interim/      # permaticker-resolved, cleaned tables
│   └── datasets/     # versioned, immutable datasets: dataset_vX.Y/
├── src/
│   ├── ingest/       # bulk download + refresh from Nasdaq Data Link
│   ├── identity/     # ticker↔permaticker resolution, universe construction
│   ├── labels/       # snapshot generation, forward-return + delisting-aware labels
│   ├── features/     # feature computation (one module per feature family)
│   ├── splits/       # purged/embargoed split tagging
│   ├── assemble/     # dataset assembly: join, ranks, composites, weights
│   └── qa/           # data-quality reports, survivorship audits
├── docs/
│   ├── features.md   # canonical feature registry
│   ├── labels.md     # canonical label definitions & conventions
│   ├── splits.md     # canonical split-tag definitions
│   ├── dataset.md    # canonical dataset column groups & manifest
│   ├── decisions/    # ADR-style records of resolved design questions
│   └── research/     # research workspaces (feature-set research, etc.)
└── tests/
```

## Status

| Milestone | State |
|---|---|
| M1 — Ingestion & identity | ✅ done (verification writeups V2/V3 pending) |
| M2 — Point-in-time verified | machinery done; V1 writeup pending |
| M3 — Labels | ✅ done (verification writeups V4/V6 pending) |
| M4 — Features | ✅ done (V5 bank/insurer half pending) |
| M5 — Splits & assembly | ✅ done — `dataset_v1.0` built end-to-end, QA reports published |

The pipeline is complete: `make all` produces `dataset_v1.0` from a raw
ingest, and the QA reports from the real-data run are committed under
[docs/research/reports/](docs/research/reports/). Remaining work is the
verification writeups and open questions in **[TODO.md](TODO.md)**;
model training happens downstream in `value-ml-models`, guided by
**[docs/manual.md](docs/manual.md)**.

## Getting started

Dependencies are managed with [uv](https://docs.astral.sh/uv/):

```bash
uv sync            # create .venv and install dependencies
make test          # run the test suite
```

### 1. Ingest the raw tables

Set your Nasdaq Data Link API key, then bulk-download everything:

```bash
export NASDAQ_DATA_LINK_API_KEY=...
make ingest                          # all seven tables
make ingest TABLES="TICKERS SEP"     # or a subset
```

or call the CLI directly for the full option set: `uv run sharadar-ingest --help`.

For each table this requests a bulk export, downloads the zipped CSV, and
converts it with DuckDB to `data/raw/<TABLE>.parquet` (typed, sorted,
ZSTD-compressed) plus a `.meta.json` provenance sidecar. Existing tables are
skipped unless `--force` is given; interrupt and re-run to resume. Budget
~40–50 GB free for the initial full run (SEP's CSV is extracted next to the
output before conversion).

### 2. Build the identity artifacts

```bash
make identity        # or: uv run sharadar-identity --help
```

Produces under `data/interim/`: the canonical `ticker_permaticker.parquet`
mapping (reused tickers flagged), `ticker_reuse.parquet`, `universe.parquet`
(inclusion rules as auditable flag columns + `in_universe` verdict), and
per-year universe counts (parquet/CSV/plot).

### 3. Build snapshots and labels

```bash
make labels          # or: uv run sharadar-labels --help
```

Produces under `data/interim/`: `snapshots.parquet` (three snapshots per
stock-quarter, on the intra-quarter low/median/high touch dates) and
`labels.parquet` (the full forward-return label matrix per horizon, with
delisting-aware handling). Column definitions: `docs/labels.md`.

### 4. Build the feature families

```bash
make features        # or: uv run sharadar-features --help
```

Produces one parquet per feature family under `data/interim/features/`
(meta, valuation, profitability, growth, solvency, quality, technical,
classification), each keyed like `labels.parquet` and validated against the
canonical registry (`docs/features.md` / `src/features/registry.py`).
Ranks, sector ranks, and the assembly-stage composites are computed at
assembly (M5).

### 5. Tag the train/validation/test splits

```bash
make splits          # or: uv run sharadar-splits --help
```

Produces under `data/interim/`: `splits.parquet` (per-horizon purged +
embargoed role tags — train/test/purged/embargoed — for the sealed holdout
and expanding walk-forward folds, plus the diagnostic-only
`entity_holdout`/`random_kfold` schemes) and `split_folds.parquet` (the
frozen fold manifest). Tags, never filters: no row is dropped.
Definitions: `docs/splits.md`.

### 6. Assemble the versioned dataset

```bash
make dataset         # or: uv run sharadar-assemble --help
```

Joins the families × labels on the snapshot key (validated against the
registry), computes the registry-driven ranks/sector-ranks (ADR 0008), the
assembly-stage composites `mohanram_g7` and `conservative_score` (ADR
0013), and the per-horizon uniqueness weights `sample_weight_{H}y` (ADR
0012), then writes the immutable `data/datasets/dataset_v1.0/` —
`dataset.parquet` + the split files + `manifest.json`. Column groups:
`docs/dataset.md`. From an existing ingest, `make all` runs steps 2–6
end-to-end.

### 7. Run the QA reports

```bash
make qa              # or: uv run sharadar-qa {coverage,staleness,daily-pit,splits-diag} --help
```

Four data-gated reports: fundamentals coverage / null rates, staleness vs.
label outcomes, the V7 `DAILY` point-in-time check, and the PLAN §7.7
split-overlap diagnostics. Detail parquet lands under `data/interim/qa/`;
committable markdown + CSV summaries under `docs/research/reports/` — the
committed copies there are from the 2026-07-18 real-data run.

Query any artifact with DuckDB:

```python
import duckdb
duckdb.sql("SELECT count(*) FROM 'data/interim/labels.parquet'")
```

## Documentation map

| File | Contents |
|---|---|
| [PLAN.md](PLAN.md) | Design & theory: objectives, point-in-time rules, universe, snapshots, features, labels, splits |
| [TODO.md](TODO.md) | Task register: milestones, verification tasks, open questions |
| [CLAUDE.md](CLAUDE.md) | Orientation for AI agents & developers: conventions, invariants, what to read |
| [docs/manual.md](docs/manual.md) | **User manual for `value-ml-models`**: how to consume a dataset version honestly |
| [docs/features.md](docs/features.md) | Canonical feature registry |
| [docs/labels.md](docs/labels.md) | Canonical label/snapshot column definitions |
| [docs/splits.md](docs/splits.md) | Canonical split-tag definitions (roles, fold calendar) |
| [docs/dataset.md](docs/dataset.md) | Canonical dataset column groups, weights, manifest |
| [docs/decisions/](docs/decisions/) | ADRs for resolved design questions |
| [docs/research/](docs/research/) | Research workspaces (feature-set research pre-M4) |
