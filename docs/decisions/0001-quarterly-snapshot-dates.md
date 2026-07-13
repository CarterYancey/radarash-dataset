# 0001 — Quarterly snapshots on intra-quarter low / median / high dates

Date: 2026-07-13
Status: accepted

## Context

README §4 proposed quarter-end snapshots plus an optional training-only
augmentation using intra-quarter low/high entry prices, to teach the
margin-of-safety gradient directly. Two open questions hung off that design:
whether to adopt the augmentation in v1, and what the canonical entry price
should be.

## Decision

Each (permaticker, calendar quarter) emits exactly **three snapshots**, taken
on the **dates** the stock's adjusted close (`SEP.closeadj`) touched its
intra-quarter **low**, **median**, and **high** — real trading days with real
entry prices, not synthetic quarter-end rows with substituted prices.

- The median is the **discrete 0.5-quantile** (`quantile_disc`) of the
  quarter's daily adjusted closes, so it is always a price that actually
  traded.
- When several dates touched the defining price (common for the median,
  guaranteed for constant prices), the **earliest date in the quarter** wins.
  The same tie rule applies to low and high.
- `snapshot_kind ∈ {low, median, high}` tags each row.
- Ranking uses `closeadj` (not raw close) so a mid-quarter split or dividend
  cannot distort which date was cheap.

## Consequences

- Every snapshot has a genuine (date, price) pair, so point-in-time feature
  joins (M2/M4) work identically for all three kinds — no special casing.
- The three kinds share a quarter's fundamentals but enter at different
  valuations, teaching the margin-of-safety gradient (README §4's goal).
- Snapshot dates are price-derived and therefore not information-free: the
  "low" date is only knowable at quarter end. This is fine for labels
  (forward-looking) and for features (computed as-of the snapshot date), but
  the low/high rows remain **training-only**; restricting evaluation to one
  entry per quarter is enforced by the splits module (M5), not here.
- `delisted`/constant-price corner cases collapse all three kinds onto the
  same date; rows stay distinct via `snapshot_kind`.
