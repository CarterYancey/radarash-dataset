# 0018 — Relative-value family: valuation against the stock's own 20-quarter history

Date: 2026-09-24
Status: accepted

## Context

`docs/research/dataset-improvements.md` §2.1 ranks "discount relative to
its own past" as the strongest feature addition: every valuation feature
is a point-in-time *level*, and the rank pass (ADR 0008/0016) compares a
stock with the *cross-section*. Nothing expresses "this stock is cheaper
than it usually is" — the distinction between *cheap* and *structurally
low-multiple* that a value screen draws by hand, and the stated weakness of
models trained on v1.x.

Computing it needs a historical valuation per past quarter, i.e. a
point-in-time historical market cap. The ADR 0015 `fund_history` view
already resolves, per snapshot, the version of each of the last 20
quarterly filings known at the snapshot date; it only lacks a price.

## Decision

1. **New family `relvalue`** ("Relative value" in docs/features.md,
   `src/features/relvalue.py`), built after `trend` from the existing
   foundation views; `fund_history` gains the bucket filing's `equity`,
   `shares` (`sharesbas × sharefactor`), `datekey` and `reportperiod`.

2. **Historical market cap per bucket** — the ADR 0007 self-built
   convention, applied at the bucket: `close × shares` of that bucket's
   filing, `close` = the unadjusted SEP close on the last trading day on
   or before the **anchor** `least(datekey, reportperiod + 45 days)`.
   - `reportperiod + 45d` (the 10-Q deadline) gives a seasonally stable
     anchor that doesn't drift with late amendments (a restated version
     with a years-later `datekey` still prices near its own period).
   - The cap at `datekey` keeps the anchor at or before the version's own
     availability date, hence before the snapshot (`<=` for inference,
     ADR 0014): no price after the snapshot can enter.
   - A print more than **14 days** older than the anchor is not used
     (pre-listing fundamentals, trading halts): the bucket is unpriced.
   - Accepted noise, as in ADR 0007: shares are as of the period end, so
     a split between period end and anchor mis-scales that one bucket.

3. **Ratios**: `sales_yield` (ART TTM revenue) and `book_to_market` (ARQ
   equity) — the most stable denominators. Earnings/cash-flow yields
   change sign too often for a median of ratios to be meaningful; they are
   candidates for a later version only with a sign-aware form.

4. **Statistics over the 20q window** (`qoff 0…19`), current value = the
   snapshot-date ratio (identical to the valuation family's column):
   - `{r}_vs_5y_median` = current ÷ median(historical values); > 1 ⇒
     cheaper than its own norm. NULL when the median ≤ 0 (registry null
     rule); a negative current numerator is kept (yield orientation).
   - `{r}_5y_pctile` = `(#hist < cur + ½·#hist = cur) / n` — midrank
     percentile, bounded [0, 1], outlier-immune.
   Both need **≥ 11 priced historical values** (ADR 0015's 20q rule) and
   a current value. Tier T5.

5. **Rank policy** (ADR 0016): `*_vs_5y_median` is continuous and ranked
   (`sales_yield_vs_5y_median` pinned at raw 0 → rank 0, the "revenue
   went to zero" mass, mirroring `sales_yield`). `*_5y_pctile` is a share
   over ≤ 20 observations with masses at 0 and 1 — **not ranked**, like
   `*_up_frac_*`. This deviates from the research sketch (which proposed
   `sales_yield_5y_pctile_rank`): that sketch predates ADR 0016, and a
   ranked tied mass at 1 would be a quarter key. The cross-sectional
   question it posed is served by `sales_yield_vs_5y_median_rank`.

6. **Splits unchanged** (ADR 0004 §4 / ADR 0015 §9): trailing feature
   windows don't move the purge/embargo bound.

## Consequences

- `FAMILIES` gains `relvalue`; assembly, QA coverage and the inference
  dataset pick it up through the registry. Four columns, plus two rank
  columns at assembly.
- Dataset **v1.3** (`added_in_version: "1.3"`; `sharadar-assemble`
  default bumped). Additive: no existing column changes.
- Burn-in matches the 20q trend features: populated from ~11 quarters of
  listed history, i.e. from ~2001 on the ~1998 data floor, and never for
  recent IPOs' first ~3 years (pre-listing buckets are unpriced).
- The shorter windows (4/8/12q) and further ratios are additive registry
  changes if the 5y version earns its keep downstream.
- Tests: `tests/test_features_relvalue.py` pins hand-computed values for
  the median ratio, tie-aware percentile, the min-count boundary, and the
  pre-listing/stale-price guard.
