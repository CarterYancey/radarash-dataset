"""CLI: data-gated QA reports for the feature-research phase.

    sharadar-qa coverage           # features.md §F9 coverage/null-rate report
    sharadar-qa staleness          # §F4.4 staleness × label-bias report
    sharadar-qa daily-pit          # V7: is DAILY point-in-time safe?
    sharadar-qa splits-diag        # PLAN §7.7 split-overlap diagnostics

Each subcommand reads `data/raw` + `data/interim`, writes machine-readable
detail under `data/interim/qa/`, and drops a committable markdown report
(plus its CSV tables) under `--report-dir` (default `docs/research/reports/`)
— push those to share run results.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import duckdb

from .coverage import (
    build_coverage_views,
    build_snapshot_latest_view,
    coverage_report_sections,
)
from .daily_pit import (
    DEFAULT_SAMPLE_TICKERS,
    build_daily_pit_views,
    daily_pit_report_sections,
)
from .report import write_report, write_view_tables
from .source import create_qa_source_views, detect_key_fields, parquet_columns
from .splits_diag import (
    DEFAULT_EMBARGO_DAYS,
    DEFAULT_TWIN_SAMPLE,
    build_feature_variance_views,
    build_label_structure_views,
    build_purge_cost_view,
    build_twin_views,
    create_splits_source_views,
    default_test_starts,
    required_families,
    splits_diag_report_sections,
)
from .staleness import build_staleness_views, staleness_report_sections

logger = logging.getLogger(__name__)

_HINTS = {
    "SF1": "run `sharadar-ingest --tables SF1`",
    "SEP": "run `sharadar-ingest --tables SEP`",
    "DAILY": "run `sharadar-ingest --tables DAILY`",
    "mapping": "run `sharadar-identity`",
    "universe": "run `sharadar-identity`",
    "snapshots": "run `sharadar-labels`",
    "labels": "run `sharadar-labels`",
    "features": "run `sharadar-features`",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sharadar-qa",
        description="Data-gated QA reports (coverage, staleness, DAILY PIT, "
        "splits diagnostics).",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("coverage", "per-year/sector fundamentals coverage, depth-tier survival, null rates"),
        ("staleness", "fundamentals staleness buckets vs. 1y label outcomes"),
        ("daily-pit", "V7: check whether DAILY historical rows are point-in-time safe"),
        ("splits-diag", "PLAN §7.7: intra-quarter variance, label overlap, twin test, purge cost"),
    ):
        cmd = sub.add_parser(name, help=help_text)
        cmd.add_argument(
            "--data-dir",
            type=Path,
            default=Path("data"),
            help="Root data directory (default: ./data)",
        )
        cmd.add_argument(
            "--report-dir",
            type=Path,
            default=Path("docs/research/reports"),
            help="Where the committable markdown/CSV report lands "
            "(default: docs/research/reports)",
        )
        cmd.add_argument(
            "--memory-limit",
            default=None,
            help="DuckDB memory limit, e.g. '8GB' (default: DuckDB's default)",
        )
        if name == "coverage":
            cmd.add_argument(
                "--no-prices",
                action="store_true",
                help="Skip the SEP-based P12/P36 price-window coverage",
            )
        if name == "daily-pit":
            cmd.add_argument(
                "--sample-tickers",
                type=int,
                default=DEFAULT_SAMPLE_TICKERS,
                help=f"Deterministic ticker sample size (default: {DEFAULT_SAMPLE_TICKERS})",
            )
        if name == "splits-diag":
            cmd.add_argument(
                "--embargo-days",
                type=int,
                default=DEFAULT_EMBARGO_DAYS,
                help="Embargo added to the horizon in the purge-cost table "
                f"(default: {DEFAULT_EMBARGO_DAYS})",
            )
            cmd.add_argument(
                "--test-starts",
                default=None,
                help="Comma-separated test-boundary dates (YYYY-MM-DD) for "
                "the purge-cost table (default: yearly Jan 1 boundaries "
                "derived from the snapshot span)",
            )
            cmd.add_argument(
                "--twin-sample",
                type=int,
                default=DEFAULT_TWIN_SAMPLE,
                help="Deterministic row sample size for the twin test "
                f"(default: {DEFAULT_TWIN_SAMPLE})",
            )
    return parser


def _missing_inputs(inputs: dict[str, Path]) -> bool:
    missing = [
        f"{path} — {_HINTS[hint]}" for hint, path in inputs.items() if not path.exists()
    ]
    for line in missing:
        logger.error("missing input: %s", line)
    return bool(missing)


def _connect(interim_dir: Path, memory_limit: str | None) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("SET preserve_insertion_order = false")
    interim_dir.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory = '{interim_dir / '.duckdb_tmp'}'")
    if memory_limit:
        con.execute("SET memory_limit = ?", [memory_limit])
    return con


def run_coverage(args: argparse.Namespace) -> int:
    raw, interim = args.data_dir / "raw", args.data_dir / "interim"
    inputs = {
        "SF1": raw / "SF1.parquet",
        "mapping": interim / "ticker_permaticker.parquet",
        "universe": interim / "universe.parquet",
        "snapshots": interim / "snapshots.parquet",
    }
    with_prices = not args.no_prices
    if with_prices:
        inputs["SEP"] = raw / "SEP.parquet"
    if _missing_inputs(inputs):
        return 2

    con = _connect(interim, args.memory_limit)
    try:
        fields = detect_key_fields(con, inputs["SF1"])
        create_qa_source_views(
            con,
            sf1_parquet=inputs["SF1"],
            mapping_parquet=inputs["mapping"],
            universe_parquet=inputs["universe"],
            snapshots_parquet=inputs["snapshots"],
            fields=fields,
            sep_parquet=inputs.get("SEP"),
        )
        build_coverage_views(con, fields=fields, with_prices=with_prices)

        qa_dir = interim / "qa"
        write_view_tables(con, "snapshot_coverage", "snapshot_coverage", qa_dir)
        for view in (
            "coverage_by_year",
            "coverage_by_sector",
            "null_rates_by_year",
            "null_rates_by_sector",
        ):
            write_view_tables(con, view, view, qa_dir, csv_dir=args.report_dir)
        write_report(
            args.report_dir / "coverage.md",
            coverage_report_sections(con, with_prices=with_prices),
        )
    finally:
        con.close()
    return 0


def run_staleness(args: argparse.Namespace) -> int:
    raw, interim = args.data_dir / "raw", args.data_dir / "interim"
    inputs = {
        "SF1": raw / "SF1.parquet",
        "mapping": interim / "ticker_permaticker.parquet",
        "universe": interim / "universe.parquet",
        "snapshots": interim / "snapshots.parquet",
        "labels": interim / "labels.parquet",
    }
    if _missing_inputs(inputs):
        return 2

    con = _connect(interim, args.memory_limit)
    try:
        create_qa_source_views(
            con,
            sf1_parquet=inputs["SF1"],
            mapping_parquet=inputs["mapping"],
            universe_parquet=inputs["universe"],
            snapshots_parquet=inputs["snapshots"],
            fields=[],
            labels_parquet=inputs["labels"],
        )
        build_snapshot_latest_view(con, fields=[])
        build_staleness_views(con)

        qa_dir = interim / "qa"
        for view in ("staleness_by_bucket", "staleness_by_year"):
            write_view_tables(con, view, view, qa_dir, csv_dir=args.report_dir)
        write_report(
            args.report_dir / "staleness.md", staleness_report_sections(con)
        )
    finally:
        con.close()
    return 0


def run_daily_pit(args: argparse.Namespace) -> int:
    raw = args.data_dir / "raw"
    inputs = {
        "DAILY": raw / "DAILY.parquet",
        "SEP": raw / "SEP.parquet",
        "SF1": raw / "SF1.parquet",
    }
    if _missing_inputs(inputs):
        return 2

    con = _connect(args.data_dir / "interim", args.memory_limit)
    try:
        sf1_cols = parquet_columns(con, inputs["SF1"])
        required = {"dimension", "datekey", "sharesbas", "equity"}
        if not required <= sf1_cols:
            logger.error(
                "SF1 export lacks columns needed for the PIT check: %s",
                ", ".join(sorted(required - sf1_cols)),
            )
            return 2

        build_daily_pit_views(
            con,
            daily_parquet=inputs["DAILY"],
            sep_parquet=inputs["SEP"],
            sf1_parquet=inputs["SF1"],
            has_sharefactor="sharefactor" in sf1_cols,
            sample_tickers=args.sample_tickers,
        )
        qa_dir = args.data_dir / "interim" / "qa"
        for view in ("daily_freshness", "pit_marketcap_by_year", "pit_pb_check"):
            write_view_tables(con, view, view, qa_dir, csv_dir=args.report_dir)
        write_report(
            args.report_dir / "daily_pit.md", daily_pit_report_sections(con)
        )
    finally:
        con.close()
    return 0


def run_splits_diag(args: argparse.Namespace) -> int:
    from datetime import date

    interim = args.data_dir / "interim"
    inputs = {
        "snapshots": interim / "snapshots.parquet",
        "labels": interim / "labels.parquet",
    }
    features_dir = interim / "features"
    missing = _missing_inputs(inputs)
    for family in required_families():
        path = features_dir / f"{family}.parquet"
        if not path.exists():
            logger.error("missing input: %s — %s", path, _HINTS["features"])
            missing = True
    if missing:
        return 2

    con = _connect(interim, args.memory_limit)
    try:
        create_splits_source_views(
            con,
            snapshots_parquet=inputs["snapshots"],
            labels_parquet=inputs["labels"],
            features_dir=features_dir,
        )
        build_feature_variance_views(con)
        build_label_structure_views(con)
        build_twin_views(con, sample_size=args.twin_sample)
        if args.test_starts:
            test_starts = [
                date.fromisoformat(part.strip())
                for part in args.test_starts.split(",")
                if part.strip()
            ]
        else:
            test_starts = default_test_starts(con)
        if not test_starts:
            logger.error("no snapshot dates to derive purge-cost boundaries from")
            return 2
        build_purge_cost_view(
            con, test_starts=test_starts, embargo_days=args.embargo_days
        )

        qa_dir = interim / "qa"
        write_view_tables(con, "twin_pairs", "twin_pairs", qa_dir)
        for view in (
            "feature_intraquarter",
            "filing_straddle",
            "label_kind_flip",
            "label_variance_decomposition",
            "label_serial_correlation",
            "twin_relations",
            "twin_label_corr",
            "purge_cost",
        ):
            write_view_tables(con, view, view, qa_dir, csv_dir=args.report_dir)
        write_report(
            args.report_dir / "splits_diag.md", splits_diag_report_sections(con)
        )
    finally:
        con.close()
    return 0


_COMMANDS = {
    "coverage": run_coverage,
    "staleness": run_staleness,
    "daily-pit": run_daily_pit,
    "splits-diag": run_splits_diag,
}


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = build_parser().parse_args(argv)
    return _COMMANDS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
