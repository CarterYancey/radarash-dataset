# sharadar-dataset

Point-in-time, survivorship-bias-free dataset construction for fundamentals-based
stock classification models.

This repo is responsible for everything **up to and including** the production of a
model-agnostic training dataset. Model training, evaluation, and portfolio
construction live in a separate repo (`value-ml-models`) that consumes the output
of this one.

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
│   └── datasets/     # versioned final datasets: dataset_vX.Y.parquet
├── src/
│   ├── ingest/       # bulk download + refresh from Nasdaq Data Link
│   ├── identity/     # ticker↔permaticker resolution, universe construction
│   ├── snapshots/    # snapshot generation, as-of joins
│   ├── features/     # feature computation (one module per feature family)
│   ├── labels/       # forward-return + delisting-aware label computation
│   ├── splits/       # purged/embargoed split tagging
│   └── qa/           # data-quality reports, survivorship audits
├── docs/
│   ├── features.md   # canonical feature registry
│   ├── labels.md     # canonical label definitions & conventions
│   ├── decisions/    # ADR-style records of resolved design questions
│   └── research/     # research workspaces (feature-set research, etc.)
└── tests/
```

## Status

| Milestone | State |
|---|---|
| M1 — Ingestion & identity | ✅ code done (verification writeups pending) |
| M2 — Point-in-time verified | not started |
| M3 — Labels | ✅ code done (verification writeups pending) |
| M4 — Features | next up — research phase, see `docs/research/features.md` |
| M5 — Splits & assembly | not started |

The task register, verification tasks, and open questions live in
**[TODO.md](TODO.md)**.

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

### 4. Run the QA reports (feature-research inputs)

```bash
make qa              # or: uv run sharadar-qa {coverage,staleness,daily-pit} --help
```

Three data-gated reports feeding the pre-M4 research questions
(`docs/research/features.md`): fundamentals coverage / depth-tier survival /
null rates, staleness vs. label outcomes, and the V7 check on whether
`DAILY` is point-in-time safe. Detail parquet lands under `data/interim/qa/`;
committable markdown + CSV summaries under `docs/research/reports/` — commit
those to share a run's results.

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
| [docs/labels.md](docs/labels.md) | Canonical label/snapshot column definitions |
| [docs/decisions/](docs/decisions/) | ADRs for resolved design questions |
| [docs/research/](docs/research/) | Research workspaces (feature-set research pre-M4) |
