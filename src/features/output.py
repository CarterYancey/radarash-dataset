"""Family parquet writer: registry-validated, one file per family."""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from identity.source import sql_quote

from .registry import KEY_COLUMNS, family_columns

logger = logging.getLogger(__name__)


def view_name(family: str) -> str:
    return f"features_{family}"


def validate_family_columns(
    con: duckdb.DuckDBPyConnection, family: str
) -> None:
    """Refuse to write a family whose columns drift from the registry."""
    rows = con.execute(f"DESCRIBE {view_name(family)}").fetchall()
    emitted = tuple(row[0] for row in rows)
    expected = KEY_COLUMNS + family_columns(family)
    if emitted != expected:
        missing = [c for c in expected if c not in emitted]
        extra = [c for c in emitted if c not in expected]
        raise ValueError(
            f"family {family!r} does not match the registry: "
            f"missing {missing or 'none'}, unexpected {extra or 'none'} "
            f"(order matters; registry.py and the view must agree)"
        )


def write_family_table(
    con: duckdb.DuckDBPyConnection,
    features_dir: Path,
    family: str,
) -> dict[str, int]:
    """Write data/interim/features/{family}.parquet; return summary counts."""
    validate_family_columns(con, family)
    features_dir.mkdir(parents=True, exist_ok=True)
    out_path = features_dir / f"{family}.parquet"
    rows = con.execute(
        f"""
        COPY (
            SELECT * FROM {view_name(family)}
            ORDER BY permaticker, snapshot_date, snapshot_kind
        )
        TO {sql_quote(str(out_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    ).fetchone()[0]
    permatickers = con.execute(
        f"SELECT count(DISTINCT permaticker) FROM {view_name(family)}"
    ).fetchone()[0]
    counts = {
        f"{family}_rows": int(rows),
        f"{family}_permatickers": int(permatickers),
        f"{family}_columns": len(family_columns(family)),
    }
    logger.info(
        "features/%s: %d rows across %d permatickers (%d feature columns)",
        family,
        counts[f"{family}_rows"],
        counts[f"{family}_permatickers"],
        counts[f"{family}_columns"],
    )
    return counts
