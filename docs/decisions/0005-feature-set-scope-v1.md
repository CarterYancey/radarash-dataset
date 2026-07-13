# 0005 — v1 feature-set scope: wide fundamentals + small technical family

Date: 2026-07-13
Status: accepted

## Context

PLAN.md §5 sketched seven feature families. Open questions: how many
features to include, which additional published formulas beyond the initial
list, and whether technical (price-based) features belong in a
fundamentals-driven deep-value dataset. Research notes:
`docs/research/features.md` §F3, §F5, §F6.

## Decision

1. **Wide by default; the gate is auditability, not a count budget.**
   Storage is cheap and downstream feature selection is model work; the
   real cost of a column is QA surface. A feature is included iff it has
   literature or thesis support **and** a testable definition, and every
   feature enters through the registry (no drive-by columns). Landing
   point: ~95 raw features → ~190 columns with ranks.
2. **Additional fundamental features adopted for v1** (beyond PLAN §5):
   Ohlson O and Zmijewski components (+ Zmijewski composite); Mohanram
   G-score (7-signal variant); Sloan accruals (cash-flow method); net
   operating assets (Hirshleifer); asset growth (Cooper–Gulen–Schill);
   external financing (Bradshaw–Richardson–Sloan); net payout /
   shareholder yield; gross profitability (Novy-Marx); Graham deep-value
   markers (NCAV/marketcap, negative-EV flag); share-count dilution.
3. **Technical family confirmed, kept small**, all from `SEP.closeadj`
   (the label plumbing — no new point-in-time machinery): 12-2 momentum,
   6m return, 1m reversal, 12m and 36m volatility, distance from 52-week
   high, log market cap, 3m median dollar volume, Amihud illiquidity.
   Momentum/low-vol are required inputs of the Conservative formula anyway,
   and they let trees separate "cheap and stabilizing" from "cheap and
   collapsing" — invisible to fundamentals alone. Liquidity measures double
   as columns informing the microcap/liquidity-floor question without
   excluding rows.
4. **Representation rules.** Valuation stored in **yield orientation**
   (E/P, B/M, EBIT/EV — defined for negative numerators, monotone, rank
   -clean); multiples derivable downstream, not stored. Non-positive
   *fundamental* denominators ⇒ NULL, with the information kept once in
   flag features (`negative_equity`, `negative_ebitda`, `negative_ev`).
   Raw values stored untouched (no winsorization); ranks are the
   outlier-robust model-facing representation.
5. **Still out of scope for v1:** market-regime features (deferred behind
   the ablation-protocol gate, unchanged), mega-composites
   (O'Shaughnessy-style), anything requiring segment/estimates/ownership
   data or external macro series, betas or intraday-dependent measures.

## Consequences

- The registry (`docs/features.md` + `src/features/registry.py`) is the
  single choke point for scope changes; dataset versions are diffable from
  registry `added_in_version`/`removed_in_version` fields.
- Rank computation moves to assembly time (cross-sections don't exist
  inside per-family modules); rank scope under the scattered decision-0001
  snapshot dates needs its own ADR (research §F7 proposes ranking within
  calendar quarter × snapshot_kind).
- The technical family makes the three same-quarter snapshot kinds differ
  in features as well as entry price — the margin-of-safety gradient
  decision 0001 was built for, and a QA check-point.
- Accepted risks: some deep-value markers (NCAV) are null-heavy outside
  microcaps by nature; classification columns from TICKERS are
  current-state rather than historical (caveat documented; SIC-era mapping
  is the fallback if verification shows material drift).
