"""Convert Nasdaq Data Link zipped-CSV exports to typed, sorted parquet.

DuckDB does the heavy lifting: it streams the CSV, applies the per-table type
overrides from the registry, sorts (spilling to disk when needed), and writes
ZSTD-compressed parquet. The zip is extracted to a temporary directory next to
the output so large tables never round-trip through Python objects.
"""

from __future__ import annotations

import csv
import logging
import tempfile
import zipfile
from pathlib import Path

import duckdb

from .tables import TableSpec

logger = logging.getLogger(__name__)

# Rows the CSV sniffer inspects to infer the types we don't override. Large
# enough to get past any all-null prefix in sparse fundamentals columns.
_SNIFF_SAMPLE_SIZE = 100_000


class ConversionError(RuntimeError):
    """The export archive did not look like a single-CSV Sharadar export."""


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _csv_header(csv_path: Path) -> list[str]:
    with csv_path.open(newline="") as fh:
        return next(csv.reader(fh))


def extract_single_csv(zip_path: Path, target_dir: Path) -> Path:
    """Extract the lone CSV member of a bulk-export zip into `target_dir`."""
    with zipfile.ZipFile(zip_path) as archive:
        members = [m for m in archive.namelist() if m.lower().endswith(".csv")]
        if len(members) != 1:
            raise ConversionError(
                f"{zip_path} should contain exactly one CSV, found {members!r}"
            )
        extracted = Path(archive.extract(members[0], path=target_dir))
    logger.info(
        "extracted %s (%.2f GB uncompressed)",
        extracted.name,
        extracted.stat().st_size / 1e9,
    )
    return extracted


def csv_to_parquet(
    csv_path: Path,
    spec: TableSpec,
    parquet_path: Path,
    *,
    sort: bool = True,
    memory_limit: str | None = None,
) -> int:
    """Write `csv_path` as parquet according to `spec`; return the row count."""
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = parquet_path.with_suffix(".parquet.tmp")

    con = duckdb.connect()
    try:
        # Insertion order is irrelevant (we sort explicitly or not at all) and
        # relaxing it lets DuckDB stream with far less memory.
        con.execute("SET preserve_insertion_order = false")
        con.execute(f"SET temp_directory = {_sql_quote(str(parquet_path.parent / '.duckdb_tmp'))}")
        if memory_limit:
            con.execute(f"SET memory_limit = {_sql_quote(memory_limit)}")

        # Only override types for columns actually present: Sharadar adds and
        # removes columns over time, and DuckDB errors on unknown names.
        header = set(_csv_header(csv_path))
        missing = sorted(set(spec.column_types) - header)
        if missing:
            logger.warning(
                "%s: override columns absent from export, skipping: %s",
                spec.name,
                ", ".join(missing),
            )
        overrides = {
            col: dtype for col, dtype in spec.column_types.items() if col in header
        }
        types_sql = ""
        if overrides:
            pairs = ", ".join(
                f"{_sql_quote(col)}: {_sql_quote(dtype)}"
                for col, dtype in overrides.items()
            )
            types_sql = f", types={{{pairs}}}"
        order_sql = ""
        sort_cols = [c for c in spec.sort_by if c in header]
        if sort and sort_cols:
            order_sql = " ORDER BY " + ", ".join(_sql_ident(c) for c in sort_cols)

        sql = (
            f"COPY (SELECT * FROM read_csv({_sql_quote(str(csv_path))}, "
            f"header=true, sample_size={_SNIFF_SAMPLE_SIZE}{types_sql})"
            f"{order_sql}) TO {_sql_quote(str(tmp_out))} "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        logger.info("converting %s -> %s", csv_path.name, parquet_path)
        rows = con.execute(sql).fetchone()[0]
    finally:
        con.close()

    tmp_out.replace(parquet_path)
    logger.info("wrote %s: %d rows, %.2f GB", parquet_path, rows, parquet_path.stat().st_size / 1e9)
    return int(rows)


def zip_to_parquet(
    zip_path: Path,
    spec: TableSpec,
    parquet_path: Path,
    *,
    sort: bool = True,
    memory_limit: str | None = None,
) -> int:
    """Extract a bulk-export zip and convert it to parquet; return row count.

    The CSV is extracted beside the output file (not the system temp dir) so
    multi-GB tables land on the same filesystem the user pointed data at.
    """
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".extract_{spec.name}_", dir=parquet_path.parent
    ) as tmp_dir:
        csv_path = extract_single_csv(zip_path, Path(tmp_dir))
        return csv_to_parquet(
            csv_path,
            spec,
            parquet_path,
            sort=sort,
            memory_limit=memory_limit,
        )
