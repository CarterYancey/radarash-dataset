# 0007 — Market inputs: self-built SEP × ARQ is canonical; DAILY is a cross-check (V7)

Date: 2026-07-14
Status: accepted

## Context

Valuation features need snapshot-date `marketcap` and `ev`. Sharadar DAILY
ships them precomputed, but PLAN's point-in-time invariant requires knowing
whether DAILY's *historical* rows are frozen as originally computed or
recomputed after restatements (verification task V7, features.md §F8.1).
`sharadar-qa daily-pit` ran three diagnostics on the full ingest
(features.md §F12, `docs/research/reports/daily_pit.md`).

## Decision

Findings:

- `lastupdated − date` declines linearly from ~7,600 days (1998) to ~0
  (2020+): DAILY was **wholesale re-stamped/rebuilt around 2019**, so
  "frozen as computed" cannot be certified for pre-2019 history.
- Our own construction — `marketcap = SEP.close × sharesbas × sharefactor`
  from the latest ARQ filing as of the date — replicates DAILY.marketcap
  (unit $1M) with ≤0.02% median error, ~98% of rows within 1%, every year.
- The sharp test: on 428k ticker-days where as-reported and restated equity
  differ, DAILY.pb sides with the **as-reported** value 85.9% of the time,
  *flat across all years* (84–89%). Recomputation from restated data would
  skew old years toward restated values; the flatness says the residual
  ~14% is definition/timing mismatch, not lookahead.

Decision:

1. **The canonical market inputs are self-built**: snapshot-date
   `marketcap = SEP.close × ARQ sharesbas × sharefactor` (latest
   `datekey < snapshot_date`), `ev = marketcap + debt − cashneq` from the
   same ARQ row. Point-in-time safe *by construction* and unit-testable.
2. **No feature reads DAILY.** DAILY stays ingested and serves as a QA
   cross-check (`sharadar-qa daily-pit` re-runs on refreshed data to catch
   regressions in either source).
3. SF1's own per-row `marketcap`/`ev`/`pe`/`pb`/`ps` (datekey-era prices)
   are likewise cross-check-only — they are not snapshot-date values.

## Consequences

- The PIT invariant for valuation features rests on our own as-of join
  (same machinery as the M2 verification path), not on a vendor's opaque
  rebuild history; the replication test doubles as its regression test.
- Marketcap is basic-shares-based; dilution is captured separately
  (`share_count_growth_1y`, diluted EPS features) rather than blended into
  the denominator.
- Accepted noise: shares are as of the last filing, so mid-quarter
  issuance/buybacks lag until the next filing — identical to DAILY's own
  behavior (that's why the two agree to <0.1%), and standard practice.
- V7 is closed by this writeup; `sharadar-qa daily-pit` remains runnable
  after every re-ingest.
