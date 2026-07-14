# sharadar-dataset

Point-in-time, survivorship-bias-aware dataset construction for
fundamentals-based U.S. equity models.

This repository owns the batch pipeline from licensed Sharadar source tables
through a versioned, model-agnostic training dataset. Model training,
evaluation, portfolio construction, and backtesting belong in the downstream
`value-ml-models` repository.

## Goals

The final dataset has one row per permanent security and snapshot:

```text
(permaticker, snapshot_date, features..., labels..., split_tags...)
```

The pipeline is designed to preserve:

- strict point-in-time feature availability;
- permanent identifiers instead of ticker identity;
- delisted securities and forward outcomes;
- temporal split boundaries without overlapping-label leakage;
- reproducibility from immutable raw Parquet files.

All tabular artifacts use Parquet and are queried or transformed with DuckDB.
There is no database service.

## Current pipeline

```text
Nasdaq Data Link bulk exports
          │
          ▼
data/raw/*.parquet
          │
          ├── identity mapping and universe
          │        └── data/interim/{ticker_permaticker,universe}.parquet
          │
          └── quarterly low/median/high price snapshots
                   └── data/interim/{snapshots,labels}.parquet

Planned:
features → point-in-time assembly → purged temporal splits → versioned dataset
```

Implemented stages:

- bulk download, validation, and conversion to compressed Parquet;
- ticker-to-permaticker mapping and unresolved-symbol audits;
- non-financial domestic common-stock universe construction;
- annual universe-count reporting;
- three observed-price snapshots per stock-quarter;
- 1-, 2-, 3-, and 5-year absolute and SPY-relative labels;
- final-value carry-forward for stocks that delist inside a label window.

## Repository layout

```text
data/
  raw/                 immutable licensed source tables
  interim/             reproducible pipeline artifacts
  datasets/            immutable versioned final datasets
src/
  ingest/              bulk download and Parquet conversion
  identity/            permanent-ID mapping and universe construction
  labels/              quarterly snapshots and forward labels
  features/            planned feature families
  splits/              planned purged/embargoed split tagging
  qa/                  planned and stage-specific data-quality reports
docs/
  decisions/           accepted architecture and modeling decisions
  research/features/   feature research notes and registry
tests/                 fixture-based tests
```

Developer orientation is in [AGENTS.md](AGENTS.md), active work is in
[TODO.md](TODO.md), and conceptual planning is in [PLAN.md](PLAN.md).

## Setup

Requirements:

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Nasdaq Data Link access to Sharadar tables

```bash
uv sync
export NASDAQ_DATA_LINK_API_KEY=...
```

Raw data is licensed and intentionally excluded from Git.

## Running the pipeline

Run individual stages:

```bash
make ingest
make identity
make labels
```

Or invoke their CLIs directly:

```bash
uv run sharadar-ingest download
uv run sharadar-identity
uv run sharadar-labels
```

Existing raw files are preserved by default. An intentional source refresh
requires:

```bash
uv run sharadar-ingest download --force
```

Run tests:

```bash
make test
```

Query any artifact directly:

```sql
SELECT snapshot_kind, count(*)
FROM read_parquet('data/interim/labels.parquet')
GROUP BY snapshot_kind;
```

## Important outputs

| Artifact | Purpose |
|---|---|
| `data/raw/*.parquet` | Immutable Sharadar source snapshots |
| `data/interim/ticker_permaticker.parquet` | Canonical ticker mapping |
| `data/interim/unresolved_tickers.parquet` | Symbols intentionally left unresolved |
| `data/interim/universe.parquet` | Eligible security entities |
| `data/interim/universe_counts_by_year.parquet` | Survivorship-depth report data |
| `data/interim/reports/universe_counts_by_year.png` | M1 universe chart |
| `data/interim/snapshots.parquet` | Quarterly low/median/high entry rows |
| `data/interim/labels.parquet` | Forward-return labels |

## Documentation

- [AGENTS.md](AGENTS.md): fast developer and AI-agent orientation
- [TODO.md](TODO.md): concrete, prioritized development work
- [PLAN.md](PLAN.md): conceptual design and research strategy
- [docs/labels.md](docs/labels.md): exact label conventions
- [docs/decisions/](docs/decisions/): accepted decision records
- [docs/research/features/](docs/research/features/): feature research workspace

## Non-goals

- model training or hyperparameter search;
- portfolio construction and backtesting;
- live data serving;
- a general-purpose data platform.
