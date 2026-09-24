# 0017 — Path-dependent label: forward max drawdown per horizon

Date: 2026-09-24
Status: accepted

## Context

Every stored label is an *endpoint* outcome: the terminal-month average,
point-to-point, and terminal-window min/max prices at the horizon end
(docs/labels.md). A stock that fell 80% in year 1 and recovered is
indistinguishable from one that compounded smoothly to the same CAGR, but
the first one could not have been held in practice. That information about
the path cannot be derived downstream from any stored column. The
training-outcomes review ranked it #3
(`research/dataset-improvements.md` §1.5). PLAN §6 anticipated it: the
labels module is two-stage so path-dependent labels can widen stage 1
without rewriting the label functions.

The same review (§1.4) settled where drawdown *thresholds* belong: a
`label_{H}_maxdd_le_30`-style binary is a one-line comparison once the
continuous drawdown is stored. This follows the label-matrix rule of storing
the continuous value so thresholds can be re-derived without recomputation
(PLAN §6, docs/labels.md).

## Decision

1. **One new continuous column per horizon, `fwd_{H}_max_drawdown`**: the
   largest peak-to-trough fall of the forward adjusted-close path over
   `[snapshot_date, horizon end]` (the same horizon end as the endpoint
   labels), as a **positive fraction**: `max over s ≤ t of 1 − P_t / P_s`.
   `0` means the path never closed below an earlier close. `0.35` means a
   35% fall. The **entry price counts as a peak**, so a fall straight from
   entry is a drawdown. This is the "could I have held it" measure, not a
   measure of drawdown from before the snapshot.
2. **Delisting (decision 0002) needs no new rule**: past the final print
   the forward-filled path is flat, so it adds no peak or trough. A stock
   that delists in window has its drawdown measured over its real prints.
3. **Observability** is the same as for every other label. The column is
   NULL exactly when the horizon is unobservable.
4. **No drawdown binaries are stored.** Thresholds such as
   `fwd_3y_max_drawdown < 0.20` are derived downstream (`value-ml-models`),
   in the same way as custom CAGR rungs. A threshold is promoted to a
   stored `label_*` column only if it becomes a standard target, via an
   amendment here.
5. **Computation (stage 1 / stage 2 split kept)**: a snapshot × day join
   would be about 2B rows at real scale, so it is not used. Stage 1
   (`labels.paths`) compresses each full forward path into
   **calendar-quarter segments** of (max, min, inner drawdown). The segments
   are the suffix of the entry quarter, each full stock-quarter strictly
   between, and the prefix of the exit quarter up to the horizon end. All of
   these are plain window/GROUP BY aggregates over the stock's own prints.
   The triple is closed under concatenation
   (`dd(A·B) = max(A.dd, B.dd, 1 − B.min / A.max)`), so stage 2
   (`labels.compute`) folds the segments in order. The cost is about
   (4H + 1) segment rows per (snapshot, horizon). A synthetic benchmark
   at about ⅓ of real scale ran in about 20 s on 4 cores.

## Consequences

- The label matrix grows by 4 columns. It appears in the next labels build
  and dataset version. Assembly picks it up through the `fwd_` prefix
  (the label-matrix column group), and no split or weight logic changes:
  the drawdown window lies inside `[snapshot_date, snapshot_date + H]`,
  so the purge bound remains exact.
- `path_segments` is the reusable full-path representation. Other
  path-dependent labels can fold the same segments: the interim-low CAGR
  (`research/dataset-improvements.md` §1.5 item 1: `seg_min` over the
  path, versus entry) and, later, triple-barrier labels (first-touch needs
  ordered segments plus a within-segment scan only where a barrier is
  crossed).
- Drawdown is not scaled by volatility or horizon. Longer horizons can only
  have equal or larger drawdowns (the path extends), and high-volatility
  microcaps dominate the upper tail. Downstream thresholds should be chosen
  per horizon, and probably reported next to `vol_12m`/`vol_36m`.
- Tests: `tests/test_labels_cli.py` pins hand-computed values (peak and
  trough in the entry quarter, in middle quarters, and after the horizon
  end in the exit quarter) and checks every (snapshot, horizon) of a
  decaying-sinusoid stock against a brute-force daily scan.
