"""Shared source views for the labels pipeline.

Everything downstream works from four temp views:

- `sep_resolved`   — SEP daily prices resolved to permatickers (reused
                     tickers disambiguated by the mapping's price window)
                     and filtered to the in-universe set.
- `trading_calendar` — the market trading calendar (distinct SEP dates)
                     with a dense row index for window arithmetic.
- `benchmark_prices` — the benchmark's adjusted closes from SFP.
- `universe`       — the identity module's universe table, verbatim.
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from identity.source import sql_quote

BENCHMARK_TICKER = "SPY"


def create_source_views(
    con: duckdb.DuckDBPyConnection,
    *,
    sep_parquet: Path,
    sfp_parquet: Path,
    mapping_parquet: Path,
    universe_parquet: Path,
    benchmark_ticker: str = BENCHMARK_TICKER,
) -> None:
    """Create the source temp views over the raw and interim parquet files."""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW universe AS
        SELECT * FROM read_parquet({sql_quote(str(universe_parquet))})
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW price_mapping AS
        SELECT permaticker, ticker, firstpricedate, lastpricedate
        FROM read_parquet({sql_quote(str(mapping_parquet))})
        """
    )
    # Resolve SEP rows to permatickers. The mapping's price-coverage window
    # disambiguates reused tickers: a price row belongs to the permaticker
    # whose [firstpricedate, lastpricedate] contains it. Non-positive or
    # missing closeadj rows are unusable for return math and are dropped.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW sep_resolved AS
        SELECT m.permaticker, p.ticker, p.date, p.closeadj
        FROM read_parquet({sql_quote(str(sep_parquet))}) p
        JOIN price_mapping m
          ON p.ticker = m.ticker
         AND p.date >= coalesce(m.firstpricedate, DATE '0001-01-01')
         AND p.date <= coalesce(m.lastpricedate, DATE '9999-12-31')
        JOIN universe u ON u.permaticker = m.permaticker AND u.in_universe
        WHERE p.closeadj IS NOT NULL AND p.closeadj > 0
        """
    )
    # The market calendar comes from all of SEP (not the universe subset) so
    # horizon-end lookups survive thin universes. `ix` is a dense trading-day
    # index: "21 trading days" is an ix range, immune to holidays/weekends.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW trading_calendar AS
        SELECT date, row_number() OVER (ORDER BY date) AS ix
        FROM (
            SELECT DISTINCT date
            FROM read_parquet({sql_quote(str(sep_parquet))})
            WHERE date IS NOT NULL
        )
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW benchmark_prices AS
        SELECT date, closeadj
        FROM read_parquet({sql_quote(str(sfp_parquet))})
        WHERE ticker = {sql_quote(benchmark_ticker)}
          AND closeadj IS NOT NULL AND closeadj > 0
        """
    )
