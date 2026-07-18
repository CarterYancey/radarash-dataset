"""Assembly source views: labels + registry-validated family parquets.

Assembly never recomputes fundamentals — it consumes the family parquets
exactly as written (research §F8.2). Reading is therefore paired with the
same registry validation the family writer enforces: a family parquet whose
columns drifted from `features.registry` refuses to assemble.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from features.registry import FAMILIES, KEY_COLUMNS, family_columns
from identity.source import sql_quote
from labels.paths import HORIZON_YEARS

logger = logging.getLogger(__name__)

LABEL_COLUMN_PREFIXES = ("fwd_", "label_", "delisted_in_window_")


def family_view(family: str) -> str:
    return f"feat_{family}"


def create_assembly_source_views(
    con: duckdb.DuckDBPyConnection,
    *,
    labels_parquet: Path,
    features_dir: Path,
) -> None:
    """Create `labels_src` and one `feat_{family}` view per family, with the
    family columns validated against the registry (exact names and order)."""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW labels_src AS
        SELECT * FROM read_parquet({sql_quote(str(labels_parquet))})
        """
    )
    for family in FAMILIES:
        path = features_dir / f"{family}.parquet"
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW {family_view(family)} AS
            SELECT * FROM read_parquet({sql_quote(str(path))})
            """
        )
        emitted = tuple(
            row[0]
            for row in con.execute(f"DESCRIBE {family_view(family)}").fetchall()
        )
        expected = KEY_COLUMNS + family_columns(family)
        if emitted != expected:
            missing = [c for c in expected if c not in emitted]
            extra = [c for c in emitted if c not in expected]
            raise ValueError(
                f"features/{family}.parquet does not match the registry: "
                f"missing {missing or 'none'}, unexpected {extra or 'none'} "
                f"— rerun `sharadar-features` after registry changes"
            )


def labels_columns(con: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    return tuple(row[0] for row in con.execute("DESCRIBE labels_src").fetchall())


def key_meta_columns(con: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    """Snapshot key + entry metadata: everything before the label matrix."""
    return tuple(
        c
        for c in labels_columns(con)
        if not c.startswith(LABEL_COLUMN_PREFIXES)
    )


def label_matrix_columns(con: duckdb.DuckDBPyConnection) -> tuple[str, ...]:
    return tuple(
        c for c in labels_columns(con) if c.startswith(LABEL_COLUMN_PREFIXES)
    )


def available_horizons(con: duckdb.DuckDBPyConnection) -> tuple[int, ...]:
    """Horizons the labels table actually carries, in years."""
    cols = set(labels_columns(con))
    return tuple(
        h for h in HORIZON_YEARS if f"delisted_in_window_{h}y" in cols
    )


def validate_key_alignment(con: duckdb.DuckDBPyConnection) -> int:
    """Every family parquet must cover exactly the labels key set; return the
    row count. A mismatch means the interim artifacts are from different
    builds — refuse to assemble a franken-dataset."""
    n_labels = con.execute("SELECT count(*) FROM labels_src").fetchone()[0]
    for family in FAMILIES:
        n_family, n_joined = con.execute(
            f"""
            SELECT
                (SELECT count(*) FROM {family_view(family)}),
                (SELECT count(*)
                 FROM labels_src l
                 JOIN {family_view(family)} f USING (permaticker, snapshot_date, snapshot_kind))
            """
        ).fetchone()
        if not (n_labels == n_family == n_joined):
            raise ValueError(
                f"features/{family}.parquet is misaligned with labels.parquet "
                f"(labels {n_labels}, family {n_family}, joined {n_joined}) "
                f"— rebuild with `sharadar-features` on the current labels"
            )
    return int(n_labels)
