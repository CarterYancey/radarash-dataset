"""Relative-value family (ADR 0018): valuation against the stock's own past.

Every valuation feature is a point-in-time level, and ranks compare against
the cross-section; this family asks "is the stock cheaper than *it* usually
is?". It prices each `fund_history` bucket (src/features/history.py) at its
own historical market cap, ADR 0007 convention:

    hist_marketcap = close(anchor) × shares   (that filing's sharesbas × sharefactor)
    anchor         = least(bucket_datekey, bucket_reportperiod + ANCHOR_DAYS)

`close(anchor)` is the unadjusted SEP close on the last trading day on or
before the anchor, NULL when that print is more than `PRICE_STALENESS_DAYS`
older than the anchor (pre-listing history, trading halts). The anchor
never passes the bucket filing's `datekey`, which is itself before the
snapshot (`<=` for inference), so every input is public at the snapshot.

Per ratio `r` in `RATIOS` (yield orientation — higher is cheaper) and the
20-quarter window (`qoff < 20`):

- `{r}_vs_5y_median` — current `r` ÷ median of the historical bucket values
  (> 1 ⇒ cheaper than its own norm); NULL when the median is ≤ 0.
- `{r}_5y_pctile` — midrank percentile of the current value within its own
  historical values: `(#below + ½·#equal) / n`, in [0, 1] (1 ⇒ cheaper than
  every past observation).

Both need at least `MIN_POINTS[20]` (ADR 0015's 20q rule) historical values
and a current value; missing stays NULL.
"""

from __future__ import annotations

import duckdb

from .history import HISTORY_QUARTERS
from .sqlutil import safe_div
from .trend import MIN_POINTS

# Historical price anchor: ~45 days after period end (the 10-Q deadline),
# capped at the filing's own datekey.
ANCHOR_DAYS = 45
# The close used for an anchor may be at most this many days old.
PRICE_STALENESS_DAYS = 14

# feature-name prefix -> (numerator in fund_history, numerator in fund_base);
# denominators are the historical / snapshot-date marketcap.
RATIOS: dict[str, tuple[str, str]] = {
    "sales_yield": ("revenue", "f_revenue"),
    "book_to_market": ("equity", "l_equity"),
}


def _relvalue_exprs(name: str) -> list[str]:
    hist = f"h.{name}"
    cur = f"c.{name}"
    n = f"count({hist})"
    enough = f"{n} >= {MIN_POINTS[HISTORY_QUARTERS]}"
    below = f"count(*) FILTER (WHERE {hist} < {cur})"
    equal = f"count(*) FILTER (WHERE {hist} = {cur})"
    return [
        f"CASE WHEN {enough} THEN {safe_div(cur, f'median({hist})')} END"
        f" AS {name}_vs_5y_median",
        f"CASE WHEN {enough} AND {cur} IS NOT NULL"
        f" THEN ({below} + 0.5 * {equal}) / {n} END"
        f" AS {name}_5y_pctile",
    ]


def build_relvalue_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_relvalue` view."""
    cur_cols = ",\n                   ".join(
        f"{safe_div(f'b.{base_col}', 'm.marketcap')} AS {name}"
        for name, (_, base_col) in RATIOS.items()
    )
    hist_mcap = "CASE WHEN a.shares > 0 THEN p.close * a.shares END"
    hist_cols = ",\n                   ".join(
        f"{safe_div(f'a.{hist_col}', hist_mcap)} AS {name}"
        for name, (hist_col, _) in RATIOS.items()
    )
    aggs = ",\n               ".join(
        expr for name in RATIOS for expr in _relvalue_exprs(name)
    )
    cur_names = ", ".join(f"c.{name}" for name in RATIOS)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW features_relvalue AS
        WITH c AS (
            SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
                   {cur_cols}
            FROM fund_base b
            JOIN market_inputs m
              USING (permaticker, snapshot_date, snapshot_kind)
        ),
        anchored AS (
            SELECT permaticker, snapshot_date, snapshot_kind, qoff,
                   revenue, equity, shares,
                   least(bucket_datekey,
                         bucket_reportperiod + {ANCHOR_DAYS}) AS anchor
            FROM fund_history
            WHERE qoff < {HISTORY_QUARTERS}
        ),
        h AS (
            SELECT a.permaticker, a.snapshot_date, a.snapshot_kind,
                   {hist_cols}
            FROM anchored a
            ASOF LEFT JOIN sep_ix p
              ON p.permaticker = a.permaticker AND a.anchor >= p.date
            WHERE p.date >= a.anchor - {PRICE_STALENESS_DAYS}
        )
        SELECT c.permaticker, c.snapshot_date, c.snapshot_kind,
               {aggs}
        FROM c
        LEFT JOIN h USING (permaticker, snapshot_date, snapshot_kind)
        GROUP BY c.permaticker, c.snapshot_date, c.snapshot_kind, {cur_names}
        """
    )
