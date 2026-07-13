"""Shared deduplicated view over the raw TICKERS parquet.

`TICKERS` carries one metadata row per (table, ticker): the same security
appears once for SEP, once for SF1, and so on. Downstream identity artifacts
are built from a single source table's rows (default SEP — the price table,
whose first/last price dates give the security's trading window), deduplicated
to exactly one row per permaticker.
"""

from __future__ import annotations

from pathlib import Path

import duckdb


def sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def create_tickers_view(
    con: duckdb.DuckDBPyConnection,
    tickers_parquet: Path,
    *,
    source_table: str = "SEP",
) -> None:
    """Create the `tickers_deduped` temp view: one row per permaticker."""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW tickers_deduped AS
        WITH source_rows AS (
            SELECT
                permaticker,
                ticker,
                name,
                exchange,
                category,
                sector,
                industry,
                famaindustry,
                TRY_CAST(siccode AS INTEGER) AS siccode,
                scalemarketcap,
                isdelisted = 'Y' AS is_delisted,
                firstpricedate,
                lastpricedate,
                lastupdated,
                row_number() OVER (
                    PARTITION BY permaticker
                    ORDER BY lastupdated DESC NULLS LAST, ticker
                ) AS rn
            FROM read_parquet({sql_quote(str(tickers_parquet))})
            WHERE "table" = {sql_quote(source_table)}
              AND permaticker IS NOT NULL
        )
        SELECT * EXCLUDE (rn) FROM source_rows WHERE rn = 1
        """
    )
