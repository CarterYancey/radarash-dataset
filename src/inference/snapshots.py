"""Inference snapshots: one row per currently-tradable stock (ADR 0014).

Unlike training snapshots (three intra-quarter touch dates per stock-quarter,
labels/snapshots.py), the inference dataset takes a single snapshot per
in-universe stock at its **latest available price**:

- `as_of` — the reference trading date: the last trading date in SEP on or
  before the requested date (default: the last date in SEP).
- A stock is included when its most recent trade is within
  `max_price_age_days` *trading days* of `as_of` (tolerates halts and thin
  prints without readmitting delisted stocks; 0 = traded on `as_of` exactly).
- `snapshot_date` is the stock's own last trade date, `entry_closeadj` its
  adjusted close that day — the freshest observable price, and the anchor
  the technical windows and marketcap use.
- `snapshot_kind` is `'inference'` for every row and `quarter` is uniform
  (the calendar quarter of `as_of`), so the assembly rank pass — which
  partitions by (quarter, snapshot_kind) — ranks the whole inference
  cross-section together even when snapshot dates straddle a quarter edge.

The view intentionally matches the training snapshot schema consumed by the
feature builders (permaticker, ticker, quarter, snapshot_kind,
snapshot_date, entry_closeadj), so every family view runs unchanged on it.
"""

from __future__ import annotations

import logging
from datetime import date

import duckdb

from identity.source import sql_quote

logger = logging.getLogger(__name__)

INFERENCE_SNAPSHOT_KIND = "inference"

# Trading days a stock's last print may trail `as_of` and still be included.
MAX_PRICE_AGE_TRADING_DAYS = 5


def resolve_as_of(
    con: duckdb.DuckDBPyConnection, as_of: date | None
) -> date | None:
    """The last trading date in `trading_calendar` on or before `as_of`
    (or the calendar's last date when `as_of` is None); None if out of range.
    """
    if as_of is None:
        row = con.execute("SELECT max(date) FROM trading_calendar").fetchone()
    else:
        row = con.execute(
            "SELECT max(date) FROM trading_calendar WHERE date <= ?", [as_of]
        ).fetchone()
    return row[0] if row else None


def build_inference_snapshot_view(
    con: duckdb.DuckDBPyConnection,
    *,
    as_of: date,
    max_price_age_days: int = MAX_PRICE_AGE_TRADING_DAYS,
) -> None:
    """Create the `snapshots` view (inference shape) from `sep_ix`."""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW snapshots AS
        WITH ref AS (
            SELECT ix AS as_of_ix, date_trunc('quarter', date) AS quarter
            FROM trading_calendar
            WHERE date = DATE {sql_quote(as_of.isoformat())}
        ),
        last_prints AS (
            SELECT p.permaticker,
                   max_by(p.date, p.ix) AS snapshot_date,
                   max_by(p.closeadj, p.ix) AS entry_closeadj,
                   max(p.ix) AS last_ix
            FROM sep_ix p
            CROSS JOIN ref
            WHERE p.ix <= ref.as_of_ix
            GROUP BY p.permaticker
        )
        SELECT lp.permaticker, u.ticker, ref.quarter,
               {sql_quote(INFERENCE_SNAPSHOT_KIND)} AS snapshot_kind,
               lp.snapshot_date, lp.entry_closeadj
        FROM last_prints lp
        CROSS JOIN ref
        JOIN universe u ON u.permaticker = lp.permaticker
        WHERE lp.last_ix >= ref.as_of_ix - {int(max_price_age_days)}
        """
    )
