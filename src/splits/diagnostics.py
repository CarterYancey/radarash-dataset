"""Diagnostic-only schemes (PLAN.md §7.3 items 4-5, decisions 0010/0011).

`entity_holdout` (fixed ticker set held out across all time) and
`random_kfold` (uniform row partition, deliberately leaky) exist to be
measured against, never to measure with: they power the §7.7 leakage-gap
experiment in `value-ml-models` and are forbidden for model selection or
reported performance. Mechanics (decision 0011 §7):

- Buckets come from DuckDB's deterministic `hash()` — `hash(permaticker)`
  for entities, `hash(permaticker, snapshot_date, snapshot_kind)` for rows
  — modulo `DIAG_BUCKETS`.
- Roles are train/test only; nothing is purged or embargoed (for
  `random_kfold`, being leaky is the point). Test rows follow the same
  conventions as the temporal schemes (median kind, observable label) so
  scheme-to-scheme score gaps are attributable to the split, not the
  evaluation.
- Both schemes cover only the pre-holdout region per horizon
  (`snapshot_date < holdout test_start`): the sealed temporal holdout is
  not consumed by the experiment, even as training data.
"""

from __future__ import annotations

import duckdb

DIAG_BUCKETS = 5
ENTITY_TEST_BUCKET = 0


def build_diag_views(
    con: duckdb.DuckDBPyConnection,
    *,
    buckets: int = DIAG_BUCKETS,
) -> None:
    """Create `diag_tags` and `diag_folds` (same shapes as `split_tags` /
    `split_folds`, with NULL temporal boundaries). Requires the
    `snapshot_horizons` and `split_folds` views."""
    buckets = int(buckets)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW diag_tags AS
        WITH holdout_bounds AS (
            SELECT horizon_years, test_start AS holdout_start
            FROM split_folds
            WHERE scheme = 'holdout'
        ),
        pre_holdout AS (
            SELECT s.permaticker, s.snapshot_date, s.snapshot_kind,
                   s.horizon_years, s.observable,
                   hash(s.permaticker) % {buckets} AS entity_bucket,
                   hash(s.permaticker, s.snapshot_date, s.snapshot_kind)
                       % {buckets} AS row_bucket
            FROM snapshot_horizons s
            JOIN holdout_bounds b USING (horizon_years)
            WHERE s.snapshot_date < b.holdout_start
        ),
        entity AS (
            SELECT 'entity_holdout' AS scheme,
                   {ENTITY_TEST_BUCKET} AS fold,
                   horizon_years, permaticker, snapshot_date, snapshot_kind,
                   CASE WHEN entity_bucket <> {ENTITY_TEST_BUCKET} THEN 'train'
                        WHEN snapshot_kind = 'median' AND observable THEN 'test'
                   END AS role
            FROM pre_holdout
        ),
        kfolds AS (
            SELECT unnest(generate_series(0, {buckets - 1})) AS fold
        ),
        random_kfold AS (
            SELECT 'random_kfold' AS scheme, f.fold,
                   p.horizon_years, p.permaticker, p.snapshot_date,
                   p.snapshot_kind,
                   CASE WHEN p.row_bucket <> f.fold THEN 'train'
                        WHEN p.snapshot_kind = 'median' AND p.observable
                            THEN 'test'
                   END AS role
            FROM pre_holdout p
            CROSS JOIN kfolds f
        )
        SELECT scheme, fold, horizon_years,
               permaticker, snapshot_date, snapshot_kind, role
        FROM (SELECT * FROM entity UNION ALL SELECT * FROM random_kfold)
        WHERE role IS NOT NULL
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW diag_folds AS
        WITH horizons AS (
            SELECT horizon_years FROM split_folds WHERE scheme = 'holdout'
        ),
        folds AS (
            SELECT 'entity_holdout' AS scheme, {ENTITY_TEST_BUCKET} AS fold
            UNION ALL
            SELECT 'random_kfold', unnest(generate_series(0, {buckets - 1}))
        )
        SELECT f.scheme, f.fold, h.horizon_years,
               CAST(NULL AS DATE) AS test_start,
               CAST(NULL AS DATE) AS test_end,
               CAST(NULL AS INTEGER) AS embargo_days
        FROM folds f
        CROSS JOIN horizons h
        """
    )
