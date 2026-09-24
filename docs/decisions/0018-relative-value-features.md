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
   `netinc`, `fcf`, `shares` (`sharesbas × sharefactor`), `datekey` and
   `reportperiod`.

2. **Historical market cap per bucket** — the ADR 0007 self-built
   convention, applied at the bucket: `close × shares` of that bucket's
   filing, `close` = SEP `close` (as in ADR 0007) on the last trading day on
   or before the **anchor** `least(datekey, reportperiod + 45 days)`.
   - `reportperiod + 45d` (the 10-Q deadline) gives a seasonally stable
     anchor that doesn't drift with late amendments (a restated version
     with a years-later `datekey` still prices near its own period).
   - The cap at `datekey` keeps the anchor at or before the version's own
     availability date, hence before the snapshot (`<=` for inference,
     ADR 0014): no price after the snapshot can enter.
   - A print more than **14 days** older than the anchor is not used
     (pre-listing fundamentals, trading halts): the bucket is unpriced.
   - Split basis (same exposure as ADR 0007's snapshot marketcap): the
     product `close × shares` is only right if both factors are on the
     same split basis *at the anchor*. If SEP `close` and SF1 `sharesbas`
     are both restated to today's split basis, a split anywhere is
     harmless; if both are as-of-the-day values, a split between the
     share-count date and the anchor (a window of days to ~6 weeks)
     mis-scales that one bucket by the split ratio. The ADR 0007
     replication (~98% of rows within 1% of DAILY in every year) rules
     out a *mixed* basis, which would misprice every pre-split row, but
     does not tell the other two cases apart. A single mis-scaled bucket
     moves the median by at most one rank position and the percentile by
     at most 1/n; the fix, if the QA check finds the case real, is to
     NULL buckets with an ACTIONS split between share-count date and
     anchor (an open follow-up, not done here).

3. **Ratios**: the six marketcap-denominated valuation yields —
   `earnings_yield`, `ocf_yield`, `fcf_yield` (ART TTM `netinc` / `ncfo`
   / `fcf`), `sales_yield` (ART TTM `revenue`), `book_to_market` and
   `tangible_book_to_market` (ARQ `equity` / `tangibles`) — same
   numerators and order as the valuation family. The EV-denominated
   yields are left out: a historical EV needs the bucket's debt and cash
   too, and adds little beside `ebit`/`ebitda` ≈ earnings. Earnings and
   cash-flow yields change sign; the percentile handles that natively,
   and the median ratio is NULL unless the historical median is > 0.
   Given a positive median the ratio is monotone in the current value,
   so a current loss or cash burn is kept (below 0), not nulled.

4. **Statistics over the 20q window** (`qoff 0…19`), current value = the
   snapshot-date ratio (identical to the valuation family's column):
   - `{r}_vs_5y_median` = current ÷ median(historical values); > 1 ⇒
     cheaper than its own norm. NULL when the median ≤ 0 (registry null
     rule); a negative current numerator is kept (yield orientation).
   - `{r}_5y_pctile` = `(#hist < cur + ½·#hist = cur) / n` — midrank
     percentile, bounded [0, 1], outlier-immune.
   Both need **≥ 11 priced historical values** (ADR 0015's 20q rule) and
   a current value. Tier T5.

5. **Rank policy** (ADR 0016): `*_vs_5y_median` is continuous and fully
   ranked (`sales_yield_vs_5y_median` pinned at raw 0 → rank 0, the "revenue
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
  dataset pick it up through the registry. Twelve columns, plus six rank
  columns at assembly.
- Dataset **v1.3** (`added_in_version: "1.3"`; `sharadar-assemble`
  default bumped). Additive: no existing column changes.
- Burn-in matches the 20q trend features: populated from ~11 quarters of
  listed history, i.e. from ~2001 on the ~1998 data floor, and not for
  recent IPOs' first ~3 years (pre-listing buckets are unpriced). These
  rows stay NULL, never dropped: a missing own-history is itself signal
  for the downstream models.
- The shorter windows (4/8/12q) and further ratios are additive registry
  changes if the 5y version earns its keep downstream.
- Tests: `tests/test_features_relvalue.py` pins hand-computed values for
  the median ratio, tie-aware percentile, the min-count boundary, the
  pre-listing/stale-price guard, and a loss-maker's non-positive median
  (median ratio NULL, percentile defined).
