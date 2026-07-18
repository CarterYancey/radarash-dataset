"""Shared source views for the features pipeline.

Everything downstream works from these temp views:

- `sf1_filings`        — one row per as-reported filing
                         (permaticker, datekey, reportperiod): ARQ
                         point-in-time levels (`l_*`) plus the same filing's
                         ART trailing-twelve-month flows (`f_*`, NULL when
                         the export has no ART row for that filing).
- `sf1_filings_latest` — deduplicated to one row per (permaticker, datekey)
                         (a 10-K plus catch-up 10-Qs can share a datekey:
                         the most recent fiscal period wins) so the T0 ASOF
                         join has a unique right side.
- `snapshots`          — the labels module's snapshot rows, verbatim.
- `sep_ix`             — permaticker-resolved daily prices (close, closeadj,
                         volume) on the dense trading-calendar index, with
                         per-stock daily returns for the technical family.
- `trading_calendar`   — market trading calendar (distinct SEP dates).
- `universe`, `price_mapping` — identity artifacts, verbatim.

SF1 rows carry only a ticker; resolution to permatickers follows the same
rule as the QA pipeline (src/qa/source.py): unambiguous tickers resolve
unconditionally, reused tickers go to the permaticker whose price-coverage
window (widened by grace margins) contains the filing's datekey.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from identity.source import sql_quote

logger = logging.getLogger(__name__)

# Filing dates tolerated outside a reused ticker's price-coverage window
# (same margins as src/qa/source.py: S-1 fundamentals predate the first
# price; final 10-K/Qs postdate the last trade).
PRE_LISTING_GRACE_DAYS = 540
POST_DELISTING_GRACE_DAYS = 366

# ARQ point-in-time levels the registry formulas read (aliased `l_*`).
ARQ_LEVEL_FIELDS: tuple[str, ...] = (
    "assets", "assetsc", "cashneq", "receivables", "inventory", "ppnenet",
    "investments", "liabilities", "liabilitiesc", "debt", "debtnc",
    "equity", "retearn", "workingcapital", "tangibles", "invcap",
    "sharesbas", "sharefactor",
)

# ART trailing-twelve-month flows (aliased `f_*`).
ART_FLOW_FIELDS: tuple[str, ...] = (
    "revenue", "gp", "sgna", "depamor", "ebit", "ebitda", "intexp",
    "netinc", "ncfo", "fcf", "ncfcommon", "ncfdebt", "ncfdiv", "epsdil",
    "rnd", "capex",
)


def check_sf1_fields(con: duckdb.DuckDBPyConnection, sf1_parquet: Path) -> None:
    """Fail fast if the SF1 export lacks a field the registry needs.

    Unlike the QA reports (which skip missing tracked fields), a missing
    feature input would silently change feature semantics — refuse to run.
    """
    rows = con.execute(
        f"DESCRIBE SELECT * FROM read_parquet({sql_quote(str(sf1_parquet))})"
    ).fetchall()
    present = {row[0] for row in rows}
    needed = set(ARQ_LEVEL_FIELDS) | set(ART_FLOW_FIELDS) | {
        "ticker", "dimension", "datekey", "reportperiod",
    }
    missing = sorted(needed - present)
    if missing:
        raise ValueError(
            f"SF1 export at {sf1_parquet} lacks required fields: "
            + ", ".join(missing)
        )


def create_feature_source_views(
    con: duckdb.DuckDBPyConnection,
    *,
    sf1_parquet: Path,
    sep_parquet: Path,
    mapping_parquet: Path,
    universe_parquet: Path,
    snapshots_parquet: Path,
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
        SELECT permaticker, ticker, firstpricedate, lastpricedate,
               ticker_is_reused
        FROM read_parquet({sql_quote(str(mapping_parquet))})
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW snapshots AS
        SELECT permaticker, quarter, snapshot_kind, snapshot_date,
               entry_closeadj
        FROM read_parquet({sql_quote(str(snapshots_parquet))})
        """
    )

    all_fields = tuple(dict.fromkeys(ARQ_LEVEL_FIELDS + ART_FLOW_FIELDS))
    field_list = "".join(f", f.{name}" for name in all_fields)
    level_list = "".join(f", arq.{name} AS l_{name}" for name in ARQ_LEVEL_FIELDS)
    flow_list = "".join(f", art.{name} AS f_{name}" for name in ART_FLOW_FIELDS)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW sf1_resolved AS
        WITH candidates AS (
            SELECT
                m.permaticker,
                f.dimension,
                f.datekey,
                f.reportperiod
                {field_list},
                row_number() OVER (
                    PARTITION BY f.ticker, f.dimension, f.datekey, f.reportperiod
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
            WHERE f.dimension IN ('ARQ', 'ART')
              AND f.datekey IS NOT NULL
              AND f.reportperiod IS NOT NULL
        )
        SELECT * EXCLUDE (rn) FROM candidates WHERE rn = 1
        """
    )
    # A filing is identified by its ARQ row; the ART row of the same
    # (permaticker, datekey, reportperiod) carries its TTM flows. Missing
    # ART (young companies without four quarters) leaves flows NULL.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW sf1_filings AS
        SELECT arq.permaticker, arq.datekey, arq.reportperiod
               {level_list}
               {flow_list}
        FROM (SELECT * FROM sf1_resolved WHERE dimension = 'ARQ') arq
        LEFT JOIN (SELECT * FROM sf1_resolved WHERE dimension = 'ART') art
          ON art.permaticker = arq.permaticker
         AND art.datekey = arq.datekey
         AND art.reportperiod = arq.reportperiod
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW sf1_filings_latest AS
        SELECT * EXCLUDE (rn) FROM (
            SELECT *, row_number() OVER (
                PARTITION BY permaticker, datekey
                ORDER BY reportperiod DESC
            ) AS rn
            FROM sf1_filings
        ) WHERE rn = 1
        """
    )

    # The market calendar comes from all of SEP (not the universe subset) so
    # window offsets survive thin universes; `ix` is a dense trading-day
    # index, immune to holidays/weekends (same as labels/source.py).
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
    # Daily prices resolved to permatickers (same rule as labels/source.py),
    # with the calendar index and per-stock daily returns. The technical
    # family needs the unadjusted close (dollar volume, marketcap) as well
    # as closeadj (returns).
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW sep_ix AS
        SELECT m.permaticker, p.date, c.ix, p.close, p.closeadj, p.volume,
               p.close * p.volume AS dollar_volume,
               p.closeadj / lag(p.closeadj) OVER w - 1 AS ret_1d,
               ln(p.closeadj / lag(p.closeadj) OVER w) AS logret_1d
        FROM read_parquet({sql_quote(str(sep_parquet))}) p
        JOIN price_mapping m
          ON p.ticker = m.ticker
         AND p.date >= coalesce(m.firstpricedate, DATE '0001-01-01')
         AND p.date <= coalesce(m.lastpricedate, DATE '9999-12-31')
        JOIN universe u ON u.permaticker = m.permaticker AND u.in_universe
        JOIN trading_calendar c ON c.date = p.date
        WHERE p.closeadj IS NOT NULL AND p.closeadj > 0
        WINDOW w AS (PARTITION BY m.permaticker ORDER BY c.ix)
        """
    )
