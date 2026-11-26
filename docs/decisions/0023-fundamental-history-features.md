# 0023 — Fundamental-history features: today vs. the stock's own record

Date: 2026-11-26
Status: accepted

## Context

A fundamentals investor reads a number against the company's history: a
drop in book value or in earnings yield means one thing after ten steady
years and another at the end of a long slide. The registry carried little
of that. The level families describe the current filing; growth compares
it with one to three years back; trend (decision 0015) fits the direction
of revenue, tangible book and operating cash flow; relative value
(decision 0018) compares today's *price multiple* with its own past.
Missing: whether today's *profitability* is normal for the company, what
it earns on average rather than this year, how far and how recently it
fell from its own best, whether the latest quarter surprised, and
anything beyond five years except dividends.

## Decision

A new family `fundhist` (31 columns) on the existing point-in-time
buckets, and three additions to the trend family. All added in v1.5.

**History inputs** (`features/history.py`). `fund_history` additionally
carries each bucket filing's `gp`, `ebit`, `assets` and book value per
share `bvps = equity / (sharesbas × sharefactor)`, with the
adjacent-quarter `prev_netinc`, `prev_bvps`, `prev_shares`. A new
`annual_history` view resolves fiscal-year offsets 0…10 (eleven
observations span ten years of growth) with the same bucket rule as
`div_history`. Every bucket is the latest version of that period with
`datekey < snapshot_date`, so the point-in-time guarantee is inherited,
and nothing reads a price except today's `marketcap`.

**`fundhist` columns** (definitions: docs/features.md):

1. *Own-norm profitability* — for ROA, ROE, gross margin and operating
   margin, recomputed per bucket: `{m}_5y_median`, `{m}_5y_std`,
   `{m}_5y_z` (`(current − mean) / std`). The z-score is the "temporary
   drop?" question in the stock's own units; the median is the level a
   mean-reversion bet reverts to; the dispersion says how much a given
   gap means.
2. *Normalized earnings power* — `earnings_yield_5y_avg`,
   `ocf_yield_5y_avg`, `fcf_yield_5y_avg` (mean TTM flow over the window ÷
   today's marketcap), `earnings_yield_5y_peak`,
   `earnings_yield_at_5y_median_margin` (median net margin × today's
   revenue ÷ marketcap), `earnings_yield_10y_avg` (ten fiscal years — the
   Graham/Shiller form). Nominal: no inflation adjustment (a deviation
   from CAPE, as with the Ohlson size term in decision 0020).
3. *Distance from the own peak* — `{revenue,netinc,bvps}_vs_5y_peak` and
   `{…}_quarters_since_5y_peak` (ties resolve to the most recent quarter;
   0 = at the peak now).
4. *Earnings surprise* — `netinc_sue_8q`, `revenue_sue_8q`: the latest
   adjacent-quarter change in the TTM figure over the standard deviation
   of the eight changes before it. `TTM_q − TTM_{q−1}` equals the quarter
   minus the same quarter a year earlier, so this is the
   seasonal-random-walk SUE (the post-earnings-announcement-drift
   variable) with no ARQ flow read. The current change is excluded from
   the denominator so a large surprise is not capped.
5. *Ten-year record* — `ni_positive_years_10y`, `ni_history_years_10y`,
   `{revenue,bvps,shares}_cagr_10y`.

**Trend-family additions** (decision 0015 machinery): series `bvps`
(trend, consistency, up-fraction × 4 windows), series `shares` (trend and
up-fraction only), and `ni_positive_frac_{w}q` beside
`ocf_positive_frac_{w}q`.

**Min counts.** 20q statistics need ≥ 11 observations (decision 0015's
20q rule); the ten-year averages ≥ 6 known fiscal years; a 10-year CAGR
needs the observation at year offset 10; SUE needs ≥ 6 of the 8 prior
changes and the latest one. Unmet ⇒ NULL.

**Rank policy** (decision 0016). Counts (`*_quarters_since_5y_peak`,
`ni_*_years_10y`) and shares (`*_up_frac_*`, `ni_positive_frac_*`) are
unranked. Pinned: `{…}_vs_5y_peak` at raw 0 → rank 1 (at its own peak,
like `dist_52w_high`); `shares_trend_{w}q` at 0 → 0.5 (unchanged share
count); `gross_margin_5y_median` at 1 → 1 and `gross_margin_5y_std` at
0 → 0 (the no-cost-of-revenue mass of `gross_margin`). Everything else is
a full percent rank. `shares` ships no consistency column: a constant
share count makes r² a mass at exactly 1.

*Amended 2026-11-26, first real-data audit run (build 1.5.1):* two columns
were flagged and re-declared. `revenue_vs_5y_peak` is **unranked**: besides
the mass at 0 it has a second one at exactly −1 (revenue gone to zero,
3.2% of `high` 2026-Q2), and two masses cannot be pinned (decision 0016,
as `ni_change_scaled`); the raw value already lives on a fixed [−1, 0]
scale. `revenue_sue_8q` is **pinned at 0 → 0.5**: TTM revenue unchanged
quarter on quarter (2.5% of `high` 2025-Q3), a signed support.
`netinc_vs_5y_peak` and `bvps_vs_5y_peak` passed and keep their pin.

## Consequences

- 55 new feature columns (31 `fundhist`, 24 trend) plus their ranks.
  None of them is a new *source* of information — they are SF1 history
  the model could not previously see in one row.
- **The rank policies above are judged, not measured.** No real data was
  available when this was written; the first real v1.5 build's
  quarter-key audit is the test. A flagged column gets its policy
  declared in the registry (pin or unrank), as decision 0016 prescribes.
  Candidates to watch: `*_5y_std` for firms with frozen filings,
  `shares_cagr_10y` at exactly 0, `netinc_sue_8q` for young series.
- Coverage is thinner than the level features by construction: the 5y
  columns need about three years of quarterly filings, the 10y columns
  six to ten years. Annual-only filers have five quarterly buckets in a
  20q window and get no 5y statistics. The NULLs are the signal (decision
  0015); do not impute.
- `bvps` uses `sharesbas × sharefactor` across time, like
  `share_count_growth_1y`. The open QA item on the split basis of
  `sharesbas` (TODO) applies to `bvps_*` and `shares_*` as well.
- **Assembly cost is the open risk.** The rank pass sorts once per rank
  column, and this decision adds about 60 of them. On a 612k-snapshot
  synthetic world in an 18 GB-disk sandbox the v1.4 assembly completed
  (10m45s, 8 GB memory limit) and the v1.5 assembly ran out of temp space
  at 16 GiB. Not a correctness issue, but the real build needs checking
  and may need the rank pass batched (TODO).
- Build cost at a third of real scale: `fundhist` 11 s (relvalue 12 s,
  trend 36 s).
- Tests: `tests/test_features_fundhist.py` (hand-checked dip stock, the
  11-observation boundary, an annual filer with a full ten-year record),
  `tests/test_features_trend.py` for the new series.
