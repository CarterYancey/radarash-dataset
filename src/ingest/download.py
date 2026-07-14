"""Orchestration for immutable raw-table ingestion."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from .convert import ParquetStats, zip_to_parquet
from .nasdaq import download_export, wait_for_export
from .tables import TableSpec


def _write_json_atomic(path: Path, value: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    with temporary.open("w", encoding="utf-8") as output:
        json.dump(value, output, indent=2)
        output.write("\n")
    os.replace(temporary, path)


def _existing_stats(path: Path) -> ParquetStats:
    quoted = "'" + str(path).replace("'", "''") + "'"
    connection = duckdb.connect()
    try:
        rows = int(connection.execute(f"SELECT count(*) FROM read_parquet({quoted})").fetchone()[0])
        columns = tuple(
            row[0] for row in connection.execute(f"DESCRIBE SELECT * FROM read_parquet({quoted})").fetchall()
        )
        return ParquetStats(rows, path.stat().st_size, columns)
    finally:
        connection.close()


def ingest_table(
    spec: TableSpec,
    output_dir: Path,
    api_key: str,
    *,
    force: bool = False,
    poll_seconds: float = 30,
    timeout_seconds: float = 7200,
) -> tuple[Path, ParquetStats, bool]:
    """Download and atomically convert one table; preserve existing raw data by default."""
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = output_dir / f"{spec.name}.parquet"
    if parquet_path.exists() and not force:
        return parquet_path, _existing_stats(parquet_path), False

    info = wait_for_export(
        spec.code,
        api_key,
        poll_seconds=poll_seconds,
        timeout_seconds=timeout_seconds,
    )
    with tempfile.TemporaryDirectory(prefix=f"sharadar-{spec.name.lower()}-", dir=output_dir) as directory:
        zip_path = Path(directory) / f"{spec.name}.zip"
        digest = download_export(info, zip_path)
        stats = zip_to_parquet(zip_path, parquet_path, spec.sort_by)

    _write_json_atomic(
        output_dir / f"{spec.name}.meta.json",
        {
            "table": spec.code,
            "description": spec.description,
            "rows": stats.rows,
            "columns": list(stats.columns),
            "parquet_bytes": stats.bytes,
            "sorted_by": list(spec.sort_by),
            "zip_sha256": digest,
            "source_status": info.status,
            "source_data_snapshot_time": info.data_snapshot_time,
            "source_last_refreshed_time": info.last_refreshed_time,
            "ingested_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        },
    )
    return parquet_path, stats, True
