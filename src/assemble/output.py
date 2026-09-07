"""Versioned dataset directory writer: parquet + splits + manifest.

`data/datasets/dataset_vX.Y/` is immutable once written (README): the
writer refuses to touch an existing directory unless forced. Column layout
(canonical doc: docs/dataset.md): snapshot key + entry metadata, features
in registry order (assembly-stage composites in place), rank columns,
sector-rank columns, the label matrix, then `sample_weight_{H}y` — with
weights NULLed wherever the horizon's label is unobservable (decision
0012 §4).

After the parquet is written, the rank columns are audited for calendar-
quarter keys (decision 0016, `audit.py`); the audit table ships as
`rank_audit.parquet` and is summarised in the manifest. A failing audit
removes the directory and raises, unless the caller allows the keys.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from features.registry import FEATURES
from identity.source import sql_quote

from .audit import (
    MAX_KEY_SHARE,
    build_rank_audit_table,
    describe_flagged,
    flagged_detail,
    rank_audit_summary,
    rank_key_error,
    write_rank_audit,
)
from .source import key_meta_columns, label_matrix_columns
from .wide import (
    feature_columns_in_order,
    rank_columns,
    rank_policy,
    secrank_columns,
)

logger = logging.getLogger(__name__)


def dataset_columns(
    con: duckdb.DuckDBPyConnection, horizons: tuple[int, ...]
) -> dict[str, tuple[str, ...]]:
    """The final column layout, grouped in output order."""
    return {
        "key_meta": key_meta_columns(con),
        "features": feature_columns_in_order(),
        "ranks": rank_columns(),
        "sector_ranks": secrank_columns(),
        "labels": label_matrix_columns(con),
        "sample_weights": tuple(f"sample_weight_{h}y" for h in horizons),
    }


def build_dataset_view(
    con: duckdb.DuckDBPyConnection, *, horizons: tuple[int, ...]
) -> None:
    """Create `dataset_wide`: wide_features ⋈ weights, final column order."""
    groups = dataset_columns(con, horizons)
    select = [f"f.{c}" for c in groups["key_meta"]]
    select += [
        f"f.{c}"
        for c in groups["features"] + groups["ranks"] + groups["sector_ranks"]
    ]
    select += [f"f.{c}" for c in groups["labels"]]
    select += [
        f"CASE WHEN f.delisted_in_window_{h}y IS NOT NULL "
        f"THEN w.sample_weight_{h}y END AS sample_weight_{h}y"
        for h in horizons
    ]
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW dataset_wide AS
        SELECT {", ".join(select)}
        FROM wide_features f
        JOIN sample_weights_wide w
          USING (permaticker, snapshot_date, snapshot_kind)
        """
    )


def write_dataset(
    con: duckdb.DuckDBPyConnection,
    *,
    datasets_dir: Path,
    version: str,
    horizons: tuple[int, ...],
    splits_parquet: Path,
    folds_parquet: Path,
    inputs: dict[str, Path],
    params: dict[str, object],
    force: bool = False,
    max_key_share: float = MAX_KEY_SHARE,
    allow_rank_keys: bool = False,
    audit_keep_dir: Path | None = None,
) -> Path:
    """Write data/datasets/dataset_v{version}/; return the directory.

    Raises ValueError (after removing the directory) when a rank column
    fails the quarter-key audit and `allow_rank_keys` is False; the audit
    table is then kept as `{audit_keep_dir}/rank_audit_v{version}.{parquet,
    csv}` (when given) so the failure can be inspected without a rebuild."""
    out_dir = datasets_dir / f"dataset_v{version}"
    if out_dir.exists():
        if not force:
            raise FileExistsError(
                f"{out_dir} already exists — dataset versions are immutable; "
                f"bump --dataset-version or pass --force to rebuild it"
            )
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)

    dataset_path = out_dir / "dataset.parquet"
    rows = con.execute(
        f"""
        COPY (
            SELECT * FROM dataset_wide
            ORDER BY permaticker, snapshot_date, snapshot_kind
        )
        TO {sql_quote(str(dataset_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    ).fetchone()[0]
    for src in (splits_parquet, folds_parquet):
        shutil.copy2(src, out_dir / src.name)

    # Decision 0016: no rank column may identify the calendar quarter.
    build_rank_audit_table(
        con,
        dataset_parquet=dataset_path,
        columns=rank_columns() + secrank_columns(),
    )
    write_rank_audit(con, out_dir / "rank_audit.parquet")
    audit = rank_audit_summary(con, max_key_share=max_key_share)
    detail = flagged_detail(con, max_key_share=max_key_share)
    if detail:
        for line in describe_flagged(detail):
            logger.warning("rank audit: %s", line)
        if not allow_rank_keys:
            if audit_keep_dir is not None:
                for suffix in (".parquet", ".csv"):
                    kept = audit_keep_dir / f"rank_audit_v{version}{suffix}"
                    write_rank_audit(con, kept)
                    logger.error("rank audit table kept at %s", kept)
            shutil.rmtree(out_dir)
            raise ValueError(rank_key_error(detail, max_key_share=max_key_share))
        logger.warning(
            "rank audit: %d keyed rank column(s) published under "
            "--allow-rank-keys; see manifest.json['rank_audit']['flagged']",
            len(audit["flagged"]),
        )
    else:
        logger.info(
            "rank audit: %d rank columns, none exceed quarter-key share %.3f",
            len(audit["columns"]), max_key_share,
        )

    permatickers = con.execute(
        "SELECT count(DISTINCT permaticker) FROM dataset_wide"
    ).fetchone()[0]
    # PLAN §7.2: summed uniqueness weights = honest effective sample size.
    effective = {
        f"{h}y": con.execute(
            f"SELECT round(sum(sample_weight_{h}y), 2) FROM dataset_wide"
        ).fetchone()[0]
        for h in horizons
    }
    input_rows = {
        name: int(
            con.execute(
                f"SELECT count(*) FROM read_parquet({sql_quote(str(path))})"
            ).fetchone()[0]
        )
        for name, path in inputs.items()
    }

    groups = dataset_columns(con, horizons)
    manifest = {
        "dataset_version": version,
        "created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "horizons_years": list(horizons),
        "params": {**params, "allow_rank_keys": bool(allow_rank_keys)},
        "rows": int(rows),
        "permatickers": int(permatickers),
        "effective_rows": effective,
        "columns": {group: list(cols) for group, cols in groups.items()},
        "rank_policy": rank_policy(),
        "rank_audit": audit,
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
        "dataset_v%s: %d rows × %d columns across %d permatickers -> %s",
        version, rows, n_cols, permatickers, out_dir,
    )
    for h in horizons:
        logger.info(
            "dataset_v%s: %sy effective sample size (Σ sample_weight) = %s",
            version, h, effective[f"{h}y"],
        )
    return out_dir
