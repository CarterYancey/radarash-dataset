# 0014 — Inference dataset: label-free snapshot at the latest available prices

Date: 2026-07-22
Status: accepted

## Context

The training dataset (`dataset_vX.Y`) exists to fit and honestly evaluate
models, so every row carries forward-looking labels, split tags, and
uniqueness weights. Deploying a trained model needs the opposite: a
feature matrix for *today's* (or the latest ingested) stocks, where labels
cannot exist yet. Rebuilding that by hand invites train/serve skew — the
features and ranks a deployed model consumes must be computed by the exact
code that produced its training columns.

Three questions had to be settled: what a "latest" snapshot is, whether a
filing published on the snapshot day itself is usable, and what
cross-section the ranks (decision 0008 makes ranks the primary model
inputs) are computed over when there is only one snapshot date.

## Decision

A separate CLI, `sharadar-inference` (`src/inference/`, `make inference`),
consuming only the ingest + identity artifacts (SF1, SEP, mapping,
universe) and producing an immutable `data/datasets/inference_{as_of}/`
with `dataset.parquet` + `manifest.json`. It reuses the training feature
machinery verbatim — the same source views, `fund_base`, family builders,
registry validation, and assembly rank pass — pointed at a different
snapshot table.

### Snapshot definition

- `as_of` = the last trading date in SEP on or before the requested date
  (default: the last date in SEP). One row per in-universe stock whose
  most recent trade is within `--max-price-age-days` (default 5) *trading
  days* of `as_of` — tolerating halts and thin prints without readmitting
  delisted stocks. Everything here is deliberately *not*
  survivorship-corrected: inference scores the stocks one can actually buy.
- `snapshot_date` = the stock's own last trade date; `entry_closeadj` = its
  adjusted close that day. Technical windows and marketcap anchor on a real
  print rather than a gap.
- `snapshot_kind` = `'inference'` (never a training kind; the splits rule
  that low/high kinds are training-only is moot here, but the distinct kind
  keeps inference rows unmistakable if they ever meet training data).

### Same-day filings are point-in-time-usable

Training resolves T0 with `datekey < snapshot_date` because entry happens
*at* the snapshot date's close — a filing dated that day may postdate the
entry. An inference row's entry hasn't happened yet: the model runs after
the close of `snapshot_date` and the earliest actionable entry is the
next trading day. Relative to that entry, every filing with
`datekey <= snapshot_date` is public — the same "usable the first trading
day strictly after `datekey`" rule (PLAN §2), evaluated one day later. So
`fund_base` gains an `include_same_day_filings` flag (T0 and lag resolution
both become inclusive); inference sets it, training semantics are
untouched. This is what "latest fundamentals" means operationally: the
freshest filing a deployed run could really act on.

### Ranks over the single inference cross-section

`quarter` is set uniformly to the calendar quarter of `as_of` (it is a
rank-partition key, not a feature), so the decision-0008 rank pass —
`percent_rank()` within (quarter, snapshot_kind) — ranks the entire
inference cross-section together even when per-stock snapshot dates
straddle a quarter boundary. Guards keep their training defaults
(`--rank-guard 20`, `--min-industry-peers 5`). All assembly-stage
composites (`mohanram_g7`, `conservative_score`, decision 0013) are
computed identically.

### What is deliberately absent

No labels, no split files, no `sample_weight_{H}y` — nothing forward of
the latest price is observable, and weights exist to de-overlap label
windows that don't exist here. The column layout is otherwise identical to
`dataset.parquet` (key + entry metadata, features, ranks, sector ranks, in
registry order), so a model trained on `dataset_vX.Y` selects its feature
columns by name and scores the inference parquet directly.

## Consequences

- Deployment consistency by construction: any change to a family formula
  or the rank mechanics propagates to inference on the next run; there is
  no second implementation to drift.
- The inference cross-section is intentionally survivor-only (today's
  tradable stocks). It must never be used for training or evaluation —
  that is what `dataset_vX.Y` and its splits are for.
- `fundamentals_age_days` can now be 0 (same-day filing); downstream
  filters using the meta flags are unaffected.
- A model comparing its training-quarter rank distributions with inference
  ranks should expect the inference cross-section to be one pooled
  partition — same convention, same guards, different date density.
- `data/datasets/inference_{as_of}/` is immutable like dataset versions
  (`--force` rebuilds); re-ingesting fresher SEP/SF1 naturally yields a new
  `as_of` directory.
