# Staleness × labels report (features.md §F4.4)

Generated 2026-07-15 by `sharadar-qa staleness` over median-kind snapshots; label stats use the 1y horizon and skip unobservable windows. Per-year bucket shares: `staleness_by_year.csv`.

| staleness_bucket | snapshots | share | labeled_1y | mean_fwd_1y_cagr | median_fwd_1y_cagr | frac_1y_ge_0 | frac_1y_beat_spy | frac_delisted_1y |
|---|---|---|---|---|---|---|---|---|
| no filing | 15258 | 0.0296 | 15228 | 0.1076 | -0.1122 | 0.4083 | 0.3104 | 0.0571 |
| 0-93d | 444923 | 0.8627 | 427817 | 0.1177 | 0.0135 | 0.5233 | 0.4193 | 0.0787 |
| 94-183d | 45358 | 0.0879 | 44028 | 0.1367 | 0.0081 | 0.5134 | 0.4205 | 0.0893 |
| 184-365d | 3439 | 0.0067 | 3400 | 0.2372 | -0.1037 | 0.4279 | 0.3276 | 0.2482 |
| >365d | 6753 | 0.0131 | 6729 | 2.3039 | -0.0701 | 0.4602 | 0.331 | 0.2941 |

A monotone delist-rate / return gradient across buckets means staleness is signal (keep rows; cutoff only as an assembly filter). The 184-365d and >365d shares price a 183d vs. 365d cutoff.
