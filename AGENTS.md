# Developer and agent guide

This file is the shortest safe orientation for implementation work. Do not use
README as the technical specification.

## Read by task

Always read:

1. this file;
2. [TODO.md](TODO.md) for current scope;
3. the relevant source module and tests.

Then read only what the task needs:

| Work | Required context |
|---|---|
| Identity or universe | `docs/decisions/0001-*.md`, `0002-*.md` |
| Labels | `docs/labels.md`, `docs/decisions/0003-*.md` |
| Features | feature section of `PLAN.md`, then `docs/research/features/` |
| Point-in-time joins | point-in-time section of `PLAN.md` |
| Splits | temporal validation section of `PLAN.md` |
| New convention | relevant research plus a new `docs/decisions/NNNN-*.md` |

## Commands

```bash
uv sync
make test
make ingest       # requires NASDAQ_DATA_LINK_API_KEY
make identity
make labels
```

Individual CLIs are `sharadar-ingest`, `sharadar-identity`, and
`sharadar-labels` under `uv run`.

## Non-negotiable invariants

- Parquet is the storage format for every tabular artifact.
- Use DuckDB for tabular transforms and analytical joins.
- Raw files are immutable unless a refresh is explicitly requested.
- `permaticker` is the entity key. Ticker is only a source join key.
- Never infer ticker history from `TICKERS.relatedtickers`.
- Keep unresolved identifiers visible; never assign them heuristically.
- Include delisted stocks throughout universe and label construction.
- Features may use only information public before the snapshot.
- SF1 feature availability is based on `datekey`, not `calendardate` or
  `reportperiod`; use ARQ/ART, never MRQ/MRT/MRY.
- Missing feature values remain null unless a documented feature explicitly
  defines another value.
- Do not silently drop rows with unavailable future labels; recent horizons are
  expected to be null.
- Do not randomly split rows. Temporal split logic must purge overlapping label
  windows and apply the configured embargo.

## Current domain rules

Universe:

- Sharadar table must be SEP.
- Include Domestic Common Stock and Domestic Common Stock Primary Class.
- Include REITs and delisted securities.
- Exclude financials when SIC is 6000–6499 or sector is Financial Services.
- Exclude ADRs, funds, warrants, preferreds, and non-primary secondary classes.

Snapshots:

- Emit low, median, and high rows for every stock-quarter.
- Use adjusted close.
- Median is the observed discrete median.
- When an extremum or median repeats, choose the earliest date.
- Preserve all three kinds when dates coincide.

Labels:

- Horizons are 1, 2, 3, and 5 years.
- Primary endpoint is the 21-trading-observation mean ending at the horizon.
- Retain point-to-point, terminal min/max, absolute thresholds, and SPY-relative
  outcomes.
- If delisted in-window, carry the final positive SEP adjusted close unchanged
  to the horizon.
- `delisted_in_window_H` is VARCHAR: `False` or an ACTIONS reason.

## Engineering practices

- Keep modules batch-oriented and simple; do not add a service or ORM.
- Prefer explicit SQL and small orchestration functions.
- Write outputs to temporary files, validate them, then atomically replace.
- Give every generated table a stable schema and deterministic ordering.
- Fail loudly on broken uniqueness, row-count, or identifier assumptions.
- Tests must use synthetic fixtures and must not require licensed raw data.
- Add full-data invariant queries when behavior cannot be demonstrated by a
  small fixture alone.
- Do not commit raw/interim/dataset artifacts.
- Preserve unrelated working-tree changes and untracked user files.

## Definition of done

For implementation changes:

1. fixture tests cover the key rule and its boundary cases;
2. `uv run pytest -q` passes;
3. `uv run python -m compileall -q src` passes;
4. `git diff --check` passes;
5. generated schemas and row-count invariants are inspected when applicable;
6. README changes are limited to user-facing behavior;
7. TODO, PLAN, research notes, or decision records are updated in the
   appropriate place.

## Documentation ownership

- `README.md`: stable overview, architecture, setup, and commands.
- `AGENTS.md`: implementation orientation and invariants.
- `TODO.md`: concrete work, ordered roughly by priority.
- `PLAN.md`: conceptual design, research questions, and validation strategy.
- `docs/research/`: evidence, formulas, comparisons, and exploratory findings.
- `docs/decisions/`: accepted decisions and their rationale.
- module docs such as `docs/labels.md`: exact produced-data contracts.

When research resolves an open question, summarize the accepted answer in a
decision record and remove the corresponding TODO. Do not let PLAN become a
second task tracker.
