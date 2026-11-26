# 0024 — Corporate-events features: trailing 8-K item counts

Date: 2026-11-26
Status: accepted — real-data coverage check pending (TODO V8)

## Context

Every feature so far is derived from SF1 or from prices. The EVENTS
table has been ingested since M1 and used for nothing. It lists, per
(ticker, date), the item codes of the 8-K filed that day. Those are the
things a company must announce between its accounts — a restatement, an
auditor change, a delisting notice, an impairment, a private placement —
and they are the standard markers of the value trap: the cheap stock that
is cheap for a reason not yet in the fundamentals. With downstream models
failing to beat SPY on features that all re-cut the same two tables, a
third source is worth more than further ratios (the point of
`research/dataset-improvements.md` §2.6).

## Decision

1. **A family `events`**: 14 count columns, `events_{name}_12m`, each the
   number of distinct event dates carrying a code in
   `snapshot_date − 365 ≤ date < snapshot_date`; `events_8k_days_12m`
   counts every event date. Codes are 8-K items (item X.0Y → code XY):
   2.02 earnings release, 1.03 bankruptcy, 2.01 acquisition/disposition,
   2.03 new obligation, 2.04 obligation trigger, 2.05 exit costs, 2.06
   impairment, 3.01 delisting notice, 3.02 unregistered equity sales,
   4.01 auditor change, 4.02 non-reliance (restatement), 5.01 change in
   control, 5.02 officer/director change.
2. **Point-in-time**: the event date is the filing date; an event is
   usable strictly after it (`date < snapshot_date`), the same rule as
   `datekey`. The inference dataset uses `<=` (decision 0014).
3. **Entity resolution**: ticker → permaticker by the SF1 rule
   (unambiguous tickers unconditionally; reused tickers by price-coverage
   window with the same grace margins).
4. **Missing vs. none**: NULL when the 365-day window starts before the
   first date in the EVENTS export; otherwise a count, 0 when the stock
   has no matching row. A company that files no 8-Ks (a 20-F filer) is 0
   throughout, including `events_8k_days_12m`, which is the context
   column for the zeros.
5. **Counts, not ranked** (decision 0016), tier `E12` (365 days of EVENTS
   coverage).
6. **`eventcodes` parsing**: every run of digits is one code, whatever
   the delimiter.
7. **EVENTS is a required input** of `sharadar-features` only when the
   `events` family is built (the default builds it), and always of
   `sharadar-inference`.

## Consequences

- **Not verified on real data.** No raw export was available when this
  was written. Before these columns are trusted (TODO V8): confirm the
  code vocabulary against Sharadar's `eventcodes` legend, and tabulate
  each column's non-zero rate by year. Two specific risks: (a) the 8-K
  item scheme began 2004-08-23 — if earlier filings are absent or coded
  differently the columns are structurally 0 before 2004 and the NULL
  rule here does not catch it (the export would still have early dates);
  (b) coverage of delisted companies may be thinner than of survivors,
  which would be a survivorship echo. If either shows, add a per-code
  coverage floor (NULL before the code's first appearance) rather than
  dropping the family.
- Era identifiability: an unranked count that is mostly 0 is not a
  quarter key, but a column whose base rate drifts with filing rules is a
  mild era marker. The downstream era probe is the check.
- Window choice: one trailing year, no decay. A 3-year window or a
  days-since-last-event form are natural extensions once the one-year
  counts show value.
- Tests: `tests/test_features_cli.py` (window edges including the
  same-day exclusion and the inclusive first day, coverage NULL vs. 0,
  delimiter handling, missing-input exit code),
  `tests/test_inference_cli.py` (same-day event used at inference).
