"""Quarterly snapshot dates: intra-quarter low / median / high touches.

Each (permaticker, calendar quarter) emits three snapshots, taken on the
dates the stock's adjusted close touched its intra-quarter low, median, and
high (docs/decisions/0001). The median is the discrete 0.5-quantile
(`quantile_disc`), so it is always a price that actually traded; when several
dates touched the defining price, the earliest date in the quarter wins.

Entry price is the adjusted close on the snapshot date — the same series the
labels use, so a mid-quarter split cannot skew which date is "low".
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from identity.source import sql_quote

logger = logging.getLogger(__name__)

SNAPSHOT_KINDS = ("low", "median", "high")


def build_snapshot_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `snapshots` view from `sep_resolved`."""
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW snapshots AS
        WITH quarter_prices AS (
            SELECT permaticker, ticker, date, closeadj,
                   date_trunc('quarter', date) AS quarter
            FROM sep_resolved
        ),
        quarter_stats AS (
            SELECT permaticker, quarter,
                   count(*) AS quarter_trading_days,
                   min(closeadj) AS low_price,
                   quantile_disc(closeadj, 0.5) AS median_price,
                   max(closeadj) AS high_price
            FROM quarter_prices
            GROUP BY permaticker, quarter
        ),
        kind_dates AS (
            SELECT qp.permaticker, qp.quarter, k.snapshot_kind,
                   min(qp.date) AS snapshot_date
            FROM quarter_prices qp
            JOIN quarter_stats qs USING (permaticker, quarter)
            CROSS JOIN (VALUES ('low'), ('median'), ('high')) k(snapshot_kind)
            WHERE qp.closeadj = CASE k.snapshot_kind
                                    WHEN 'low' THEN qs.low_price
                                    WHEN 'median' THEN qs.median_price
                                    ELSE qs.high_price
                                END
            GROUP BY qp.permaticker, qp.quarter, k.snapshot_kind
        )
        SELECT kd.permaticker, qp.ticker, kd.quarter, qs.quarter_trading_days,
               kd.snapshot_kind, kd.snapshot_date,
               qp.closeadj AS entry_closeadj
        FROM kind_dates kd
        JOIN quarter_stats qs USING (permaticker, quarter)
        JOIN quarter_prices qp
          ON qp.permaticker = kd.permaticker AND qp.date = kd.snapshot_date
        """
    )


def write_snapshot_table(
    con: duckdb.DuckDBPyConnection,
    interim_dir: Path,
) -> dict[str, int]:
    """Write snapshots.parquet; return summary counts."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    snapshots_path = interim_dir / "snapshots.parquet"
    rows = con.execute(
        f"""
        COPY (
            SELECT * FROM snapshots
            ORDER BY permaticker, quarter, snapshot_kind
        )
        TO {sql_quote(str(snapshots_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    ).fetchone()[0]

    permatickers, quarters = con.execute(
        """
        SELECT count(DISTINCT permaticker), count(DISTINCT quarter)
        FROM snapshots
        """
    ).fetchone()
    counts = {
        "snapshot_rows": int(rows),
        "permatickers": int(permatickers),
        "quarters": int(quarters),
    }
    logger.info(
        "snapshots: %(snapshot_rows)d rows across %(permatickers)d permatickers "
        "and %(quarters)d quarters",
        counts,
    )
    return counts
