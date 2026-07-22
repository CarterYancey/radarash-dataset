"""Inference dataset directory writer: parquet + manifest (ADR 0014).

`data/datasets/inference_{as_of}/` mirrors the training dataset's layout
(docs/dataset.md) minus everything forward-looking: same key + entry
metadata, same feature/rank/sector-rank columns in the same order, but no
label matrix, no split files, no sample weights — there is nothing to
observe forward of the latest price. Directories are immutable like
training dataset versions: an existing one is refused unless forced.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb

from assemble.source import key_meta_columns
from assemble.wide import (
    feature_columns_in_order,
    rank_columns,
    secrank_columns,
)
from features.registry import FEATURES
from identity.source import sql_quote

logger = logging.getLogger(__name__)


def inference_columns(
    con: duckdb.DuckDBPyConnection,
) -> dict[str, tuple[str, ...]]:
    """The final column layout, grouped in output order."""
    return {
        "key_meta": key_meta_columns(con),
        "features": feature_columns_in_order(),
        "ranks": rank_columns(),
        "sector_ranks": secrank_columns(),
    }


def build_inference_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create `inference_wide`: wide_features in the final column order."""
    groups = inference_columns(con)
    select = [c for cols in groups.values() for c in cols]
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW inference_wide AS
        SELECT {", ".join(select)} FROM wide_features
        """
    )


def write_inference_dataset(
    con: duckdb.DuckDBPyConnection,
    *,
    datasets_dir: Path,
    as_of: date,
    inputs: dict[str, Path],
    params: dict[str, int],
    force: bool = False,
) -> Path:
    """Write data/datasets/inference_{as_of}/; return the directory."""
    out_dir = datasets_dir / f"inference_{as_of.isoformat()}"
    if out_dir.exists():
        if not force:
            raise FileExistsError(
                f"{out_dir} already exists — pass --force to rebuild it"
            )
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    dataset_path = out_dir / "dataset.parquet"
    rows = con.execute(
        f"""
        COPY (
            SELECT * FROM inference_wide
            ORDER BY permaticker, snapshot_date, snapshot_kind
        )
        TO {sql_quote(str(dataset_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    ).fetchone()[0]

    permatickers, stale = con.execute(
        f"""
        SELECT count(DISTINCT permaticker),
               count(*) FILTER (snapshot_date < DATE
                   {sql_quote(as_of.isoformat())})
        FROM inference_wide
        """
    ).fetchone()
    input_rows = {
        name: int(
            con.execute(
                f"SELECT count(*) FROM read_parquet({sql_quote(str(path))})"
            ).fetchone()[0]
        )
        for name, path in inputs.items()
    }

    groups = inference_columns(con)
    manifest = {
        "dataset_kind": "inference",
        "as_of": as_of.isoformat(),
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "params": params,
        "rows": int(rows),
        "permatickers": int(permatickers),
        "rows_with_stale_price": int(stale),
        "columns": {group: list(cols) for group, cols in groups.items()},
        "feature_versions": {
            spec.name: {
                "added": spec.added_in_version,
                "removed": spec.removed_in_version,
            }
            for spec in FEATURES
        },
        "input_rows": input_rows,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )

    n_cols = sum(len(cols) for cols in groups.values())
    logger.info(
        "inference_%s: %d rows × %d columns across %d permatickers "
        "(%d with a price older than as-of) -> %s",
        as_of.isoformat(), rows, n_cols, permatickers, stale, out_dir,
    )
    return out_dir
