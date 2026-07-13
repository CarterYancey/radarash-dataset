# 0002 — Delisting return convention: final adjusted value, 0% to horizon

Date: 2026-07-13
Status: accepted

## Context

PLAN.md §6 required labels to be computed for every snapshot whose forward
window contains a delisting (dropping them reintroduces survivorship bias),
but left the terminal-value convention open: bankruptcy at −100% vs. final
price, and acquisitions compounding at the risk-free rate vs. 0%.

## Decision

One convention for **all** delistings, regardless of reason:

> The position is carried at the security's **final adjusted close**
> (`closeadj` on its last SEP trading day), compounding at **0%** from the
> delisting to the horizon end.

Mechanically (in `labels.paths`): the forward price on any trading day is the
most recent adjusted close on or before that day (ASOF join). Past the final
trade this forward-fills the final adjusted close, so terminal-window
average, min, max, and point-to-point all equal the final value once the
window lies wholly after the delisting. The same fill covers ordinary
trading halts. No `−100%` override for bankruptcies: Sharadar's final traded
price already reflects the market's recovery estimate, and V4 will audit
that assumption against known cases.

`delisted_in_window` is a single VARCHAR column per horizon:

- `'false'` — the security still traded at the horizon end;
- otherwise the **delist reason itself** (from ACTIONS, most specific action
  wins: `bankruptcyliquidation` > `regulatorydelisting` >
  `voluntarydelisting` > `acquisitionby` > `mergerfrom` > `delisted`;
  `'unknown'` when delisted with no matching ACTIONS row);
- `NULL` — the horizon is not yet observable, no label was computed.

There is no separate `delist_reason` label column.

## Consequences

- Labels are defined for every snapshot with an elapsed window — no
  delisted-row drops anywhere in the label pipeline.
- Acquisitions are slightly pessimistic (cash-out proceeds earn nothing to
  the horizon); bankruptcies are as pessimistic as their final print.
- Horizons whose nominal end date falls after the last calendar date are
  **not** computed even for delisted stocks: the stock's path is frozen but
  the benchmark's is not, and delisted companies can relist. The label stays
  NULL until the calendar catches up.
- Downstream filtering by delist reason uses `delisted_in_window_{H}`
  directly (`<> 'false'`), no join needed.
