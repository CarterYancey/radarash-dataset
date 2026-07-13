"""Small shared helpers: materialize views, render markdown report tables."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from identity.source import sql_quote

logger = logging.getLogger(__name__)


def write_view_tables(
    con: duckdb.DuckDBPyConnection,
    view: str,
    name: str,
    parquet_dir: Path,
    *,
    csv_dir: Path | None = None,
) -> int:
    """COPY a view to `{parquet_dir}/{name}.parquet`, plus a committable
    `{csv_dir}/{name}.csv` when `csv_dir` is given; return the row count."""
    parquet_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = parquet_dir / f"{name}.parquet"
    rows = con.execute(
        f"""
        COPY (SELECT * FROM {view})
        TO {sql_quote(str(parquet_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    ).fetchone()[0]
    if csv_dir is not None:
        csv_dir.mkdir(parents=True, exist_ok=True)
        con.execute(
            f"""
            COPY (SELECT * FROM {view})
            TO {sql_quote(str(csv_dir / f'{name}.csv'))} (FORMAT CSV, HEADER)
            """
        )
    logger.info("%s: %d rows -> %s", name, rows, parquet_path)
    return int(rows)


def _fmt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4f}".rstrip("0").rstrip(".") or "0"
    return str(value)


def md_table(con: duckdb.DuckDBPyConnection, sql: str) -> str:
    """Run `sql` and render the result as a GitHub-markdown table."""
    cursor = con.execute(sql)
    headers = [d[0] for d in cursor.description]
    rows = cursor.fetchall()
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    lines.extend("| " + " | ".join(_fmt(v) for v in row) + " |" for row in rows)
    return "\n".join(lines)


def write_report(report_path: Path, sections: list[str]) -> Path:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n\n".join(sections).strip() + "\n")
    logger.info("report -> %s", report_path)
    return report_path
