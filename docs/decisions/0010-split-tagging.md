# 0010 — Purged/embargoed split tagging: schema, fold schedule, embargo

Date: 2026-07-15
Status: accepted

## Context

M5 begins with split tagging. PLAN §7 fixes the theory: rows are serially
and cross-sectionally dependent, so temporal splits must be **purged per
horizon** and **embargoed**, low/high snapshot kinds are training-only, and
the tagging schema `(scheme, fold, horizon) → {train | test | purged |
embargoed}` must not preclude CPCV later. PLAN §7.6 requires the notes from
the required reading to land here before `src/splits/` is written. What the
plan leaves open is everything concrete: the exact overlap condition against
*our* label windows, where the embargo sits, the fold calendar, the holdout
definition, and the physical schema.

### Notes from the reading

- **de Prado ch. 7 (purged k-fold + embargo).** Purging drops from training
  any observation whose label interval `[t0, t1]` overlaps any test label
  interval. Our label for `(snapshot_date, H)` is a function of prices in
  `(snapshot_date, snapshot_date + H]` — the terminal averaging window is
  the *trailing* 21 trading days ending at the horizon end, and the horizon
  end is the last trading day on or before the nominal end `snapshot_date +
  H` (docs/labels.md). So `t1 = snapshot_date + H` (nominal) is a correct,
  slightly conservative upper bound on label information. Test label
  intervals begin at `test_start` at the earliest, so for training rows that
  precede the test period the exact overlap condition collapses to the
  boundary condition `snapshot_date + H ≥ test_start`.
- **Embargo placement.** In de Prado's k-fold, training data sits on *both*
  sides of the test block, and the embargo is applied to training rows
  immediately **after** test end (purging already handles the before side).
  Our v1 schemes (expanding-window walk-forward + sealed holdout) have no
  post-test training data at all, so the k-fold embargo would be a no-op.
  PLAN §7.2 instead mandates the embargo on the *pre-test* side — on top of
  purging — to absorb serial correlation in features and returns that does
  not end cleanly at the label-window boundary (features are built from
  trailing windows; returns are autocorrelated across the cutoff). Cheap
  insurance, per-fold cost is one embargo of data. CPCV (v2) reintroduces
  post-test training data and will need the post-test embargo as well; the
  role-per-(scheme, fold) schema below supports that without change.
- **de Prado ch. 11–12 (backtest dangers, CPCV).** One walk-forward path is
  a single draw of history; CPCV's value is variance estimation. Reserved
  for v2, schema-compatible (`scheme` is an open enum; a CPCV fold is just
  another `(scheme, fold)` with its own role assignment).
- **Bailey/Borwein/de Prado/Zhu (PBO).** The number of configurations tried
  must be recorded — an invariant enforced in `value-ml-models`, not here.
  The dataset side's contribution: fold definitions are **frozen artifacts**
  (a published fold manifest, below), so trials downstream cannot quietly
  redefine folds and reset the trial count.

## Decision

1. **Physical schema: one long tag table**, `data/interim/splits.parquet`:

   ```
   (scheme, fold, horizon_years, permaticker, snapshot_date, snapshot_kind, role)
   ```

   `role ∈ {train, test, purged, embargoed}`. **Absence means out of fold**
   (rows on/after the test period that aren't test rows, low/high kinds
   inside the test window, unobservable-label rows). `purged`/`embargoed`
   are tagged explicitly rather than silently dropped so QA can price what
   the boundary costs. Splits are *tags*, never filters — no labels/features
   row is removed (survivorship invariant untouched).

2. **Fold manifest**, `data/interim/split_folds.parquet`: one row per
   `(scheme, fold, horizon_years)` with `test_start`, `test_end`,
   `embargo_days`, and per-role row counts. This is the frozen fold
   definition downstream code consumes and reports must cite.

3. **Role assignment** for a fold with test period `[test_start, test_end)`,
   horizon `H`, embargo `E` days:
   - `train`: `snapshot_date + H years + E days < test_start`. All three
     snapshot kinds. (PLAN §7.2's full eligibility condition.)
   - `embargoed`: fails only the embargo —
     `snapshot_date + H < test_start ≤ snapshot_date + H + E`.
   - `purged`: `snapshot_date < test_start` and
     `snapshot_date + H ≥ test_start` (label window reaches the test period).
   - `test`: `test_start ≤ snapshot_date < test_end`, **`snapshot_kind =
     'median'` only** (decision 0001 / PLAN §4: a real portfolio enters at
     one price), and the horizon must be observable
     (`delisted_in_window_{H} IS NOT NULL`).

4. **Fold calendar: calendar-year test periods; `fold` = test start year
   (INTEGER).** Quarterly snapshots make finer folds pointless, and yearly
   folds keep the manifest legible.
   - **`holdout`** (per horizon): one fold; test period starts
     `Jan 1 of (last observable snapshot year − holdout_years + 1)` and is
     unbounded above (`test_end = 9999-12-31`). Default `holdout_years = 3`.
     Because observability is per-horizon, holdout covers different eras per
     horizon by construction (PLAN §7.5) — e.g. 5y holdout ends ~4 years
     before 1y holdout.
   - **`walkforward`** (per horizon): expanding-window folds with test year
     `Y` running from `first_snapshot_year + min_train_years + H` (so the
     first fold has ≥ `min_train_years` of post-purge training span;
     default `min_train_years = 5`) through `holdout_start_year − 1`
     (model selection never touches holdout). Horizons whose range is empty
     get no walk-forward folds — with defaults, real data still yields
     15–20 folds per horizon.
   - **`cpcv`**: reserved, no v1 implementation.

5. **Embargo default: 30 calendar days**, parameterized (`--embargo-days`).
   de Prado's guidance is a small fraction of the sample period; 30 days on
   ~28 years is ~0.3%, and one month matches PLAN §7.2's default.

6. All boundaries are **derived from the data** (min snapshot year, max
   observable snapshot year per horizon, from `labels.parquet`) plus the
   three parameters — no hardcoded dates — and frozen into the manifest at
   build time.

## Consequences

- Downstream selects a training set with
  `role = 'train' AND scheme/fold/horizon = …` and inherits purge + embargo
  + kind rules for free; it cannot accidentally train on low/high test-era
  rows because those rows simply have no tag in that fold.
- The tag table is long (every fold × eligible row), ~10⁷–10⁸ rows on real
  data — fine for parquet/DuckDB, and the price of making `purged`/
  `embargoed` first-class inspectable rather than implicit.
- Training rows are provably label-observable (their windows end before
  `test_start`, which is on or before the last observable date), so no
  NULL-label rows can enter training via the tags.
- Per-horizon walk-forward folds share test years where ranges overlap, so
  cross-horizon comparisons at a fixed test year remain possible; holdout
  eras differ per horizon and reports must say so (PLAN §7.5).
- Uniqueness weights (`sample_weight`, de Prado ch. 4) are **not** part of
  split tagging — they are within-train density corrections and land at
  assembly, where the overlap-counting question in TODO.md gets its own
  decision.
