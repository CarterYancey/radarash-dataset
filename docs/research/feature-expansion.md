# Feature and label expansion for v1.5 (research workspace)

Date: 2026-11-26. Context: downstream models still do not substantially
outperform SPY. Two candidates were proposed (deeper fundamentals history;
max return and drawdown over the horizon) with a request to look for
others. This is the ledger of what was considered, what shipped, and what
did not and why. Shipped items graduated to ADRs 0022–0024 and the
canonical docs; nothing below is design canon.

No real data was available for this work (`data/` empty). Everything was
built and tested on synthetic fixtures; the items under "Before trusting
it" need a real build.

## 1. Where the two candidates stood

- **Max return and drawdown.** The drawdown half already existed
  (`fwd_{H}_max_drawdown`, `…_from_entry`, ADR 0017). The upside half did
  not: `fwd_{H}_max_cagr` is only the best close of the last 21 days.
- **Fundamentals history.** Partly there: revenue / tangible book / OCF
  trends over 4–20 quarters (ADR 0015), a 10-year dividend record, and
  the price multiples against their own 5 years (ADR 0018). Not there:
  anything about whether today's *profitability* is normal, average
  earnings, distance from the own peak, book value per share, the share
  count over time, loss history, or any 10-year figure except dividends.

On the March 2017 → March 2020 example: `fwd_{H}_excess_cagr` and
`label_{H}_beat_spy` already neutralize a market-wide dip at the endpoint,
because SPY is measured over the same window. The absolute rungs
(`label_{H}_cagr_ge_*`) do not. So part of the fix is a choice of target
downstream; the new path labels cover the rest.

## 2. Shipped

| # | What | Columns | ADR |
|---|---|---|---|
| 1 | Max run-up vs. entry | `fwd_{H}_max_runup` | 0022 |
| 2 | When the high and low came | `fwd_{H}_days_to_max`, `_days_to_min` | 0022 |
| 3 | Endpoint-free outcome | `fwd_{H}_path_avg_return` | 0022 |
| 4 | Forward risk | `fwd_{H}_realized_vol` | 0022 |
| 5 | The market's own path, same window | `fwd_{H}_spy_max_runup`, `_spy_max_drawdown`, `_spy_max_drawdown_from_entry`, `_spy_path_avg_return` | 0022 |
| 6 | Is today's profitability normal for this stock | `{roa,roe,gross_margin,operating_margin}_5y_{median,std,z}` | 0023 |
| 7 | Normalized earnings power | `earnings_yield_{5y_avg,10y_avg,5y_peak,at_5y_median_margin}`, `{ocf,fcf}_yield_5y_avg` | 0023 |
| 8 | Distance from the own peak, and how recent | `{revenue,netinc,bvps}_vs_5y_peak`, `…_quarters_since_5y_peak` | 0023 |
| 9 | Earnings / revenue surprise (seasonal SUE) | `netinc_sue_8q`, `revenue_sue_8q` | 0023 |
| 10 | Ten-year record | `ni_positive_years_10y`, `ni_history_years_10y`, `{revenue,bvps,shares}_cagr_10y` | 0023 |
| 11 | Book value per share and share-count trends, loss history | `bvps_{trend,consistency,up_frac}_{w}q`, `shares_{trend,up_frac}_{w}q`, `ni_positive_frac_{w}q` | 0023 |
| 12 | 8-K events, trailing year | `events_*_12m` (14 columns) | 0024 |

36 label columns, 69 feature columns (55 from SF1 history, 14 from
EVENTS), plus ranks where the policy allows.

Why these and not more ratios: §2.6 of `dataset-improvements.md` still
holds — the constraint is independent information per era, not column
count. Items 6–11 expose SF1 history the model could not see in a single
row; item 9 is a different *kind* of signal (earnings momentum, where the
rest of the set is value and quality); item 12 is a different *source*.

## 3. Considered, not shipped

| Idea | Why not (now) |
|---|---|
| Triple-barrier labels (first touch of +x / −y) | Still the principled path label (PLAN §6). `days_to_max` / `days_to_min` with the two extremes answer the common cases ("did it reach +50% before its low"); a true first-touch needs a within-segment scan at the crossing. Next label work if the path labels earn their keep. |
| Fraction of days above entry ("time under water") | Not decomposable over the quarter segments (the threshold is each snapshot's own entry price), so it needs a snapshot × day scan. `path_avg_return` carries most of it. |
| Trough-to-peak max run-up (mirror of `max_drawdown`) | Answers "best possible trade inside the window", not "what did this entry offer". `max_runup` vs. entry is the row's own upside. |
| Era-ranked outcome labels | Derivable downstream today (`dataset-improvements.md` §1.2); now also on `path_avg_return`. |
| Stored binaries or ratios on the new labels | Same rule as ADR 0017: continuous stored, thresholds downstream. |
| Insider (SF2) and institutional (SF3) data | Not ingested; needs the tables in `ingest/tables.py` and a subscription that includes them. Insider buying in a beaten-down stock is the best-documented value-trap discriminator after the 8-K events. **The strongest remaining source.** |
| S&P 500 membership at the snapshot | Open TODO item; the SP500 table is not ingested. |
| Market-regime features (valuation spread, market P/E) | Unchanged: near date-identifiers under temporal splits; only with the registered ablation (PLAN §5.6). |
| Acceleration (`trend_4q − trend_20q`) | A linear combination of stored columns; add only if a tree model demonstrably fails to find it. |
| Inflation-adjusted 10-year earnings (true CAPE) | Needs a CPI series, a new external input. Nominal 10y average shipped; the rank absorbs most of the drift. |
| Sector-relative own-history (z vs. sector z) | `_secrank` on the new z-scores would be the cheap form; wait for evidence the plain z helps. |
| Idiosyncratic volatility, return skew, trailing drawdown | Cheap technicals; low priority for a fundamentals-led thesis. |
| Longer or decayed event windows, days since last event | After the one-year counts are verified on real data. |
| Quarterly (ARQ) flow features | The seasonal difference of a quarterly flow is the adjacent-quarter change in the TTM figure, which the buckets already hold — that is how SUE was built without reading ARQ flows. Single-quarter margins would need them. |

## 4. Before trusting it (needs a real build)

1. **Rank audit.** The rank policies of the new features were chosen by
   reasoning about where mass points sit. The v1.5 quarter-key audit is
   the test; a flagged column needs its policy declared (ADR 0023).
2. **EVENTS coverage** (TODO V8): code vocabulary and per-year non-zero
   rates, especially before 2004 and for delisted companies (ADR 0024).
3. **Null rates** of the 5y / 10y columns by year and sector
   (`sharadar-qa coverage` reads the registry, so it covers them).
4. **Build time** on the real ingest (synthetic third-scale numbers are in
   the ADRs).
5. **Assembly temp space.** The v1.5 rank pass did not fit in a small
   sandbox where v1.4 did (TODO, ADR 0023). The rank audit therefore has
   only run on the small test fixtures.
6. **Run-up tail.** `fwd_{H}_max_runup` on sub-5-cent paths (the Foamex
   class) will show 100x+ values that are recorded, not investable.

## 5. Suggested downstream experiments

Columns alone may not move the result; these are the uses that could.

1. **Change the target, not the features.** Train the same model on
   `path_avg_return − spy_path_avg_return > 0` and compare walk-forward
   precision@K with `label_{H}_beat_spy`. If the endpoint was costing
   signal, this is where it shows.
2. **Asymmetry target.** `max_runup >= a AND max_drawdown_from_entry <= b`
   ("reached the upside without the ride"), per horizon, with base rates
   reported per fold.
3. **Risk-adjusted regression.** `cagr / realized_vol`, era-ranked.
4. **Ablation by family** on the registered leakage-gap setup: add
   `fundhist`, then `events`, then both, to the v1.4 feature set. Report
   per-family gain, not only the total — a family that adds nothing
   should be dropped from the model input, whatever the dataset ships.
5. **Era probe** on the new columns before any of the above, as for v1.2.
