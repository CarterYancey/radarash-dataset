"""Snapshot-date market inputs: the `market_inputs` foundation view.

ADR 0007: the canonical market inputs are self-built —
`marketcap = SEP.close (unadjusted, snapshot date) * sharesbas * sharefactor`
from the T0 filing resolved by `fund_base`, and
`ev = marketcap + debt_q - cashneq_q` from the same filing. DAILY is never
read. Missing shares/debt/cash leave marketcap/ev NULL (no imputation);
marketcap is positive whenever present (close > 0 by the SEP filter,
shares <= 0 is treated as missing).
"""

from __future__ import annotations

import duckdb


def build_market_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `market_inputs` view from `fund_base` and `sep_ix`."""
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW market_inputs AS
        SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
               CASE WHEN b.l_sharesbas * b.l_sharefactor > 0
                    THEN p.close * b.l_sharesbas * b.l_sharefactor
               END AS marketcap,
               CASE WHEN b.l_sharesbas * b.l_sharefactor > 0
                    THEN p.close * b.l_sharesbas * b.l_sharefactor
                         + b.l_debt - b.l_cashneq
               END AS ev
        FROM fund_base b
        LEFT JOIN sep_ix p
          ON p.permaticker = b.permaticker AND p.date = b.snapshot_date
        """
    )
