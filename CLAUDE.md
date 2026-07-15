# CLAUDE.md — agent/developer orientation

Batch pipeline that turns Sharadar (Nasdaq Data Link) bulk exports into a
point-in-time, survivorship-bias-free training dataset for stock
classification. Parquet + DuckDB only; no services, no database.

## Read this before coding

| Doc | When |
|---|---|
| `PLAN.md` | Design rationale & invariants. §-numbers (§1–§7) are cited from code docstrings — don't renumber. Read the § relevant to your module; read §7 in full before touching `src/splits/`. |
| `TODO.md` | Task register: milestones, verification tasks V1–V6, open questions. |
| `docs/decisions/` | ADRs for resolved questions. Skim titles; read the ones your module touches. |
| `docs/labels.md` | Canonical label/snapshot column definitions. Update it whenever the labels schema changes. |
| `docs/features.md` | Canonical feature registry (one row per feature). Must stay 1:1 with `src/features/registry.py`; update both together. |
| `docs/research/` | Research workspaces (feature-set research pre-M4 → `features.md` there). Findings go here, not in README/PLAN. |
| `README.md` | Human-facing overview + how to run. Keep it high-level; don't let detail accumulate there. |

## Commands

```bash
uv sync                 # install (Python >=3.12, uv-managed)
make test               # pytest; single test: uv run pytest tests/test_x.py -k name
make ingest             # bulk download (needs NASDAQ_DATA_LINK_API_KEY; ~40-50 GB)
make identity           # ticker↔permaticker mapping + universe
make labels             # snapshots + label matrix
make features           # per-family feature tables (needs labels)
make qa                 # data-gated QA reports (coverage, staleness, DAILY PIT)
```

`data/` is git-ignored and empty in a fresh clone — everything must be
developable and testable from synthetic fixtures; never assume real data is
present.

## Layout

```
src/ingest/      table registry (tables.py), download, CSV→parquet conversion
src/identity/    tickers dedup (source.py), mapping, universe, year counts
src/labels/      source views, snapshots, delistings, paths (stage 1), compute (stage 2), cli
src/features/    registry.py (1:1 with docs/features.md), base (as-of + lags), market, 8 family modules, output (registry-validated writer), cli
src/splits/      (M5, not started — PLAN.md §7 is required reading)
src/qa/          data-gated QA reports (sharadar-qa): coverage/null rates (F9), staleness×labels, DAILY PIT check (V7)
tests/           synthetic-fixture tests; conftest.py has shared TICKERS fixtures
```

Entry points (pyproject): `sharadar-ingest`, `sharadar-identity`,
`sharadar-labels`, `sharadar-qa`. New top-level packages must be added to
`[tool.hatch.build.targets.wheel] packages` and get a `make` target.

## Non-negotiable invariants (PLAN.md has the why)

- **Point-in-time:** features may only use information public on/before
  `snapshot_date`. SF1: as-reported dimensions (ARQ/ART) only; availability
  date is `datekey` (usable the first trading day strictly after), never
  `calendardate`/`reportperiod`.
- **`permaticker` is the entity key**; `ticker` is a join key, resolved
  through the mapping's price-coverage window (tickers get reused).
- **Never drop delisted rows** from labels — that reintroduces survivorship
  bias. Delisting handling lives in `labels/paths.py` only (decision 0002).
- **Splits must purge per horizon and embargo** (`snapshot_date + horizon +
  embargo < test_start`); low/high snapshot kinds are training-only.
- Missing values stay NULL — no silent imputation.

## Code conventions

- Pipeline pattern (see `src/identity/`, `src/labels/`): pure-SQL DuckDB
  **temp views** built by `build_*_view(con)` functions, materialized by
  `write_*_table(con, dir)` functions that COPY to ZSTD parquet, return count
  dicts, and log a summary. CLIs are thin argparse orchestrators returning
  int exit codes (2 = missing inputs, with a hint naming the command to run
  first).
- Interpolate SQL identifiers/literals via `identity.source.sql_quote`; keep
  column lists explicit (no `SELECT *` from raw tables).
- Data flow: `data/raw/` (immutable ingests) → `data/interim/` →
  `data/datasets/` (versioned, immutable). Parquet sorted for downstream
  joins; large jobs set `preserve_insertion_order=false` + a temp directory.
- Tests build small CSV worlds and push them through the **real** ingest
  converter (`csv_to_parquet` + `TABLES` specs), then run the real CLI
  `main()`; assert on hand-checkable numbers (see
  `tests/test_labels_cli.py`'s ZIG stock for the style). No mocking of
  DuckDB/SQL internals.

## Practices

- Resolving anything listed under "Open questions" in TODO.md ⇒ write an ADR
  in `docs/decisions/NNNN-slug.md` (context/decision/consequences), check the
  box in TODO.md, and update PLAN.md if the design text changes.
- Research/exploration writeups go under `docs/research/`, one workspace per
  topic; they graduate to ADRs + canonical docs, not into README/PLAN.
- Keep TODO.md current as tasks complete; keep README.md lean.
