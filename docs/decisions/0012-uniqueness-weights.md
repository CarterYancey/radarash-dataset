# 0012 — Uniqueness weights: exact per-horizon average uniqueness, kinds pooled

Date: 2026-07-18
Status: accepted

## Context

PLAN §7.2 keeps overlapping rows inside training sets and compensates with
a per-horizon `sample_weight` column ≈ the average uniqueness of the row's
label (de Prado, *AFML* ch. 4). TODO left the details open: the exact
overlap counting, and whether the three low/median/high snapshots of a
stock-quarter share a weight pool with each other. Assembly (M5) is where
the column is computed, so the question had to be resolved now.

## Decision

1. **Definition.** For horizon `H`, a row's label window is the nominal
   calendar interval `[snapshot_date, snapshot_date + H years]` (inclusive;
   the same interval the purge rule bounds — the trailing terminal-average
   window never extends past the nominal end, docs/labels.md). Let
   `c(t)` = the number of horizon-`H` windows **of the same permaticker**
   (all three snapshot kinds) containing calendar day `t`. Then

   ```
   sample_weight_{H} = mean over days t in the window of 1 / c(t)
   ```

   — de Prado's average uniqueness, computed **exactly at day granularity**.
   `c(t)` is piecewise constant with breakpoints only at window starts and
   ends, so the mean is evaluated as a cumulative-integral difference over
   those breakpoints (O(rows) work, no per-day expansion); implementation
   in `src/assemble/weights.py`.
2. **The three snapshot kinds share one pool.** `c(t)` counts all kinds of
   the permaticker, so an isolated stock-quarter's three rows weigh ~1/3
   each. PLAN §4 already states the low/median/high rows "receive
   uniqueness weights like any other overlapping rows": they are three
   entries into one mostly-shared forward outcome, and a stock-quarter
   should carry roughly the same total weight whether the pipeline emits
   one entry price or three. Not pooling them would triple the weight of
   every stock-quarter for no informational gain — exactly the
   overrepresentation the column exists to prevent.
3. **Same-stock overlap only.** `c(t)` is per permaticker, following
   de Prado's per-instrument concurrency. Cross-sectional dependence
   (different stocks, shared market path — PLAN §7.1) is real but is not a
   row-weighting problem: downweighting every stock in a dense era by the
   size of the cross-section would just shrink whole eras relative to
   thin ones. It stays handled where it belongs — purged temporal splits
   for measurement honesty, and evaluation-confidence caveats (PLAN §7.5).
4. **NULL when the horizon is unobservable** (`delisted_in_window_{H}` is
   NULL): a row with no label at `H` cannot be trained on at `H`, and a
   number there would invite silent misuse. Delisting inside the window
   does *not* shrink the window — the label still spans the full interval
   (the position is carried at the final print, decision 0002), so its
   overlap with sibling windows is unchanged.
5. **No normalization.** The stored weight is the raw average uniqueness in
   (0, 1]. Downstream training code normalizes per training set if its
   estimator wants that; baking a normalization into the dataset would tie
   the column to one split scheme. The per-era sums (an honest
   effective-sample-size estimate, PLAN §7.2) are logged at assembly time
   and recorded in the dataset manifest.

## Consequences

- An isolated stock-quarter's rows carry exactly 1/3; a stock snapshotted
  quarterly for years carries ~`1 / (3 · 4H)` per row at horizon `H` —
  long horizons no longer dominate training by sheer overlap count.
- Weights depend only on `labels.parquet` (snapshot dates per permaticker
  + observability), not on features or splits: re-assembling with a new
  feature set leaves them bit-identical.
- `splits-diag`'s label-variance decomposition and twin test (decision
  0010) remain the empirical check on whether same-stock overlap was the
  right thing to weight; if the leakage-gap experiment ever shows
  cross-sectional overlap dominating, revisiting §3 is a new ADR.
- The three-kinds pooling means a model trained on all kinds sees the
  margin-of-safety gradient (decision 0001) at unchanged total weight per
  stock-quarter, preserving comparability with a median-only ablation.
