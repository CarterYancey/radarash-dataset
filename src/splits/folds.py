"""Fold calendar derivation (PLAN.md §7.3, decision 0010).

Calendar-year test periods, `fold` = test start year. Per horizon:

- `holdout` — one fold, test period from Jan 1 of
  (last observable snapshot year − holdout_years + 1), unbounded above.
- `walkforward` — expanding-window folds with test years from
  (first snapshot year + min_train_years + horizon) — so the first fold
  has at least `min_train_years` of post-purge training span — through
  the year before holdout starts (model selection never touches holdout).
  Horizons whose range is empty get no walk-forward folds.
- `cpcv` — reserved (v2), no folds emitted.

All boundaries derive from the data plus the three parameters; nothing is
hardcoded. The manifest written by `write_folds_table` is the frozen fold
definition downstream code must consume.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from identity.source import sql_quote

logger = logging.getLogger(__name__)

EMBARGO_DAYS = 30
HOLDOUT_YEARS = 3
MIN_TRAIN_YEARS = 5

# Holdout test periods are unbounded above: every future snapshot belongs
# to them, none may ever leak into training.
FAR_FUTURE = "DATE '9999-12-31'"


def create_snapshot_horizon_view(
    con: duckdb.DuckDBPyConnection,
    labels_parquet: Path,
    *,
    horizons: tuple[int, ...],
) -> None:
    """Create `snapshot_horizons`: one row per (snapshot, horizon) with the
    per-horizon observability marker (`delisted_in_window_{H}` is NULL iff
    the horizon is not yet observable, docs/labels.md)."""
    selects = []
    for h in horizons:
        tag = f"{int(h)}y"
        selects.append(
            f"""
            SELECT permaticker, snapshot_date, snapshot_kind,
                   {int(h)} AS horizon_years,
                   delisted_in_window_{tag} IS NOT NULL AS observable
            FROM read_parquet({sql_quote(str(labels_parquet))})
            """
        )
    con.execute(
        "CREATE OR REPLACE TEMP VIEW snapshot_horizons AS "
        + " UNION ALL ".join(selects)
    )


def build_fold_view(
    con: duckdb.DuckDBPyConnection,
    *,
    embargo_days: int = EMBARGO_DAYS,
    holdout_years: int = HOLDOUT_YEARS,
    min_train_years: int = MIN_TRAIN_YEARS,
) -> None:
    """Create `split_folds`: (scheme, fold, horizon_years, test_start,
    test_end, embargo_days)."""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW split_folds AS
        WITH bounds AS (
            SELECT horizon_years,
                   min(year(snapshot_date)) AS first_year,
                   max(year(snapshot_date)) FILTER (observable)
                       AS last_observable_year
            FROM snapshot_horizons
            GROUP BY horizon_years
        ),
        holdout AS (
            SELECT 'holdout' AS scheme,
                   last_observable_year - {int(holdout_years) - 1} AS fold,
                   horizon_years
            FROM bounds
            WHERE last_observable_year IS NOT NULL
        ),
        walkforward AS (
            SELECT 'walkforward' AS scheme,
                   unnest(generate_series(
                       b.first_year + {int(min_train_years)} + b.horizon_years,
                       h.fold - 1)) AS fold,
                   b.horizon_years
            FROM bounds b
            JOIN holdout h USING (horizon_years)
        )
        SELECT scheme, fold, horizon_years,
               make_date(fold, 1, 1) AS test_start,
               CASE WHEN scheme = 'holdout' THEN {FAR_FUTURE}
                    ELSE make_date(fold + 1, 1, 1)
               END AS test_end,
               {int(embargo_days)} AS embargo_days
        FROM (SELECT * FROM holdout UNION ALL SELECT * FROM walkforward)
        """
    )


def write_folds_table(
    con: duckdb.DuckDBPyConnection,
    interim_dir: Path,
) -> dict[str, int]:
    """Write split_folds.parquet (the frozen fold manifest, with per-role
    counts); return and log summary counts."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    folds_path = interim_dir / "split_folds.parquet"
    rows = con.execute(
        f"""
        COPY (
            SELECT f.scheme, f.fold, f.horizon_years,
                   f.test_start, f.test_end, f.embargo_days,
                   count(*) FILTER (t.role = 'train') AS n_train,
                   count(*) FILTER (t.role = 'test') AS n_test,
                   count(*) FILTER (t.role = 'purged') AS n_purged,
                   count(*) FILTER (t.role = 'embargoed') AS n_embargoed
            FROM split_folds f
            LEFT JOIN split_tags t USING (scheme, fold, horizon_years)
            GROUP BY ALL
            ORDER BY scheme, horizon_years, fold
        )
        TO {sql_quote(str(folds_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    ).fetchone()[0]

    per_scheme = con.execute(
        """
        SELECT scheme, horizon_years, count(*) AS folds,
               min(fold) AS first_fold, max(fold) AS last_fold
        FROM split_folds
        GROUP BY scheme, horizon_years
        ORDER BY scheme, horizon_years
        """
    ).fetchall()

    counts = {"fold_rows": int(rows)}
    for scheme, horizon_years, folds, first_fold, last_fold in per_scheme:
        counts[f"{scheme}_{horizon_years}y_folds"] = int(folds)
        logger.info(
            "folds %s %dy: %d fold(s), test years %d..%d",
            scheme, horizon_years, folds, first_fold, last_fold,
        )
    logger.info("fold manifest: %d rows -> %s", rows, folds_path)
    return counts
