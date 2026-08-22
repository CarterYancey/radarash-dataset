# Canonical feature registry (M4)

**Status: canonical** (2026-07-14) — implements accepted ADRs
[0003](decisions/0003-composite-scores-in-house.md) (composites in-house),
[0004](decisions/0004-fundamental-history-depth.md) (history depth),
[0005](decisions/0005-feature-set-scope-v1.md) (v1 scope),
[0006](decisions/0006-staleness-policy.md) (staleness),
[0007](decisions/0007-market-inputs-daily-pit.md) (market inputs),
[0008](decisions/0008-rank-representation.md) (ranks),
[0015](decisions/0015-trend-consistency-features.md) (trend & consistency, v1.1).
`src/features/` implements this registry in the build order below.
Research trail: [research/features.md](research/features.md).

This file and `src/features/registry.py` must stay 1:1 — assembly validates
that emitted columns match the code registry exactly. Update both together;
`added_in_version` / `removed_in_version` on each spec makes dataset
versions diffable from the registry alone.

## Conventions (apply to every feature unless its row says otherwise)

- **Key:** `(permaticker, snapshot_date, snapshot_kind)` — same as
  `labels.parquet`. One row per snapshot. Fundamentals resolve strictly per
  `snapshot_date` (decision 0001: no special casing per kind): the three
  same-quarter kinds *usually* share a quarter's fundamentals, but a filing
  whose `datekey` lands between two kinds' snapshot dates puts those kinds on
  different filings — point-in-time-correct by design. Price-based features
  always differ across kinds.
- **Point-in-time:** fundamentals come from the freshest as-reported row
  with `datekey < snapshot_date` (usable strictly after the filing date,
  PLAN §2). Flow ("ttm") inputs are **ART**; point-in-time levels ("q") are
  **ARQ** from the same filing. `MR*` dimensions never. No staleness
  cutoff (ADR 0006).
- **YoY / lag inputs** (`x₋₁`, `x₋₂`, `x₋₃` = 1/2/3 fiscal years prior):
  matched by `reportperiod` window `365·k ± 30` days, latest
  `datekey < snapshot_date` version, per ADR 0004. No partner ⇒ NULL.
- **Market inputs** (ADR 0007): `marketcap = SEP.close ×
  sharesbas_q × sharefactor`; `ev = marketcap + debt_q − cashneq_q`; both
  as of `snapshot_date`. DAILY is never read.
- **Null rule:** yields divide by `marketcap` (positive by construction) or
  `ev` (NULL when `ev ≤ 0`, with `negative_ev` flag). Ratios over a
  fundamental denominator are NULL when the denominator is ≤ 0 or missing;
  the sign information lives once in the flag features. No winsorization,
  no imputation.
- **Ranks** (ADR 0008): every numeric feature also ships
  `{name}_rank` = `percent_rank` within (calendar quarter, snapshot_kind),
  NULL-safe, thin-slice guard 20. Rows marked **S** additionally ship
  `{name}_secrank` within (quarter, kind, sector). Flags (bool) and
  classification columns are not ranked.
- **Tiers** (ADR 0004): T0 current filing; T1/T2/T3 = +1/2/3 fiscal years;
  P12/P36 = 252/756 trading days of `SEP.closeadj`; T5/T10 = +20 quarters /
  +10 fiscal years (ADR 0015). Tier = what the feature *needs*; unmet ⇒
  NULL — except the windowed trend family, whose tier states the full
  window while partial histories degrade per its min-count rules.
- **Quarterly/annual history windows** (ADR 0015): the lag-q (lag-y)
  observation is the filing with `reportperiod` within ±30 days of
  `fund_reportperiod − q·91.3125` (`− y·365.25`), latest
  `datekey < snapshot_date` version — the quarterly/annual generalization
  of the YoY rule above. No partner ⇒ bucket missing.
- Structurally null segments (from the coverage report, research §F10):
  classified-balance-sheet inputs (`workingcapital`, `assetsc`,
  `liabilitiesc`) are ~84% NULL for Real Estate and ~55% for residual
  Financial Services — every feature marked ⌂ below inherits that.
  `retearn` is ~20%/14% NULL in Energy/Utilities (⌐).

## Meta

| column | tier | definition | notes |
|---|---|---|---|
| `fund_datekey` | T0 | `datekey` of the filing used | metadata, not ranked |
| `fund_reportperiod` | T0 | `reportperiod` of that filing | metadata, not ranked |
| `fundamentals_age_days` | T0 | `snapshot_date − datekey` | **feature**, ranked (ADR 0006) |
| `has_filing_183d` / `has_filing_365d` | T0 | age ≤ 183 / 365 | flags (ADR 0006) |
| `negative_equity` | T0 | `equity_q ≤ 0` | flag |
| `negative_ebitda` | T0 | `ebitda ≤ 0` | flag |
| `negative_ev` | T0 | `ev ≤ 0` | flag; on-thesis deep-value marker |

## Valuation (yield orientation, ADR 0005 §4)

| column | tier | definition | notes |
|---|---|---|---|
| `earnings_yield` | T0 | `netinc / marketcap` | S |
| `ocf_yield` | T0 | `ncfo / marketcap` | S |
| `fcf_yield` | T0 | `fcf / marketcap` | S |
| `sales_yield` | T0 | `revenue / marketcap` | S |
| `book_to_market` | T0 | `equity_q / marketcap` | S; negative book kept (yield orientation) |
| `tangible_book_to_market` | T0 | `tangibles_q / marketcap` | S |
| `ebit_to_ev` | T0 | `ebit / ev` | S; NULL if `ev ≤ 0`; Magic-formula earnings yield |
| `ebitda_to_ev` | T0 | `ebitda / ev` | S; NULL if `ev ≤ 0` |
| `dividend_yield` | T0 | `−ncfdiv / marketcap` | cash-flow-statement convention |
| `net_payout_yield` | T0 | `−(ncfdiv + ncfcommon) / marketcap` | Conservative-formula input |
| `ncav_to_marketcap` | T0 ⌂ | `(assetsc_q − liabilities_q) / marketcap` | Graham net-net discount |
| `ev_to_marketcap` | T0 | `ev / marketcap` | leverage-in-price; negative-EV magnitude |

## Profitability

| column | tier | definition | notes |
|---|---|---|---|
| `gp_to_assets` | T0 | `gp / assets_q` | S; Novy-Marx |
| `roa` | T0 | `netinc / assets_q` | F-score, O-score, Zmijewski input |
| `roe` | T0 | `netinc / equity_q` | NULL if `equity_q ≤ 0` |
| `ebit_to_invcap` | T0 | `ebit / invcap_q` | NULL if `invcap_q ≤ 0` |
| `roc_greenblatt` | T0 ⌂ | `ebit / (workingcapital_q + ppnenet_q)` | NULL if denom ≤ 0; Magic-formula ROC |
| `gross_margin` | T0 | `gp / revenue` | S |
| `operating_margin` | T0 | `ebit / revenue` | S |
| `net_margin` | T0 | `netinc / revenue` | S |
| `fcf_margin` | T0 | `fcf / revenue` | |
| `cfo_to_assets` | T0 | `ncfo / assets_q` | G-score CFROA |
| `asset_turnover` | T0 | `revenue / assets_q` | F-score & Z input |

All `x / revenue` NULL when `revenue ≤ 0`; denominators are current-quarter
levels, not `*avg` (one convention everywhere; noted deviation from
textbook ROA).

## Growth & trends

| column | tier | definition | notes |
|---|---|---|---|
| `revenue_growth_1y` | T1 | `revenue / revenue₋₁ − 1` | NULL if `revenue₋₁ ≤ 0`; Beneish SGI − 1 |
| `revenue_growth_3y` | T3 | `(revenue / revenue₋₃)^(1/3) − 1` | same null rule |
| `epsdil_growth_1y` | T1 | `epsdil / epsdil₋₁ − 1` | NULL if `epsdil₋₁ ≤ 0` |
| `roa_delta_1y` | T1 | `roa − roa₋₁` | F-score signal 3 |
| `gross_margin_delta_1y` | T1 | `gross_margin − gross_margin₋₁` | F-score signal 8 |
| `gross_margin_delta_2y` | T2 | `gross_margin − gross_margin₋₂` | trend depth |
| `asset_turnover_delta_1y` | T1 | `asset_turnover − asset_turnover₋₁` | F-score signal 9 |
| `asset_growth_1y` | T1 | `assets_q / assets_q₋₁ − 1` | Cooper–Gulen–Schill |
| `share_count_growth_1y` | T1 | `(sharesbas·sharefactor) YoY − 1` | dilution; F-score signal 7 proxy |

## Trend & consistency (ADR 0015; added in v1.1)

Long-history financial health over quarterly windows w ∈ {4, 8, 12, 20}
(~1/2/3/5y, matching the label horizons; tiers T1/T2/T3/T5 respectively).
Series: `revenue` (ART TTM), `tangibles_q` (ARQ), `ncfo` (ART TTM).
`trend`/`consistency` need ≥ {3, 5, 7, 11} observations, all > 0 (the log's
domain — no silent filtering); `up_frac` needs one fewer adjacent-quarter
pairs; `*_positive_frac` the same min counts. TTM at quarterly spacing
overlaps by construction (smoothed, seasonality-free — a TTM increase means
the latest quarter beat its year-ago quarter); `consistency` of a constant
series is 1 (consistent, zero trend). Dividend features sample the TTM cash
dividend `−ncfdiv` at fiscal-year anniversaries over 10 years; a cut is a
YoY drop below 0.8× (omission included). No T0 filing ⇒ all NULL; no known
dividend year ⇒ the dividend counters are NULL.

| column | tier | definition | notes |
|---|---|---|---|
| `revenue_trend_4q` | T1 | `regr_slope(ln(revenue), years)`, last 4 quarterly obs | annualized log growth |
| `revenue_consistency_4q` | T1 | `regr_r2` of the 4q revenue fit | 1 = textbook compounder |
| `revenue_up_frac_4q` | T1 | share of adjacent-quarter revenue increases, 4q | |
| `revenue_trend_8q` | T2 | same fit over 8 quarters | |
| `revenue_consistency_8q` | T2 | `regr_r2`, 8q | |
| `revenue_up_frac_8q` | T2 | share of increases, 8q | |
| `revenue_trend_12q` | T3 | same fit over 12 quarters | |
| `revenue_consistency_12q` | T3 | `regr_r2`, 12q | |
| `revenue_up_frac_12q` | T3 | share of increases, 12q | |
| `revenue_trend_20q` | T5 | same fit over 20 quarters | |
| `revenue_consistency_20q` | T5 | `regr_r2`, 20q | |
| `revenue_up_frac_20q` | T5 | share of increases, 20q | |
| `tangibles_trend_4q` | T1 | `regr_slope(ln(tangibles_q), years)`, last 4 quarterly obs | tangible book trend |
| `tangibles_consistency_4q` | T1 | `regr_r2` of the 4q tangibles fit | |
| `tangibles_up_frac_4q` | T1 | share of adjacent-quarter tangibles increases, 4q | |
| `tangibles_trend_8q` | T2 | same fit over 8 quarters | |
| `tangibles_consistency_8q` | T2 | `regr_r2`, 8q | |
| `tangibles_up_frac_8q` | T2 | share of increases, 8q | |
| `tangibles_trend_12q` | T3 | same fit over 12 quarters | |
| `tangibles_consistency_12q` | T3 | `regr_r2`, 12q | |
| `tangibles_up_frac_12q` | T3 | share of increases, 12q | |
| `tangibles_trend_20q` | T5 | same fit over 20 quarters | |
| `tangibles_consistency_20q` | T5 | `regr_r2`, 20q | |
| `tangibles_up_frac_20q` | T5 | share of increases, 20q | |
| `ocf_trend_4q` | T1 | `regr_slope(ln(ncfo), years)`, last 4 quarterly obs | NULL when OCF ≤ 0 in-window |
| `ocf_consistency_4q` | T1 | `regr_r2` of the 4q ncfo fit | |
| `ocf_up_frac_4q` | T1 | share of adjacent-quarter ncfo increases, 4q | |
| `ocf_trend_8q` | T2 | same fit over 8 quarters | |
| `ocf_consistency_8q` | T2 | `regr_r2`, 8q | |
| `ocf_up_frac_8q` | T2 | share of increases, 8q | |
| `ocf_trend_12q` | T3 | same fit over 12 quarters | |
| `ocf_consistency_12q` | T3 | `regr_r2`, 12q | |
| `ocf_up_frac_12q` | T3 | share of increases, 12q | |
| `ocf_trend_20q` | T5 | same fit over 20 quarters | |
| `ocf_consistency_20q` | T5 | `regr_r2`, 20q | |
| `ocf_up_frac_20q` | T5 | share of increases, 20q | |
| `ocf_positive_frac_4q` | T1 | share of last 4 quarterly obs with `ncfo > 0` | the OCF-sign signal where log trend is NULL |
| `ocf_positive_frac_8q` | T2 | same, 8q | |
| `ocf_positive_frac_12q` | T3 | same, 12q | |
| `ocf_positive_frac_20q` | T5 | same, 20q | |
| `fund_history_quarters` | T5 | quarterly filings present in the 20q window | short history *is* the signal |
| `div_years_paid_10y` | T10 | fiscal years with `−ncfdiv > 0`, last 10 | |
| `div_streak_10y` | T10 | consecutive paying years ending now, max 10 | missing/unknown year breaks it |
| `div_cuts_10y` | T10 | YoY TTM dividend drops below 0.8× prior, last 10y | omission counts as a cut |
| `div_history_years_10y` | T10 | annual dividend observations known, last 10 | denominator context |

## Solvency / distress

| column | tier | definition | notes |
|---|---|---|---|
| `wc_to_assets` | T0 ⌂ | `workingcapital_q / assets_q` | Z & O component |
| `retearn_to_assets` | T0 ⌐ | `retearn_q / assets_q` | Z component |
| `ebit_to_assets` | T0 | `ebit / assets_q` | Z component |
| `marketcap_to_liabilities` | T0 | `marketcap / liabilities_q` | Z (public) component |
| `equity_to_liabilities` | T0 | `equity_q / liabilities_q` | Z'/Z'' component |
| `liabilities_to_assets` | T0 | `liabilities_q / assets_q` | O & Zmijewski component |
| `cl_to_ca` | T0 ⌂ | `liabilitiesc_q / assetsc_q` | O component |
| `current_ratio` | T0 ⌂ | `assetsc_q / liabilitiesc_q` | F-score signal 6 base |
| `quick_ratio` | T0 ⌂ | `(assetsc_q − inventory_q) / liabilitiesc_q` | |
| `cash_to_assets` | T0 | `cashneq_q / assets_q` | |
| `debt_to_equity` | T0 | `debt_q / equity_q` | NULL if `equity_q ≤ 0` |
| `net_debt_to_ebitda` | T0 | `(debt_q − cashneq_q) / ebitda` | NULL if `ebitda ≤ 0` |
| `interest_coverage` | T0 | `ebit / intexp` | NULL if `intexp ≤ 0` (no debt ⇒ NULL, not ∞) |
| `ffo_to_liabilities` | T0 | `ncfo / liabilities_q` | O component (FFO proxied by CFO, §F1 gap) |
| `log_assets` | T0 | `ln(assets_q)` | O size term (nominal; rank fixes drift) |
| `ni_change_scaled` | T1 | `(netinc − netinc₋₁) / (|netinc| + |netinc₋₁|)` | O component |
| `two_year_loss` | T1 | `netinc < 0 AND netinc₋₁ < 0` | flag; O component |
| `liab_gt_assets` | T0 | `liabilities_q > assets_q` | flag; O component |
| `altman_z` | T0 ⌂⌐ | `1.2·wc/ta + 1.4·re/ta + 3.3·ebit/ta + 0.6·mve/tl + 1.0·s/ta` | composite; literature comparability |
| `altman_z_dd` | T0 ⌂⌐ | `6.56·wc/ta + 3.26·re/ta + 6.72·ebit/ta + 1.05·bve/tl` | Z'' — featured variant (mixed universe) |
| `zmijewski` | T0 ⌂ | `−4.336 − 4.513·roa + 5.679·tl/ta + 0.004·ca/cl` | composite |

Composites are NULL when any component is NULL (⌂⌐ inherited); the Ohlson
composite is deferred (ADR 0003) — its components are all above.

## Earnings quality (Beneish inputs are ART pairs, T1)

| column | tier | definition | notes |
|---|---|---|---|
| `dsri` | T1 | `(receivables_q/revenue) / (receivables_q₋₁/revenue₋₁)` | |
| `gmi` | T1 | `gross_margin₋₁ / gross_margin` | NULL if either margin ≤ 0 |
| `aqi` | T1 ⌂ | `(1 − (assetsc_q + ppnenet_q)/assets_q)` YoY ratio | |
| `sgi` | T1 | `revenue / revenue₋₁` | |
| `depi` | T1 | `(depamor/(depamor + ppnenet_q))₋₁ / (…)current` | |
| `sgai` | T1 | `(sgna/revenue) / (sgna₋₁/revenue₋₁)` | |
| `lvgi` | T1 ⌂ | `((debt_q + liabilitiesc_q)/assets_q)` YoY ratio | |
| `accruals_to_assets` | T0 | `(netinc − ncfo) / assets_q` | S; TATA & Sloan accruals (CF method), one column |
| `beneish_m` | T1 ⌂ | `−4.84 + 0.92·dsri + 0.528·gmi + 0.404·aqi + 0.892·sgi + 0.115·depi − 0.172·sgai + 4.679·tata − 0.327·lvgi` | composite |
| `piotroski_f` | T1 | count of the 9 signals (research §F2.2 table) | composite, 0–9; signals from components above + `ncfcommon ≤ 0` |
| `noa_to_assets` | T1 | `((assets_q − cashneq_q − investments_q) − (liabilities_q − debt_q)) / assets_q₋₁` | Hirshleifer NOA |
| `ext_financing_to_assets` | T0 | `(ncfcommon + ncfdebt) / assets_q` | Bradshaw–Richardson–Sloan |
| `rnd_to_assets` | T0 | `coalesce(rnd, 0) / assets_q` | G-score input; unreported R&D counts as 0 — the one explicit fill (ADR 0013) |
| `capex_to_assets` | T0 | `−capex / assets_q` | G-score input; cash-flow sign convention |
| `roa_variability_3y` | T3 | stddev of `{roa, roa₋₁, roa₋₂, roa₋₃}` | G-score input; NULL unless all four exist |
| `revenue_growth_variability_3y` | T3 | stddev of the 3 YoY revenue growths | G-score input; NULL unless all three exist |
| `mohanram_g7` | T3 | 7-signal variant vs. `famaindustry` medians (ADR 0013) | **assembly-stage** (needs cross-section); advertising signal unavailable |

## Technical (from `SEP.closeadj`; differs across snapshot kinds)

| column | tier | definition | notes |
|---|---|---|---|
| `mom_12_2` | P12 | total return t−252 → t−21 | S is not applied; plain rank only |
| `ret_6m` | P12 | total return t−126 → t | |
| `ret_1m` | P12 | total return t−21 → t | short-term reversal |
| `vol_12m` | P12 | ann. σ of daily log returns, ≥200 obs | |
| `vol_36m` | P36 | same over 756d, ≥600 obs | Conservative-formula input |
| `dist_52w_high` | P12 | `closeadj / max₍t−252…t₎ closeadj − 1` | |
| `log_marketcap` | T0 | `ln(marketcap)` | |
| `dollar_volume_3m` | P12 | median daily `close × volume`, t−63 → t | liquidity column (TODO microcap question) |
| `amihud_12m` | P12 | mean `|ret| / (close × volume)` | illiquidity |
| `conservative_score` | P36 | rank-sum of `vol_36m` (low), `mom_12_2` (high), `net_payout_yield` (high) | **assembly-stage** composite (needs ranks) |

## Classification (not ranked)

| column | source | notes |
|---|---|---|
| `sector` / `industry` | TICKERS | Sharadar scheme; **current-state**, not historical (documented caveat, research §F8.3) |
| `famaindustry` | TICKERS | FF-48-style; G-score peer grouping |
| `scalemarketcap` | TICKERS | size bucket, current-state |
| `siccode` | TICKERS | fallback for era-stable industry mapping |

Current-state means three accepted (v1) edges: a reclassified firm's whole
history gets today's label; delisted firms' labels **freeze at delisting**
while survivors' keep refreshing (a faint survivorship echo confined to
these columns); and at assembly the `_secrank` cross-sections group
historical rows by current-state sector — mild lookahead through
peer-group *identity* only, never through the ranked firm's own values.
`siccode` (assigned at registration, era-stable) is the stored fallback.
Revisit if material drift ever shows up — measurable as a cross-export
diff once two ingest vintages exist.

## Build order (`src/features/`, research §F8.2)

`base` (as-of + lag resolution), `history` (quarterly/annual buckets,
ADR 0015) and `market` (marketcap/EV) → `valuation` →
`profitability` + `growth` → `trend` → `solvency` → `quality` →
`technical` → `classification`; then assembly (M5, `src/assemble/`) computes
ranks/sector-ranks and the two assembly-stage columns (`mohanram_g7`,
`conservative_score`, ADR 0013) — output layout in dataset.md.
Market-regime features remain deferred behind their ablation gate
(PLAN §5.6). Each family writes `data/interim/features/{family}.parquet` on
the shared key; families never read each other's outputs.
