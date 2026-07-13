"""Per-permaticker delisting facts: final trade, final price, reason.

The delisting-return convention (docs/decisions/0002) needs the last trading
date and the final adjusted close for every security; the labels also carry a
human-readable reason, mined from ACTIONS. Reasons compete by specificity —
`bankruptcyliquidation` beats a bare `delisted` when both are recorded — and
an ACTIONS row only counts if it falls inside the permaticker's price window
(plus a grace period, since delisting actions are often stamped a few days
after the last trade). That window check is what keeps a reused ticker's
later delisting from bleeding onto the earlier permaticker.

A delisted security with no matching ACTIONS row gets reason 'unknown'
rather than a null, so `delisted_in_window` stays unambiguous.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from identity.source import sql_quote

# Most-specific first; the first match wins when a ticker has several
# delisting-flavored actions. Vocabulary per Sharadar ACTIONS docs — V4 will
# validate coverage against real data.
DELIST_REASON_PRIORITY = (
    "bankruptcyliquidation",
    "regulatorydelisting",
    "voluntarydelisting",
    "acquisitionby",
    "mergerfrom",
    "delisted",
)

UNKNOWN_DELIST_REASON = "unknown"

# ACTIONS delist rows are frequently dated shortly after the final trade.
ACTION_GRACE_DAYS = 30


def build_delisting_view(
    con: duckdb.DuckDBPyConnection,
    actions_parquet: Path,
) -> None:
    """Create the `delistings` view: one row per in-universe permaticker."""
    actions = ", ".join(sql_quote(a) for a in DELIST_REASON_PRIORITY)
    priority = "CASE a.action " + " ".join(
        f"WHEN {sql_quote(action)} THEN {rank}"
        for rank, action in enumerate(DELIST_REASON_PRIORITY)
    ) + " END"
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW delistings AS
        WITH last_px AS (
            SELECT permaticker,
                   max(date) AS last_price_date,
                   max_by(closeadj, date) AS final_closeadj
            FROM sep_resolved
            GROUP BY permaticker
        ),
        reason_candidates AS (
            SELECT m.permaticker, a.action, a.date,
                   {priority} AS priority
            FROM read_parquet({sql_quote(str(actions_parquet))}) a
            JOIN price_mapping m
              ON a.ticker = m.ticker
             AND a.date >= coalesce(m.firstpricedate, DATE '0001-01-01')
             AND a.date <= coalesce(m.lastpricedate, DATE '9999-12-31')
                           + INTERVAL {ACTION_GRACE_DAYS} DAY
            WHERE a.action IN ({actions})
        ),
        best_reason AS (
            SELECT permaticker, action AS delist_reason
            FROM reason_candidates
            QUALIFY row_number() OVER (
                PARTITION BY permaticker ORDER BY priority, date
            ) = 1
        )
        SELECT u.permaticker,
               u.is_delisted,
               l.last_price_date,
               l.final_closeadj,
               CASE WHEN u.is_delisted
                    THEN coalesce(b.delist_reason,
                                  {sql_quote(UNKNOWN_DELIST_REASON)})
               END AS delist_reason
        FROM universe u
        LEFT JOIN last_px l USING (permaticker)
        LEFT JOIN best_reason b USING (permaticker)
        WHERE u.in_universe
        """
    )
