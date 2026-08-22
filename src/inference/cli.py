"""CLI: build the label-free inference dataset (ADR 0014).

    sharadar-inference                       # snapshot at the latest SEP date
    sharadar-inference --as-of 2026-06-30 --max-price-age-days 0

Inputs (produced by `sharadar-ingest` and `sharadar-identity`):

    data/raw/SF1.parquet                  as-reported fundamentals
    data/raw/SEP.parquet                  daily prices
    data/interim/ticker_permaticker.parquet
    data/interim/universe.parquet

One snapshot per currently-tradable in-universe stock at its latest
available price, pushed through the *same* family builders and assembly
rank pass as training (so a trained model sees the exact feature/rank
columns it was fit on), with same-day filings included — the conceptual
entry is the next trading day, so that stays point-in-time. No labels, no
splits, no sample weights. Produces data/datasets/inference_{as_of}/ with
dataset.parquet and manifest.json.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import duckdb

from assemble.source import family_view
from assemble.wide import MIN_INDUSTRY_PEERS, RANK_GUARD, build_wide_views
from features.base import build_fund_base_view
from features.cli import FAMILY_BUILDERS
from features.history import build_fund_history_view
from features.market import build_market_view
from features.output import validate_family_columns, view_name
from features.registry import FAMILIES
from features.source import check_sf1_fields, create_feature_source_views

from .output import build_inference_view, write_inference_dataset
from .snapshots import (
    MAX_PRICE_AGE_TRADING_DAYS,
    build_inference_snapshot_view,
    resolve_as_of,
)

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sharadar-inference",
        description="Build the label-free inference dataset: one snapshot "
        "per tradable stock at its latest available price, all features "
        "and ranks, no labels.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Root data directory (default: ./data)",
    )
    parser.add_argument(
        "--as-of",
        type=date.fromisoformat,
        default=None,
        metavar="YYYY-MM-DD",
        help="Reference date; snapshots use the last trading date on or "
        "before it (default: the last date in SEP)",
    )
    parser.add_argument(
        "--max-price-age-days",
        type=int,
        default=MAX_PRICE_AGE_TRADING_DAYS,
        help="Trading days a stock's last print may trail the as-of date "
        f"and still be included (default: {MAX_PRICE_AGE_TRADING_DAYS})",
    )
    parser.add_argument(
        "--rank-guard",
        type=int,
        default=RANK_GUARD,
        help="Minimum non-null cross-section for rank columns, ADR 0008 "
        f"(default: {RANK_GUARD})",
    )
    parser.add_argument(
        "--min-industry-peers",
        type=int,
        default=MIN_INDUSTRY_PEERS,
        help="Minimum non-null famaindustry cross-section per G-score "
        f"median, ADR 0013 (default: {MIN_INDUSTRY_PEERS})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing inference directory of the same as-of date",
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
        "SF1": (raw_dir / "SF1.parquet", "sharadar-ingest --tables SF1"),
        "SEP": (raw_dir / "SEP.parquet", "sharadar-ingest --tables SEP"),
        "mapping": (
            interim_dir / "ticker_permaticker.parquet",
            "sharadar-identity",
        ),
        "universe": (interim_dir / "universe.parquet", "sharadar-identity"),
    }
    missing = [
        f"{path} — {name} (run `{hint}`)"
        for name, (path, hint) in inputs.items()
        if not path.exists()
    ]
    if missing:
        for line in missing:
            logger.error("missing input: %s", line)
        return 2

    con = duckdb.connect()
    try:
        # Same streaming-friendly settings as the features/assembly CLIs.
        con.execute("SET preserve_insertion_order = false")
        interim_dir.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory = '{interim_dir / '.duckdb_tmp'}'")
        if args.memory_limit:
            con.execute("SET memory_limit = ?", [args.memory_limit])

        check_sf1_fields(con, inputs["SF1"][0])
        create_feature_source_views(
            con,
            sf1_parquet=inputs["SF1"][0],
            sep_parquet=inputs["SEP"][0],
            mapping_parquet=inputs["mapping"][0],
            universe_parquet=inputs["universe"][0],
            snapshots_parquet=None,
        )
        as_of = resolve_as_of(con, args.as_of)
        if as_of is None:
            logger.error(
                "no trading date on or before %s in SEP", args.as_of
            )
            return 1
        build_inference_snapshot_view(
            con, as_of=as_of, max_price_age_days=args.max_price_age_days
        )
        rows = con.execute("SELECT count(*) FROM snapshots").fetchone()[0]
        if rows == 0:
            logger.error("no tradable in-universe stock as of %s", as_of)
            return 1
        logger.info("inference snapshot: %d stocks as of %s", rows, as_of)

        # ADR 0014: filings dated the snapshot day itself are usable.
        build_fund_base_view(con, include_same_day_filings=True)
        build_fund_history_view(con, include_same_day_filings=True)
        build_market_view(con)
        for family in FAMILIES:
            FAMILY_BUILDERS[family](con)
            validate_family_columns(con, family)
            con.execute(
                f"""
                CREATE OR REPLACE TEMP VIEW {family_view(family)} AS
                SELECT * FROM {view_name(family)}
                """
            )
        # The assembly rank pass reads `labels_src` for the key + entry
        # metadata; here that is the snapshot view itself (no label columns).
        con.execute(
            """
            CREATE OR REPLACE TEMP VIEW labels_src AS
            SELECT permaticker, ticker, quarter, snapshot_kind,
                   snapshot_date, entry_closeadj
            FROM snapshots
            """
        )
        build_wide_views(
            con,
            rank_guard=args.rank_guard,
            min_industry_peers=args.min_industry_peers,
        )
        build_inference_view(con)
        write_inference_dataset(
            con,
            datasets_dir=args.data_dir / "datasets",
            as_of=as_of,
            inputs={name: path for name, (path, _) in inputs.items()},
            params={
                "max_price_age_days": args.max_price_age_days,
                "rank_guard": args.rank_guard,
                "min_industry_peers": args.min_industry_peers,
            },
            force=args.force,
        )
    except (FileExistsError, ValueError) as exc:
        logger.error("%s", exc)
        return 1
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
