# 0004 — History depth: tiered lookbacks, capped at 3y, no split-rule change

Date: 2026-07-13
Status: accepted

## Context

Several feature families need a history of fundamentals (M-score: prior
fiscal year; trends: 2y; growth CAGRs: 3y+). Open questions: how deep, one
depth or several, how "consecutive filings" is defined on real (messy)
filing data, and whether trailing feature windows change the train/test
split rules. Research notes: `docs/research/features.md` §F4.

## Decision

1. **Depth tiers.** Every feature declares one requirement from a fixed
   menu: fundamentals **T0** (current filing), **T1** (+4 quarters), **T2**
   (+8), **T3** (+12); prices **P12** (252 trading days), **P36** (756).
   Fundamental depth is **capped at T3 (3 years) in v1** — the data floor
   is ~1998, and deeper lookbacks both burn sample years and
   systematically null young/newly-listed firms. Deeper tiers are additive
   registry changes for a future dataset version.
2. **Multiple depths coexist** as separate columns with separate null
   policies (e.g. `revenue_growth_1y` and `revenue_growth_3y`). The
   dataset stays label-agnostic: no per-horizon feature sets. Whether long
   -horizon labels are better predicted by long-history features is a
   downstream model-selection question the wide dataset enables.
3. **Lag matching is by `reportperiod` arithmetic, never positional.** The
   YoY partner of a filing is the same-permaticker row with `reportperiod`
   in `[−395d, −335d]` relative to the current one, taking the latest
   `datekey ≤ snapshot_date` (the version of history known at snapshot
   time). No partner ⇒ NULL. `calendardate` is not used for lag matching.
4. **Splits are unchanged.** Leakage flows forward through label windows;
   the purge/embargo condition (`snapshot_date + horizon + embargo <
   test_start`, PLAN §7.2) already covers it. A test row computing features
   over training-period data is deployment reality, not leakage; residual
   serial correlation across the boundary is what the (parameterized)
   embargo is for.
5. **Missing history ⇒ NULL, never row-drop.** Dropping short-history rows
   would tilt the universe toward seasoned survivors — survivorship bias
   through the back door.

## Consequences

- Burn-in: T1 features populate from ~1999, T3/P36 from ~2001. The earliest
  walk-forward fold must postdate the deepest tier it uses — asserted by
  the QA/coverage report (per-year, per-tier null rates), not by a split
  rule.
- Age-correlated missingness is accepted and *measured* (coverage report)
  rather than hidden by filtering.
- Amended filings, fiscal-year changes, and filing gaps degrade gracefully
  to NULL instead of silently mis-pairing quarters; the pairing rule is
  unit-testable with synthetic fiscal calendars.
- The staleness-cutoff question (TODO) stays open but narrows: features are
  computed against the freshest filing ≤ snapshot date, a
  `fundamentals_age_days` column is stored, and any cutoff is applied at
  assembly as a filter — so re-deciding it never recomputes features.
