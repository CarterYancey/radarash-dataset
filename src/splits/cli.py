"""CLI: tag purged/embargoed train/test splits (M5, PLAN.md §7).

    sharadar-splits                    # reads data/interim/labels.parquet
    sharadar-splits --embargo-days 30 --holdout-years 3

Inputs (produced by `sharadar-labels`):

    data/interim/labels.parquet        wide label matrix, one row per snapshot

Produces under data/interim/:

    splits.parquet                     (scheme, fold, horizon, snapshot) -> role
    split_folds.parquet                frozen fold manifest with role counts

Schemes: sealed `holdout` + expanding `walkforward` (purged/embargoed,
decision 0011) and the diagnostic-only `entity_holdout` / `random_kfold`
(unpurged by design, decision 0010 — never for model selection).
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

from labels.paths import HORIZON_YEARS

from .diagnostics import build_diag_views
from .folds import (
    EMBARGO_DAYS,
    HOLDOUT_YEARS,
    MIN_TRAIN_YEARS,
    build_fold_view,
    create_snapshot_horizon_view,
    write_folds_table,
)
from .tags import build_tag_view, write_splits_table

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sharadar-splits",
        description="Tag purged/embargoed holdout and walk-forward splits per horizon.",
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
        help=f"Label horizons in years (default: {' '.join(map(str, HORIZON_YEARS))})",
    )
    parser.add_argument(
        "--embargo-days",
        type=int,
        default=EMBARGO_DAYS,
        help=f"Calendar days of embargo after purging (default: {EMBARGO_DAYS})",
    )
    parser.add_argument(
        "--holdout-years",
        type=int,
        default=HOLDOUT_YEARS,
        help="Final observable calendar years sealed as holdout, per horizon "
        f"(default: {HOLDOUT_YEARS})",
    )
    parser.add_argument(
        "--min-train-years",
        type=int,
        default=MIN_TRAIN_YEARS,
        help="Minimum post-purge training span before the first walk-forward "
        f"test year (default: {MIN_TRAIN_YEARS})",
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
    labels_path = interim_dir / "labels.parquet"
    if not labels_path.exists():
        logger.error(
            "missing input: %s — labels (run `sharadar-labels`)", labels_path
        )
        return 2

    con = duckdb.connect()
    try:
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET temp_directory = '{interim_dir / '.duckdb_tmp'}'")
        if args.memory_limit:
            con.execute("SET memory_limit = ?", [args.memory_limit])

        horizons = tuple(dict.fromkeys(sorted(args.horizons)))
        available = {
            row[0]
            for row in con.execute(
                "SELECT name FROM parquet_schema(?)", [str(labels_path)]
            ).fetchall()
        }
        absent = [h for h in horizons if f"delisted_in_window_{h}y" not in available]
        if absent:
            logger.error(
                "labels.parquet has no columns for horizon(s) %s — rerun "
                "`sharadar-labels --horizons %s`",
                " ".join(map(str, absent)),
                " ".join(map(str, horizons)),
            )
            return 2

        create_snapshot_horizon_view(con, labels_path, horizons=horizons)
        build_fold_view(
            con,
            embargo_days=args.embargo_days,
            holdout_years=args.holdout_years,
            min_train_years=args.min_train_years,
        )
        build_tag_view(con)
        build_diag_views(con)
        write_splits_table(con, interim_dir)
        write_folds_table(con, interim_dir)
    finally:
        con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
