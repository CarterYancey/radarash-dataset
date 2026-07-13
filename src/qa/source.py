"""Shared source views for the QA reports.

Everything downstream works from these temp views:

- `sf1_arq`         — SF1 as-reported quarterly rows resolved to permatickers.
- `sf1_arq_latest`  — same, deduplicated to one row per (permaticker, datekey)
                      so ASOF joins have a unique right side.
- `snapshots_median`— the median-kind snapshot rows: the canonical one-per-
                      (stock, quarter) evaluation row (decision 0001's low/high
                      kinds share the quarter's fundamentals, so coverage is
                      measured once).
- `labels_median`   — matching label rows (only when labels are an input).
- `sep_resolved`    — permaticker-resolved daily prices (only when SEP is an
                      input; same resolution rule as the labels pipeline).
- `universe`, `price_mapping` — identity artifacts, verbatim.

SF1 rows carry only a ticker. A ticker mapped to exactly one permaticker
resolves unconditionally — filings legitimately fall outside the price window
(S-1 fundamentals predate the first price; final 10-K/Qs postdate the last
trade). Only **reused** tickers need arbitration: the filing goes to the
permaticker whose price-coverage window (widened by grace margins) contains
its datekey, nearest window on overlap; reused-ticker filings outside every
widened window stay unresolved — itself a QA number.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from identity.source import sql_quote

logger = logging.getLogger(__name__)

# Filing dates tolerated outside the price-coverage window.
PRE_LISTING_GRACE_DAYS = 540
POST_DELISTING_GRACE_DAYS = 366

# SF1 fields whose availability the coverage report tracks (the inputs the
# ADR-0003/0005 feature families need most). Intersected with the columns
# actually present in the export — Sharadar adds/removes columns over time.
KEY_FIELDS: tuple[str, ...] = (
    "revenue", "cor", "gp", "sgna", "rnd", "depamor", "ebit", "ebitda",
    "intexp", "taxexp", "netinc", "ncfo", "capex", "fcf",
    "ncfcommon", "ncfdebt", "ncfdiv",
    "assets", "assetsc", "cashneq", "receivables", "inventory", "ppnenet",
    "intangibles", "liabilities", "liabilitiesc", "payables", "debt",
    "equity", "retearn", "workingcapital",
    "sharesbas", "sharefactor",
)


def parquet_columns(con: duckdb.DuckDBPyConnection, parquet: Path) -> set[str]:
    rows = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet({sql_quote(str(parquet))})"
    ).fetchall()
    return {row[0] for row in rows}


def detect_key_fields(con: duckdb.DuckDBPyConnection, sf1_parquet: Path) -> list[str]:
    """KEY_FIELDS actually present in this SF1 export, warning on the rest."""
    present_cols = parquet_columns(con, sf1_parquet)
    fields = [f for f in KEY_FIELDS if f in present_cols]
    missing = sorted(set(KEY_FIELDS) - present_cols)
    if missing:
        logger.warning(
            "SF1 export lacks %d tracked fields (skipped): %s",
            len(missing),
            ", ".join(missing),
        )
    return fields


def create_qa_source_views(
    con: duckdb.DuckDBPyConnection,
    *,
    sf1_parquet: Path,
    mapping_parquet: Path,
    universe_parquet: Path,
    snapshots_parquet: Path,
    fields: list[str],
    labels_parquet: Path | None = None,
    sep_parquet: Path | None = None,
) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW universe AS
        SELECT * FROM read_parquet({sql_quote(str(universe_parquet))})
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW price_mapping AS
        SELECT permaticker, ticker, firstpricedate, lastpricedate,
               ticker_is_reused
        FROM read_parquet({sql_quote(str(mapping_parquet))})
        """
    )

    field_list = "".join(f", f.{name}" for name in fields)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW sf1_arq AS
        WITH candidates AS (
            SELECT
                m.permaticker,
                f.ticker,
                f.datekey,
                f.reportperiod
                {field_list},
                row_number() OVER (
                    PARTITION BY f.ticker, f.datekey, f.reportperiod
                    ORDER BY CASE
                        WHEN f.datekey
                             BETWEEN coalesce(m.firstpricedate, DATE '0001-01-01')
                                 AND coalesce(m.lastpricedate, DATE '9999-12-31')
                        THEN 0
                        ELSE least(
                            abs(f.datekey - coalesce(m.firstpricedate, f.datekey)),
                            abs(f.datekey - coalesce(m.lastpricedate, f.datekey))
                        )
                    END
                ) AS rn
            FROM read_parquet({sql_quote(str(sf1_parquet))}) f
            JOIN price_mapping m
              ON f.ticker = m.ticker
             AND (NOT m.ticker_is_reused
                  OR (f.datekey >= coalesce(
                          m.firstpricedate - {PRE_LISTING_GRACE_DAYS},
                          DATE '0001-01-01')
                      AND f.datekey <= coalesce(
                          m.lastpricedate + {POST_DELISTING_GRACE_DAYS},
                          DATE '9999-12-31')))
            WHERE f.dimension = 'ARQ'
              AND f.datekey IS NOT NULL
              AND f.reportperiod IS NOT NULL
        )
        SELECT * EXCLUDE (rn) FROM candidates WHERE rn = 1
        """
    )
    # Two filings can share a datekey (10-K + 10-Q catch-ups): for "the latest
    # filing as of a date" the most recent fiscal period wins.
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW sf1_arq_latest AS
        SELECT * EXCLUDE (rn) FROM (
            SELECT *, row_number() OVER (
                PARTITION BY permaticker, datekey
                ORDER BY reportperiod DESC
            ) AS rn
            FROM sf1_arq
        ) WHERE rn = 1
        """
    )

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW snapshots_median AS
        SELECT permaticker, quarter, snapshot_date
        FROM read_parquet({sql_quote(str(snapshots_parquet))})
        WHERE snapshot_kind = 'median'
        """
    )
    if labels_parquet is not None:
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW labels_median AS
            SELECT * FROM read_parquet({sql_quote(str(labels_parquet))})
            WHERE snapshot_kind = 'median'
            """
        )
    if sep_parquet is not None:
        # Same resolution rule as labels/source.py: a price row belongs to the
        # permaticker whose price window contains it.
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW sep_resolved AS
            SELECT m.permaticker, p.date
            FROM read_parquet({sql_quote(str(sep_parquet))}) p
            JOIN price_mapping m
              ON p.ticker = m.ticker
             AND p.date >= coalesce(m.firstpricedate, DATE '0001-01-01')
             AND p.date <= coalesce(m.lastpricedate, DATE '9999-12-31')
            WHERE p.closeadj IS NOT NULL AND p.closeadj > 0
            """
        )
