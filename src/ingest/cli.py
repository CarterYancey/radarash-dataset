"""CLI for Sharadar ingestion."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .convert import zip_to_parquet
from .download import ingest_table
from .tables import TABLES, table_spec


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download Sharadar bulk tables as Parquet")
    commands = parser.add_subparsers(dest="command", required=True)
    download = commands.add_parser("download", help="download and ingest bulk tables")
    download.add_argument("tables", nargs="*", default=list(TABLES), metavar="TABLE")
    download.add_argument("--output-dir", type=Path, default=Path("data/raw"))
    download.add_argument("--api-key", default=os.environ.get("NASDAQ_DATA_LINK_API_KEY"))
    download.add_argument("--force", action="store_true", help="replace existing raw Parquet")
    download.add_argument("--poll-seconds", type=float, default=30)
    download.add_argument("--timeout-seconds", type=float, default=7200)
    convert = commands.add_parser("convert", help="convert an existing Nasdaq ZIP")
    convert.add_argument("table")
    convert.add_argument("zip_path", type=Path)
    convert.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "convert":
        spec = table_spec(args.table)
        output = args.output or Path("data/raw") / f"{spec.name}.parquet"
        stats = zip_to_parquet(args.zip_path, output, spec.sort_by)
        print(f"wrote {output} ({stats.rows:,} rows, {stats.bytes:,} bytes)")
        return 0
    if not args.api_key:
        raise SystemExit("Set NASDAQ_DATA_LINK_API_KEY or pass --api-key")
    for name in args.tables:
        spec = table_spec(name)
        path, stats, changed = ingest_table(
            spec,
            args.output_dir,
            args.api_key,
            force=args.force,
            poll_seconds=args.poll_seconds,
            timeout_seconds=args.timeout_seconds,
        )
        print(f"{'wrote' if changed else 'kept'} {path} ({stats.rows:,} rows, {stats.bytes:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
