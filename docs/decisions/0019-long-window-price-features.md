# 0019 — Long-window price features: 5-year anchors, long-term reversal, MAX, beta

Date: 2026-09-24
Status: accepted

## Context

`docs/research/dataset-improvements.md` §2.2 lists price-only features
that carry much of the "discount vs. the stock's own past" signal of the
relative-value family (ADR 0018) without any fundamentals matching: the
stock's own long drawdown, a slow mean-reversion anchor, long-term
reversal, and — optionally — two well-documented cross-sectional
predictors, the lottery/MAX factor and market beta. The technical family
(ADR 0005 §3) stops at 3 years (`vol_36m`) and has no benchmark input.

## Decision

1. **Five technical-family columns** (dataset v1.3), all from
   `SEP.closeadj` on the dense trading-day index like the rest of the
   family:
   - `dist_5y_high` = `closeadj / max(closeadj over t−1260…t) − 1` — the
     stock's own drawdown at entry; separates "off its long-run peak" from
     "off a recent blip" (`dist_52w_high`).
   - `price_vs_5y_avg` = `closeadj / mean(closeadj over t−1260…t) − 1` —
     slow mean-reversion anchor.
   - `mom_36_12` = total return t−756 → t−252 (De Bondt–Thaler long-term
     reversal; the deep-value companion of `mom_12_2`), with the family's
     as-of reference prices (21-day staleness band).
   - `max_ret_21d` = largest one-day return over the last 21 trading days
     (Bali–Cakici–Whitelaw MAX).
   - `beta_12m` = `regr_slope` of the stock's daily log returns on the
     benchmark's over the last 252 trading days.

2. **New tier P60** (1260 trading days) for the two 5-year anchors. They
   need **≥ 1000 prints** in the window (the same ~80% coverage as
   `vol_36m`'s 600/756), otherwise NULL: over a younger listing a
   "5-year high" is a different quantity, and a missing long history is
   itself signal for the models — NULL, never a shorter-window stand-in.

3. **One-day returns only for MAX and beta.** `sep_ix` gains `prev_ix`
   (the calendar index each return starts from); these two features use
   only returns with `prev_ix = ix − 1`, and the beta additionally only
   benchmark returns with the same property. A thin stock's multi-day jump
   is neither a daily MAX nor comparable with a one-day market move.
   `max_ret_21d` needs ≥ 15 such returns; `beta_12m` ≥ 200 pairs (the
   `vol_12m` minimum).

4. **Benchmark in the features pipeline.** The beta's market is the
   labels module's benchmark (SFP `SPY` `closeadj`, `labels.source.
   BENCHMARK_TICKER`), exposed as the `benchmark_ix` source view. SFP
   becomes a required input of `sharadar-features` and
   `sharadar-inference` (missing ⇒ exit 2 with the ingest hint; it was
   already required by `sharadar-labels`).

5. **Rank policies** (ADR 0016): `dist_5y_high` pinned at raw 0 → rank 1
   (at the 5-year high, like `dist_52w_high`); `max_ret_21d` pinned at
   raw 0 → rank 0 (no up day in the month — a flat illiquid stock's mass;
   the rare all-down month shares that bottom rank); the other three are
   full ranks.

## Consequences

- The technical family's per-snapshot price join widens from 756 to 1260
  trading days (≈1.7× rows in that join); `vol_36m` keeps its 756-day
  window through an explicit filter.
- Burn-in: 5-year anchors populate from ~2003 on the ~1998 data floor and
  only for stocks with ~4 years of prints; `mom_36_12` needs a print near
  t−756. Missing stays NULL.
- `beta_12m` is a plain daily OLS beta: nonsynchronous trading biases
  thin stocks' betas toward 0 (Scholes–Williams / Dimson corrections are
  a possible later refinement). It is a stock-level characteristic, not a
  market-regime feature: no market level enters the feature, so the
  PLAN §5.6 date-identifier concern does not apply.
- Tests: `tests/test_features_technical_long.py` pins hand-computed
  values on piecewise-constant paths, an exact-beta stock, and thin
  traders whose multi-day returns would change MAX and beta if they were
  admitted.
