# Splits diagnostics (PLAN §7.7, decision 0010)

Generated 2026-07-18 by `sharadar-qa splits-diag`. Full tables land as CSVs next to this report; interpretation guide in docs/research/splits.md.

## Q1/Q2 — which features move within a quarter

Top features by the fraction of (stock, quarter) groups whose three snapshot kinds disagree. Price-touching features should lead; fundamental-only features should differ only in filing-straddle quarters (full list: `feature_intraquarter.csv`).

| family | feature | groups | frac_groups_differ | median_rel_range |
|---|---|---|---|---|
| technical | ret_1m | 501567 | 0.9969 | 3.7635 |
| technical | ret_6m | 479011 | 0.9969 | 1.4814 |
| technical | vol_12m | 463557 | 0.9969 | 0.0521 |
| technical | amihud_12m | 508339 | 0.9968 | 0.1038 |
| technical | vol_36m | 386968 | 0.9967 | 0.0178 |
| technical | mom_12_2 | 453016 | 0.9951 | 0.7068 |
| valuation | ebitda_to_ev | 449775 | 0.9944 | 0.2795 |
| valuation | ebit_to_ev | 453687 | 0.994 | 0.3023 |
| solvency | altman_z | 410079 | 0.9938 | 0.163 |
| valuation | earnings_yield | 462208 | 0.9937 | 0.3742 |
| valuation | fcf_yield | 459045 | 0.9934 | 0.4327 |
| valuation | ocf_yield | 459077 | 0.9934 | 0.3666 |
| meta | fundamentals_age_days | 500559 | 0.9922 | 1 |
| solvency | marketcap_to_liabilities | 499143 | 0.9922 | 0.3248 |
| technical | log_marketcap | 499645 | 0.9922 | 0.0157 |
| valuation | book_to_market | 499476 | 0.9922 | 0.3186 |
| valuation | ncav_to_marketcap | 460849 | 0.9922 | 0.3687 |
| valuation | tangible_book_to_market | 499451 | 0.9922 | 0.3141 |
| valuation | ev_to_marketcap | 499484 | 0.991 | 0.0677 |
| technical | dist_52w_high | 515731 | 0.9821 | 0.9565 |
| technical | dollar_volume_3m | 515731 | 0.9612 | 0.2352 |
| valuation | sales_yield | 462314 | 0.9491 | 0.3029 |
| valuation | net_payout_yield | 458404 | 0.9046 | 0.4018 |
| quality | revenue_growth_variability_3y | 317599 | 0.75 | 0.2763 |
| quality | roa_variability_3y | 333327 | 0.7491 | 0.1802 |
| growth | revenue_growth_3y | 324094 | 0.745 | 0.174 |
| quality | noa_to_assets | 454606 | 0.7428 | 0.0714 |
| growth | asset_growth_1y | 454638 | 0.7427 | 0.4267 |
| profitability | roe | 425068 | 0.7419 | 0.1763 |
| quality | sgai | 384125 | 0.7419 | 0.045 |

| stock_quarters | straddled_quarters | frac_straddled |
|---|---|---|
| 515731 | 373378 | 0.724 |

## Q2 — label structure across kinds, stocks, and quarters

Flip rate: among (stock, quarter) groups where both the low and high kinds have observable labels, how often the binary label disagrees — the margin-of-safety gradient made visible.

| horizon | label | groups | frac_flip |
|---|---|---|---|
| 1y | beat_spy | 496839 | 0.2609 |
| 1y | cagr_ge_0 | 496839 | 0.2888 |
| 1y | cagr_ge_10 | 496839 | 0.2893 |
| 1y | cagr_ge_5 | 496839 | 0.2923 |
| 1y | cagr_ge_8 | 496839 | 0.2906 |
| 2y | beat_spy | 481516 | 0.186 |
| 2y | cagr_ge_0 | 481516 | 0.2042 |
| 2y | cagr_ge_10 | 481516 | 0.2105 |
| 2y | cagr_ge_5 | 481516 | 0.2096 |
| 2y | cagr_ge_8 | 481516 | 0.211 |
| 3y | beat_spy | 465205 | 0.1542 |
| 3y | cagr_ge_0 | 465205 | 0.1731 |
| 3y | cagr_ge_10 | 465205 | 0.1815 |
| 3y | cagr_ge_5 | 465205 | 0.1802 |
| 3y | cagr_ge_8 | 465205 | 0.1822 |
| 5y | beat_spy | 429020 | 0.124 |
| 5y | cagr_ge_0 | 429020 | 0.1426 |
| 5y | cagr_ge_10 | 429020 | 0.1453 |
| 5y | cagr_ge_5 | 429020 | 0.1533 |
| 5y | cagr_ge_8 | 429020 | 0.1512 |

Variance decomposition (exact ANOVA shares): `within_stock_quarter_share` is the entry-price gradient's share of all-kinds label variance; `quarter_fe_share` is the calendar-quarter fixed effect on median rows — the §7.1 cross-sectional overlap. Serial correlation is same-stock, median-kind, by quarter lag — the §7.1 serial overlap.

| horizon | rows_all_kinds | var_all_kinds | within_stock_quarter_share | rows_median | var_median | quarter_fe_share |
|---|---|---|---|---|---|---|
| 1y | 1492268 | 280.3341 | 0.0509 | 497202 | 260.9825 | 0.0028 |
| 2y | 1446555 | 0.248 | 0.1052 | 481870 | 0.2216 | 0.0855 |
| 3y | 1397341 | 0.128 | 0.0558 | 465489 | 0.1211 | 0.0721 |
| 5y | 1289323 | 0.0745 | 0.0295 | 429489 | 0.0724 | 0.046 |

| horizon | lag_quarters | pairs | label_corr |
|---|---|---|---|
| 1y | 1 | 484170 | 0.525 |
| 1y | 2 | 471194 | 0.0149 |
| 1y | 3 | 458306 | 0.0044 |
| 1y | 4 | 445544 | -0.0016 |
| 2y | 1 | 469037 | 0.8672 |
| 2y | 2 | 456243 | 0.721 |
| 2y | 3 | 443519 | 0.5783 |
| 2y | 4 | 430911 | 0.4413 |
| 3y | 1 | 452798 | 0.9304 |
| 3y | 2 | 440131 | 0.847 |
| 3y | 3 | 427534 | 0.7638 |
| 3y | 4 | 415042 | 0.6813 |
| 5y | 1 | 417440 | 0.963 |
| 5y | 2 | 405532 | 0.9148 |
| 5y | 3 | 393892 | 0.8656 |
| 5y | 4 | 382594 | 0.8173 |

## Q3 — twin test (row uniqueness)

Nearest neighbor of each sampled median row in quarter-ranked feature space (axes: earnings_yield, book_to_market, sales_yield, gp_to_assets, asset_turnover, liabilities_to_assets, cash_to_assets, accruals_to_assets, ret_6m, vol_12m, dist_52w_high, log_marketcap). If near-twins are disproportionately same-stock neighbor quarters or same-date peers, and their labels are far more correlated than random pairs', approximate memorization has something to recall (pairs detail: `twin_pairs.parquet`).

| nn_relation | pairs | share | mean_dist2 |
|---|---|---|---|
| same_stock_within_1y | 545 | 0.545 | 0.025 |
| unrelated | 398 | 0.398 | 0.0509 |
| same_stock_distant | 41 | 0.041 | 0.0428 |
| same_quarter_peer | 16 | 0.016 | 0.0318 |

| horizon | pairing | labeled_pairs | label_corr | mean_abs_diff |
|---|---|---|---|---|
| 1y | nearest | 939 | 0.4034 | 0.4599 |
| 1y | random | 924 | -0.0105 | 0.6803 |
| 2y | nearest | 888 | 0.7281 | 0.2283 |
| 2y | random | 852 | 0.0142 | 0.4462 |
| 3y | nearest | 841 | 0.5941 | 0.1723 |
| 3y | random | 794 | -0.0051 | 0.3701 |
| 5y | nearest | 758 | 0.5919 | 0.1272 |
| 5y | random | 677 | 0.0131 | 0.2858 |

## Purge cost (§7.2 priced per boundary)

Most recent three boundaries shown; all boundaries in `purge_cost.csv`. Unweighted row counts — uniqueness-weighted effective sample sizes follow once M5 defines `sample_weight`.

| test_start | horizon | train_pool_rows | eligible_rows | purged_rows | frac_pool_purged | test_rows_1y_window |
|---|---|---|---|---|---|---|
| 2024-01-01 | 1y | 1420545 | 1365225 | 55320 | 0.0389 | 15729 |
| 2024-01-01 | 2y | 1420545 | 1309938 | 110607 | 0.0779 | 15729 |
| 2024-01-01 | 3y | 1420545 | 1257437 | 163108 | 0.1148 | 15729 |
| 2024-01-01 | 5y | 1420545 | 1166848 | 253697 | 0.1786 | 15729 |
| 2025-01-01 | 1y | 1467732 | 1416709 | 51023 | 0.0348 | 15093 |
| 2025-01-01 | 2y | 1467732 | 1365225 | 102507 | 0.0698 | 15093 |
| 2025-01-01 | 3y | 1467732 | 1309938 | 157794 | 0.1075 | 15093 |
| 2025-01-01 | 5y | 1467732 | 1212247 | 255485 | 0.1741 | 15093 |
| 2026-01-01 | 1y | 1513011 | 1464037 | 48974 | 0.0324 | 11394 |
| 2026-01-01 | 2y | 1513011 | 1416709 | 96302 | 0.0636 | 11394 |
| 2026-01-01 | 3y | 1513011 | 1365225 | 147786 | 0.0977 | 11394 |
| 2026-01-01 | 5y | 1513011 | 1257437 | 255574 | 0.1689 | 11394 |
