"""CLI: build the identity artifacts from the ingested TICKERS table.

    sharadar-identity                 # reads data/raw/TICKERS.parquet
    sharadar-identity --start-year 1997

Produces under data/interim/:

    ticker_permaticker.parquet        canonical mapping, reuse flagged
    ticker_reuse.parquet              V2 raw material
    universe.parquet                  PLAN.md §3 flags + in_universe verdict
    universe_counts_by_year.parquet   per-year counts (also as .csv)
    reports/universe_counts_by_year.png
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

from .mapping import build_mapping_view, write_mapping_tables
from .report import build_counts_view, plot_universe_counts, write_counts_tables
from .source import create_tickers_view
from .universe import build_universe_view, write_universe_table

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sharadar-identity",
        description="Build ticker/permaticker mapping, universe table, and per-year counts.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Root data directory (default: ./data)",
    )
    parser.add_argument(
        "--source-table",
        default="SEP",
        help="TICKERS metadata rows to build from (default: SEP)",
    )
    parser.add_argument(
        "--start-year",
        type=int,
        default=None,
        help="Earliest year in the counts report (default: earliest in data)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = build_parser().parse_args(argv)

    tickers_parquet = args.data_dir / "raw" / "TICKERS.parquet"
    if not tickers_parquet.exists():
        logger.error(
            "%s not found — run `sharadar-ingest --tables TICKERS` first",
            tickers_parquet,
        )
        return 2
    interim_dir = args.data_dir / "interim"

    con = duckdb.connect()
    try:
        create_tickers_view(con, tickers_parquet, source_table=args.source_table)
        build_mapping_view(con)
        write_mapping_tables(con, interim_dir)

        build_universe_view(con)
        write_universe_table(con, interim_dir)

        build_counts_view(con, start_year=args.start_year)
        counts = write_counts_tables(con, interim_dir)
        plot_universe_counts(
            counts, interim_dir / "reports" / "universe_counts_by_year.png"
        )
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
