"""CLI: assemble the versioned training dataset (M5).

    sharadar-assemble                       # writes data/datasets/dataset_v1.0/
    sharadar-assemble --dataset-version 1.1 --rank-guard 20

Inputs (produced by `sharadar-labels`, `sharadar-features`, `sharadar-splits`):

    data/interim/labels.parquet             wide label matrix
    data/interim/features/{family}.parquet  the eight family tables
    data/interim/splits.parquet             role tags (copied verbatim)
    data/interim/split_folds.parquet        fold manifest (copied verbatim)

Produces data/datasets/dataset_v{VERSION}/ with dataset.parquet (features ×
ranks × labels × uniqueness weights), the split files, and manifest.json.
Dataset directories are immutable: an existing version is refused unless
--force is given.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

from features.registry import FAMILIES

from .output import build_dataset_view, write_dataset
from .source import (
    available_horizons,
    create_assembly_source_views,
    validate_key_alignment,
)
from .weights import build_weight_views
from .wide import MIN_INDUSTRY_PEERS, RANK_GUARD, build_wide_views

logger = logging.getLogger(__name__)

DEFAULT_VERSION = "1.1"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sharadar-assemble",
        description="Assemble the versioned dataset: families × labels × "
        "splits, ranks, composites, uniqueness weights.",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Root data directory (default: ./data)",
    )
    parser.add_argument(
        "--dataset-version",
        default=DEFAULT_VERSION,
        help=f"Version suffix of the output directory "
        f"data/datasets/dataset_vX.Y (default: {DEFAULT_VERSION})",
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
        help="Overwrite an existing dataset directory of the same version",
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

    interim_dir = args.data_dir / "interim"
    features_dir = interim_dir / "features"
    inputs = {
        "labels": (interim_dir / "labels.parquet", "sharadar-labels"),
        **{
            f"features/{family}": (
                features_dir / f"{family}.parquet",
                "sharadar-features",
            )
            for family in FAMILIES
        },
        "splits": (interim_dir / "splits.parquet", "sharadar-splits"),
        "split_folds": (interim_dir / "split_folds.parquet", "sharadar-splits"),
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
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET temp_directory = '{interim_dir / '.duckdb_tmp'}'")
        if args.memory_limit:
            con.execute("SET memory_limit = ?", [args.memory_limit])

        create_assembly_source_views(
            con,
            labels_parquet=inputs["labels"][0],
            features_dir=features_dir,
        )
        rows = validate_key_alignment(con)
        horizons = available_horizons(con)
        if not horizons:
            logger.error(
                "labels.parquet carries no horizon columns — rerun "
                "`sharadar-labels`"
            )
            return 1
        logger.info(
            "assembling %d snapshot rows, horizons %s",
            rows,
            ", ".join(f"{h}y" for h in horizons),
        )
        build_wide_views(
            con,
            rank_guard=args.rank_guard,
            min_industry_peers=args.min_industry_peers,
        )
        build_weight_views(con, horizons=horizons)
        build_dataset_view(con, horizons=horizons)
        write_dataset(
            con,
            datasets_dir=args.data_dir / "datasets",
            version=args.dataset_version,
            horizons=horizons,
            splits_parquet=inputs["splits"][0],
            folds_parquet=inputs["split_folds"][0],
            inputs={name: path for name, (path, _) in inputs.items()},
            params={
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
