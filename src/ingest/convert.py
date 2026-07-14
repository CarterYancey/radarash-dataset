"""Convert Nasdaq bulk ZIP/CSV exports into query-ready Parquet."""

from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import duckdb


@dataclass(frozen=True)
class ParquetStats:
    rows: int
    bytes: int
    columns: tuple[str, ...]


def _string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def csv_to_parquet(csv_path: Path, output_path: Path, sort_by: tuple[str, ...] = ()) -> ParquetStats:
    """Infer the full CSV schema and atomically write validated Parquet."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_name(f".{output_path.name}.tmp")
    temporary.unlink(missing_ok=True)
    connection = duckdb.connect()
    try:
        connection.execute(
            "CREATE TEMP TABLE source AS SELECT * FROM read_csv("
            f"{_string(str(csv_path))}, header=true, sample_size=-1, "
            "nullstr=['', 'NA', 'N/A', 'NULL'], ignore_errors=false)"
        )
        columns = tuple(row[1] for row in connection.execute("PRAGMA table_info('source')").fetchall())
        missing = set(sort_by).difference(columns)
        if missing:
            raise ValueError(f"Sort columns missing from export: {sorted(missing)}")
        order = ""
        if sort_by:
            order = " ORDER BY " + ", ".join(_identifier(column) for column in sort_by)
        connection.execute(
            f"COPY (SELECT * FROM source{order}) TO {_string(str(temporary))} "
            "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 100000)"
        )
        rows = int(connection.execute("SELECT count(*) FROM source").fetchone()[0])
        written = int(
            connection.execute(f"SELECT count(*) FROM read_parquet({_string(str(temporary))})").fetchone()[0]
        )
        if rows != written:
            raise RuntimeError(f"Parquet validation failed: wrote {written} of {rows} rows")
        os.replace(temporary, output_path)
        return ParquetStats(rows, output_path.stat().st_size, columns)
    finally:
        connection.close()
        temporary.unlink(missing_ok=True)


def zip_to_parquet(zip_path: Path, output_path: Path, sort_by: tuple[str, ...] = ()) -> ParquetStats:
    with zipfile.ZipFile(zip_path) as archive:
        members = [
            item for item in archive.infolist()
            if not item.is_dir() and item.filename.lower().endswith(".csv")
        ]
        if len(members) != 1:
            raise ValueError(f"Expected exactly one CSV in {zip_path}, found {len(members)}")
        member = members[0]
        if Path(member.filename).name != member.filename:
            raise ValueError(f"Unsafe archive member path: {member.filename!r}")
        with tempfile.TemporaryDirectory(prefix="sharadar-csv-") as directory:
            archive.extract(member, directory)
            return csv_to_parquet(Path(directory) / member.filename, output_path, sort_by)
