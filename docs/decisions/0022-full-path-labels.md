# 0022 — Full-path labels: run-up, timing, path average, realized volatility

Date: 2026-11-26
Status: accepted

## Context

Downstream models have not substantially outperformed SPY, and one suspect
is the label itself. Every return label is an *endpoint* outcome — the
terminal-month average H years after the snapshot. The horizon date is
arbitrary: a March 2017 row with a 3-year horizon is scored on March 2020
and counts as a loser whatever it did in between. Decision 0017 stored the
downside of the path (`fwd_{H}_max_drawdown`, `…_from_entry`) but nothing
on the upside, nothing on *when* the extremes came, and no outcome that
does not hang on one date. The terminal-window max (`fwd_{H}_max_cagr`) is
only the best close of the last 21 days.

Two things already soften the endpoint and are worth stating first:
`fwd_{H}_excess_cagr` subtracts SPY over the identical window, so a
market-wide dip at the horizon end hits both legs; and the four horizons
sample one entry at four endpoints. What was missing is the path itself.

## Decision

Per horizon, nine more continuous columns, all NULL exactly when the
horizon is unobservable, all over the same forward-filled path
`[snapshot_date, horizon end]` as decision 0017:

1. **`fwd_{H}_max_runup`** = `max(P) / entry_closeadj − 1`. The best
   mark-to-market gain vs. entry, the mirror of
   `max_drawdown_from_entry`. A plain return (not annualized, like the
   drawdowns); ≥ 0 because the entry day is on the path.
2. **`fwd_{H}_days_to_max`, `fwd_{H}_days_to_min`** = market-calendar
   trading days from entry to the **first** close at the path high / low.
   Ties resolve to the earliest day (a flat or delisted path reports 0).
   Together they order the two extremes — "fell first, peaked later" is
   `days_to_min < days_to_max` — and locate them, which the triple-barrier
   label (still deferred) would otherwise be needed for.
3. **`fwd_{H}_path_avg_return`** = `mean(P) / entry_closeadj − 1`, every
   trading day of the window weighted equally, halts and the
   post-delisting stretch forward-filled (decision 0002's convention, so a
   stock that dies early carries its final close for the rest of the
   window). This is the expected simple return of an exit on a uniformly
   random day: the endpoint-free outcome.
4. **`fwd_{H}_realized_vol`** = `sqrt(252 · Σ r² / n)` over the path's
   log returns, `n` = trading days after entry, uncentered. Forward-filled
   days are zero returns, so a stock delisted early has a low *window*
   volatility by construction — consistent with every other label, which
   also treats the carried position as held.
5. **`fwd_{H}_spy_max_runup`, `fwd_{H}_spy_max_drawdown`,
   `fwd_{H}_spy_max_drawdown_from_entry`, `fwd_{H}_spy_path_avg_return`** —
   the benchmark's own path over the identical window, so every
   stock-path column has its market counterpart and excess versions are
   subtractions downstream. NULL where SPY has no price on or before the
   snapshot date.

**No binaries, no ratios stored** (same rule as decision 0017 §5).
Derived downstream, e.g.:

- endpoint-free beat-the-market: `path_avg_return > spy_path_avg_return`;
- reached +50% at any point: `max_runup >= 0.5`;
- asymmetry: `max_runup / max_drawdown_from_entry`;
- stock-specific pain: `max_drawdown_from_entry − spy_max_drawdown_from_entry`;
- risk-adjusted: `cagr / realized_vol`.

**Computation.** Stage 1 (`labels.paths`) widens the quarter segments of
decision 0017. Each segment also carries the calendar index of the first
print at its max and at its min (`max`/`min` over a `(price, ∓index)`
struct — deterministic on ties) and two additive totals: the
time-weighted price sum (each print weighted by the trading days to the
stock's next print; the path's last print re-weighted to the horizon end)
and the sum of squared log returns. Stage 2 folds them with `max`, `min`
and `sum`. The benchmark is one series, so its path statistics are a
plain range join over the forward-filled calendar (distinct snapshot
dates × path days, about 20M rows at real scale). Still nothing scales
with snapshots × days.

## Consequences

- The label matrix grows by 36 columns (nine per horizon); they reach the
  dataset through the `fwd_` prefix like the rest. No split or weight
  logic changes: the window is `[snapshot_date, snapshot_date + H]`, so
  the purge bound stays exact.
- Build cost: on a synthetic world at about a third of real scale (13M
  price rows, 612k snapshots) `sharadar-labels` went from 35 s to 69 s on
  24 cores. Not measured on real data.
- `fwd_{H}_max_runup` is dominated by microcaps the same way the upper
  drawdown tail is (the Foamex class of sub-5-cent paths,
  `research/2026-11-26-foamex-price-path-reply.md`): a 400x run-up is a
  recorded price, not an investable one. Threshold or clip it downstream
  and pair it with `dollar_volume_3m`; it is not winsorized here.
- `path_avg_return` is a simple average of price relatives, not a CAGR:
  for a steadily compounding stock it is roughly the return at mid-window.
  Compare it across rows of the same horizon, or against
  `spy_path_avg_return`; do not compare it with `fwd_{H}_cagr`.
- Tests: `tests/test_labels_cli.py` checks all nine columns for every
  (snapshot, horizon) of five stocks against a brute-force forward-filled
  daily scan — including a stock delisted inside its entry quarter, one
  delisted mid-path and one that halts across a quarter boundary and
  resumes — and pins hand-computed values.
