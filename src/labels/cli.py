"""CLI: build quarterly snapshots and forward-return labels (M3).

    sharadar-labels                    # reads data/raw + data/interim
    sharadar-labels --horizons 1 3

Inputs (produced by `sharadar-ingest` and `sharadar-identity`):

    data/raw/SEP.parquet               daily adjusted prices
    data/raw/SFP.parquet               benchmark (SPY) prices
    data/raw/ACTIONS.parquet           delist reasons
    data/interim/ticker_permaticker.parquet
    data/interim/universe.parquet

Produces under data/interim/:

    snapshots.parquet                  low/median/high quarterly snapshots
    labels.parquet                     one row per snapshot, wide label matrix
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

from .compute import CAGR_THRESHOLDS_PCT, build_label_views, write_labels_table
from .delistings import build_delisting_view
from .paths import HORIZON_YEARS, TERMINAL_WINDOW_TRADING_DAYS, build_path_views
from .snapshots import build_snapshot_view, write_snapshot_table
from .source import BENCHMARK_TICKER, create_source_views

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sharadar-labels",
        description="Build quarterly low/median/high snapshots and forward-return labels.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Root data directory (default: ./data)",
    )
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        default=list(HORIZON_YEARS),
        metavar="YEARS",
        help=f"Forward horizons in years (default: {' '.join(map(str, HORIZON_YEARS))})",
    )
    parser.add_argument(
        "--terminal-window-days",
        type=int,
        default=TERMINAL_WINDOW_TRADING_DAYS,
        help="Trading days in the terminal averaging window "
        f"(default: {TERMINAL_WINDOW_TRADING_DAYS})",
    )
    parser.add_argument(
        "--benchmark-ticker",
        default=BENCHMARK_TICKER,
        help=f"SFP ticker for relative labels (default: {BENCHMARK_TICKER})",
    )
    parser.add_argument(
        "--memory-limit",
        default=None,
        help="DuckDB memory limit, e.g. '8GB' (default: DuckDB's default)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = build_parser().parse_args(argv)

    raw_dir = args.data_dir / "raw"
    interim_dir = args.data_dir / "interim"
    inputs = {
        "SEP prices (run `sharadar-ingest --tables SEP`)": raw_dir / "SEP.parquet",
        "SFP prices (run `sharadar-ingest --tables SFP`)": raw_dir / "SFP.parquet",
        "ACTIONS (run `sharadar-ingest --tables ACTIONS`)": raw_dir / "ACTIONS.parquet",
        "mapping (run `sharadar-identity`)": interim_dir / "ticker_permaticker.parquet",
        "universe (run `sharadar-identity`)": interim_dir / "universe.parquet",
    }
    missing = [f"{path} — {hint}" for hint, path in inputs.items() if not path.exists()]
    if missing:
        for line in missing:
            logger.error("missing input: %s", line)
        return 2

    con = duckdb.connect()
    try:
        # Streaming-friendly settings: output order is imposed at COPY time,
        # and the SEP-wide ASOF joins may spill.
        con.execute("SET preserve_insertion_order = false")
        interim_dir.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory = '{interim_dir / '.duckdb_tmp'}'")
        if args.memory_limit:
            con.execute("SET memory_limit = ?", [args.memory_limit])

        create_source_views(
            con,
            sep_parquet=raw_dir / "SEP.parquet",
            sfp_parquet=raw_dir / "SFP.parquet",
            mapping_parquet=interim_dir / "ticker_permaticker.parquet",
            universe_parquet=interim_dir / "universe.parquet",
            benchmark_ticker=args.benchmark_ticker,
        )
        build_snapshot_view(con)
        write_snapshot_table(con, interim_dir)

        build_delisting_view(con, raw_dir / "ACTIONS.parquet")
        horizons = tuple(dict.fromkeys(sorted(args.horizons)))
        build_path_views(
            con,
            horizons=horizons,
            window_days=args.terminal_window_days,
        )
        build_label_views(
            con,
            horizons=horizons,
            thresholds_pct=CAGR_THRESHOLDS_PCT,
        )
        write_labels_table(con, interim_dir)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
