# Canonical split-tag definitions (M5)

Produced by `sharadar-splits` (`src/splits/`), consuming
`data/interim/labels.parquet`. Two outputs under `data/interim/`:

- `splits.parquet` — one row per (scheme, fold, horizon, snapshot) that
  participates in the fold, with its role
- `split_folds.parquet` — the frozen fold manifest (one row per
  scheme × fold × horizon, with boundaries and role counts)

Design decisions: [decisions/0010](decisions/0010-split-tagging.md);
theory in PLAN.md §7. Splits are **tags, never filters** — no labels or
features row is dropped.

## `splits.parquet` columns

| column | type | meaning |
|---|---|---|
| `scheme` | varchar | `holdout` \| `walkforward` (`cpcv` reserved for v2) |
| `fold` | integer | test-period start year (calendar-year folds) |
| `horizon_years` | integer | the label horizon this tag applies to |
| `permaticker` | — | snapshot key, as in `labels.parquet` |
| `snapshot_date` | — | snapshot key |
| `snapshot_kind` | — | snapshot key (`low` \| `median` \| `high`) |
| `role` | varchar | `train` \| `test` \| `purged` \| `embargoed` |

**Absence means out of fold**: rows on/after the test period that are not
test rows, low/high kinds inside the test window, and unobservable-label
rows in the test window carry no row for that (scheme, fold, horizon).

## Role definitions

For a fold with test period `[test_start, test_end)`, horizon `H`
(calendar years, nominal) and embargo `E` (calendar days):

| role | condition |
|---|---|
| `train` | `snapshot_date + H + E < test_start` — all three kinds |
| `embargoed` | `snapshot_date + H < test_start ≤ snapshot_date + H + E` |
| `purged` | `snapshot_date < test_start ≤ snapshot_date + H` |
| `test` | `test_start ≤ snapshot_date < test_end`, **median kind only**, horizon observable (`delisted_in_window_{H}` not NULL) |

`purged`/`embargoed` are the rows a naive temporal split would have
(leakily) trained on; they are tagged explicitly so QA can price the
boundary cost. Low/high snapshot kinds are training-only (PLAN §4):
a real portfolio enters at one price.

## Fold calendar

Derived from the data at build time and frozen into the manifest; per
horizon, with `first_year` = earliest snapshot year and `last_year` =
latest snapshot year with an observable label at that horizon:

- **`holdout`** — one fold: `fold = last_year − holdout_years + 1`,
  test period `[Jan 1 of fold, ∞)` (`test_end = 9999-12-31`). Sealed:
  evaluated once per project phase, never used for model selection.
  Observability is per-horizon, so holdout covers different eras per
  horizon by construction (PLAN §7.5).
- **`walkforward`** — expanding-window folds, one per test year from
  `first_year + min_train_years + H` through `fold(holdout) − 1`;
  test period `[Jan 1 of Y, Jan 1 of Y+1)`. Horizons whose range is
  empty get no walk-forward folds.

Defaults: `--embargo-days 30`, `--holdout-years 3`, `--min-train-years 5`.

## `split_folds.parquet` columns

`scheme`, `fold`, `horizon_years`, `test_start`, `test_end`,
`embargo_days`, `n_train`, `n_test`, `n_purged`, `n_embargoed`.

This manifest is the frozen fold definition: downstream code selects
training data as `role = 'train'` for a (scheme, fold, horizon) and must
cite the manifest in reports (the PBO trial-count invariant in
`value-ml-models` depends on folds not being quietly redefined).
