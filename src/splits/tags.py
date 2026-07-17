"""Role assignment per (scheme, fold, horizon) (PLAN.md §7.2, decision 0011).

For a fold with test period [test_start, test_end), horizon H and embargo E:

- `train`     — snapshot_date + H + E < test_start (PLAN §7.2's full
                eligibility condition). All three snapshot kinds.
- `embargoed` — fails only the embargo: the label window ends before
                test_start but within E days of it.
- `purged`    — snapshot_date < test_start and the label window reaches the
                test period (snapshot_date + H >= test_start).
- `test`      — snapshot_date inside the test period, median kind ONLY
                (low/high are training-only, PLAN §4), horizon observable.

Rows matching none of these (post-test rows, low/high kinds inside the test
window, unobservable rows in the test window) carry no tag for that fold:
absence means out of fold. Nominal `snapshot_date + H` bounds the label
information from above — the terminal averaging window is trailing and the
horizon end never lands after the nominal end (docs/labels.md) — so the
purge condition is exact-or-conservative, never leaky.

The diagnostic-only schemes (`diagnostics.py`) use train/test roles with no
purge at all; `write_splits_table` emits both alongside each other.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from identity.source import sql_quote

logger = logging.getLogger(__name__)


def build_tag_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create `split_tags`: one row per (scheme, fold, horizon, snapshot)
    that participates in the fold, with its role."""
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW split_tags AS
        SELECT * FROM (
            SELECT f.scheme, f.fold, f.horizon_years,
                   s.permaticker, s.snapshot_date, s.snapshot_kind,
                   CASE
                       WHEN s.snapshot_date < f.test_start THEN CASE
                           WHEN s.snapshot_date
                                + to_years(f.horizon_years)
                                + to_days(f.embargo_days) < f.test_start
                               THEN 'train'
                           WHEN s.snapshot_date
                                + to_years(f.horizon_years) < f.test_start
                               THEN 'embargoed'
                           ELSE 'purged'
                       END
                       WHEN s.snapshot_date < f.test_end
                            AND s.snapshot_kind = 'median'
                            AND s.observable
                           THEN 'test'
                   END AS role
            FROM snapshot_horizons s
            JOIN split_folds f USING (horizon_years)
        )
        WHERE role IS NOT NULL
        """
    )


def write_splits_table(
    con: duckdb.DuckDBPyConnection,
    interim_dir: Path,
) -> dict[str, int]:
    """Write splits.parquet; return and log summary counts."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    splits_path = interim_dir / "splits.parquet"
    rows = con.execute(
        f"""
        COPY (
            SELECT scheme, fold, horizon_years,
                   permaticker, snapshot_date, snapshot_kind, role
            FROM (SELECT * FROM split_tags
                  UNION ALL
                  SELECT * FROM diag_tags)
            ORDER BY scheme, horizon_years, fold,
                     permaticker, snapshot_date, snapshot_kind
        )
        TO {sql_quote(str(splits_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    ).fetchone()[0]

    per_role = con.execute(
        """
        SELECT scheme, role, count(*)
        FROM (SELECT * FROM split_tags UNION ALL SELECT * FROM diag_tags)
        GROUP BY scheme, role
        ORDER BY scheme, role
        """
    ).fetchall()

    counts = {"split_rows": int(rows)}
    for scheme, role, n in per_role:
        counts[f"{scheme}_{role}"] = int(n)
        logger.info("splits %s: %d %s rows", scheme, n, role)
    logger.info("splits: %d rows -> %s", rows, splits_path)
    return counts
