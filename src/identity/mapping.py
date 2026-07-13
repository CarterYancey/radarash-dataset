"""Ticker ↔ permaticker mapping — the first pipeline artifact (README §2).

`permaticker` is the canonical entity key; `ticker` is a join key only.
Ticker reuse (one ticker string used by several permatickers over time) is
real in this data: the mapping flags reused tickers and a companion report
lists them, which is the raw material for verification task V2.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from .source import sql_quote

logger = logging.getLogger(__name__)


def build_mapping_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `mapping` view from `tickers_deduped`."""
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW mapping AS
        SELECT
            permaticker,
            ticker,
            name,
            exchange,
            category,
            is_delisted,
            firstpricedate,
            lastpricedate,
            count(*) OVER (PARTITION BY ticker) > 1 AS ticker_is_reused
        FROM tickers_deduped
        """
    )


def write_mapping_tables(
    con: duckdb.DuckDBPyConnection,
    interim_dir: Path,
) -> dict[str, int]:
    """Write the mapping and the V2 ticker-reuse report; return row counts."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    mapping_path = interim_dir / "ticker_permaticker.parquet"
    reuse_path = interim_dir / "ticker_reuse.parquet"

    rows = con.execute(
        f"""
        COPY (SELECT * FROM mapping ORDER BY ticker, permaticker)
        TO {sql_quote(str(mapping_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    ).fetchone()[0]

    reused = con.execute(
        f"""
        COPY (
            SELECT * FROM mapping WHERE ticker_is_reused
            ORDER BY ticker, firstpricedate
        )
        TO {sql_quote(str(reuse_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    ).fetchone()[0]

    logger.info(
        "mapping: %d permatickers (%d rows on reused tickers) -> %s",
        rows,
        reused,
        interim_dir,
    )
    return {"mapping_rows": int(rows), "reused_ticker_rows": int(reused)}
