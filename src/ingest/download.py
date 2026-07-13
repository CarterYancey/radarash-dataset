"""CLI: bulk-download Sharadar tables and store them as parquet.

Usage (via the console script installed by this package):

    sharadar-ingest                     # all tables, into ./data
    sharadar-ingest --tables SEP SF1    # a subset
    sharadar-ingest --force             # re-download tables that already exist

Requires NASDAQ_DATA_LINK_API_KEY in the environment (or --api-key).

Each table produces:

    data/raw/<TABLE>.parquet        the raw table, typed and sorted
    data/raw/<TABLE>.meta.json      provenance: source refresh time, row
                                    count, zip sha256, ingestion timestamp

Downloads are staged under data/raw/.staging/ and removed on success unless
--keep-zip is given.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import logging
import os
import sys
from pathlib import Path

from .convert import zip_to_parquet
from .nasdaq import API_KEY_ENV_VAR, BulkExportClient
from .tables import TableSpec, resolve_tables

logger = logging.getLogger(__name__)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def ingest_table(
    client: BulkExportClient,
    spec: TableSpec,
    raw_dir: Path,
    *,
    keep_zip: bool = False,
    sort: bool = True,
    memory_limit: str | None = None,
) -> dict:
    """Download one table, convert it to parquet, and write its metadata."""
    status = client.wait_until_fresh(spec.qualified_name)
    zip_path = raw_dir / ".staging" / f"{spec.name}.zip"
    client.download(status.link, zip_path)
    zip_sha256 = _sha256(zip_path)

    parquet_path = raw_dir / f"{spec.name}.parquet"
    rows = zip_to_parquet(
        zip_path, spec, parquet_path, sort=sort, memory_limit=memory_limit
    )

    meta = {
        "table": spec.qualified_name,
        "description": spec.description,
        "rows": rows,
        "parquet_bytes": parquet_path.stat().st_size,
        "sorted_by": list(spec.sort_by) if sort else [],
        "zip_sha256": zip_sha256,
        "source_status": status.status,
        "source_data_snapshot_time": status.data_snapshot_time,
        "source_last_refreshed_time": status.last_refreshed_time,
        "ingested_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
    }
    meta_path = raw_dir / f"{spec.name}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2) + "\n")

    if not keep_zip:
        zip_path.unlink()
    return meta


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sharadar-ingest",
        description="Bulk-download Sharadar tables from Nasdaq Data Link into data/raw/*.parquet.",
    )
    parser.add_argument(
        "--tables",
        nargs="+",
        metavar="TABLE",
        help="Tables to ingest (default: all). E.g. --tables TICKERS SEP",
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data"),
        help="Root data directory (default: ./data)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help=f"Nasdaq Data Link API key (default: ${API_KEY_ENV_VAR})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download tables whose parquet already exists",
    )
    parser.add_argument(
        "--keep-zip",
        action="store_true",
        help="Keep the downloaded zip in data/raw/.staging/ after conversion",
    )
    parser.add_argument(
        "--no-sort",
        action="store_true",
        help="Skip sorting parquet output (faster, less memory, worse pruning)",
    )
    parser.add_argument(
        "--memory-limit",
        default=None,
        help="DuckDB memory limit for conversion, e.g. '8GB' (default: DuckDB's)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=30.0,
        help="Seconds between export-status polls (default: 30)",
    )
    parser.add_argument(
        "--poll-timeout",
        type=float,
        default=3600.0,
        help="Max seconds to wait for a fresh export (default: 3600)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = build_parser().parse_args(argv)

    try:
        specs = resolve_tables(args.tables)
    except KeyError as exc:
        logger.error("%s", exc.args[0])
        return 2

    api_key = args.api_key or os.environ.get(API_KEY_ENV_VAR, "")
    if not api_key:
        logger.error(
            "no API key: pass --api-key or set %s", API_KEY_ENV_VAR
        )
        return 2

    client = BulkExportClient(
        api_key,
        poll_interval=args.poll_interval,
        poll_timeout=args.poll_timeout,
    )
    raw_dir = args.data_dir / "raw"

    failures: list[str] = []
    for spec in specs:
        parquet_path = raw_dir / f"{spec.name}.parquet"
        if parquet_path.exists() and not args.force:
            logger.info("%s: %s exists, skipping (use --force to redo)", spec.name, parquet_path)
            continue
        logger.info("=== ingesting %s: %s", spec.qualified_name, spec.description)
        try:
            meta = ingest_table(
                client,
                spec,
                raw_dir,
                keep_zip=args.keep_zip,
                sort=not args.no_sort,
                memory_limit=args.memory_limit,
            )
        except Exception:
            logger.exception("%s: ingestion failed", spec.name)
            failures.append(spec.name)
            continue
        logger.info("%s: done (%d rows)", spec.name, meta["rows"])

    if failures:
        logger.error("failed tables: %s", ", ".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
