"""CLI: build the per-family feature tables (M4).

    sharadar-features                     # all families
    sharadar-features --families valuation technical

Inputs (produced by `sharadar-ingest`, `sharadar-identity`, `sharadar-labels`):

    data/raw/SF1.parquet                  as-reported fundamentals
    data/raw/SEP.parquet                  daily prices
    data/interim/ticker_permaticker.parquet
    data/interim/universe.parquet
    data/interim/snapshots.parquet

Produces one parquet per family under data/interim/features/, each on the
labels key (permaticker, snapshot_date, snapshot_kind), with columns
validated against the registry (docs/features.md / registry.py).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

from .base import build_fund_base_view
from .classification import build_classification_view
from .growth import build_growth_view
from .market import build_market_view
from .meta import build_meta_view
from .output import write_family_table
from .profitability import build_profitability_view
from .quality import build_quality_view
from .registry import FAMILIES
from .solvency import build_solvency_view
from .source import check_sf1_fields, create_feature_source_views
from .technical import build_technical_view
from .valuation import build_valuation_view

logger = logging.getLogger(__name__)

FAMILY_BUILDERS = {
    "meta": build_meta_view,
    "valuation": build_valuation_view,
    "profitability": build_profitability_view,
    "growth": build_growth_view,
    "solvency": build_solvency_view,
    "quality": build_quality_view,
    "technical": build_technical_view,
    "classification": build_classification_view,
}
assert tuple(FAMILY_BUILDERS) == FAMILIES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sharadar-features",
        description="Build the per-family point-in-time feature tables.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Root data directory (default: ./data)",
    )
    parser.add_argument(
        "--families",
        nargs="+",
        choices=FAMILIES,
        default=list(FAMILIES),
        metavar="FAMILY",
        help=f"Families to build (default: all; choices: {', '.join(FAMILIES)})",
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
        "SF1 fundamentals (run `sharadar-ingest --tables SF1`)": raw_dir / "SF1.parquet",
        "SEP prices (run `sharadar-ingest --tables SEP`)": raw_dir / "SEP.parquet",
        "mapping (run `sharadar-identity`)": interim_dir / "ticker_permaticker.parquet",
        "universe (run `sharadar-identity`)": interim_dir / "universe.parquet",
        "snapshots (run `sharadar-labels`)": interim_dir / "snapshots.parquet",
    }
    missing = [f"{path} — {hint}" for hint, path in inputs.items() if not path.exists()]
    if missing:
        for line in missing:
            logger.error("missing input: %s", line)
        return 2

    families = [f for f in FAMILIES if f in set(args.families)]
    con = duckdb.connect()
    try:
        # Streaming-friendly settings: output order is imposed at COPY time,
        # and the technical family's SEP-window join may spill.
        con.execute("SET preserve_insertion_order = false")
        interim_dir.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory = '{interim_dir / '.duckdb_tmp'}'")
        if args.memory_limit:
            con.execute("SET memory_limit = ?", [args.memory_limit])

        check_sf1_fields(con, raw_dir / "SF1.parquet")
        create_feature_source_views(
            con,
            sf1_parquet=raw_dir / "SF1.parquet",
            sep_parquet=raw_dir / "SEP.parquet",
            mapping_parquet=interim_dir / "ticker_permaticker.parquet",
            universe_parquet=interim_dir / "universe.parquet",
            snapshots_parquet=interim_dir / "snapshots.parquet",
        )
        build_fund_base_view(con)
        build_market_view(con)

        features_dir = interim_dir / "features"
        for family in families:
            FAMILY_BUILDERS[family](con)
            write_family_table(con, features_dir, family)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
