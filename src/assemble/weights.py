"""Per-horizon uniqueness weights (decision 0012, de Prado AFML ch. 4).

`sample_weight_{H}` = the exact day-granularity average uniqueness of a
row's nominal label window `[snapshot_date, snapshot_date + H years]`
against all same-permaticker windows of the same horizon (all three
snapshot kinds pooled).

The concurrency count c(t) is piecewise constant, changing only where a
window starts (+1) or ends (−1), so the average of 1/c over a window is
computed as a cumulative-integral difference between two boundary points —
O(rows) work, no per-day expansion:

    events      one +n/−n delta per distinct boundary date
    segments    running c and segment length between consecutive boundaries
    cumulative  ∫ 1/c up to each boundary (gaps where c = 0 contribute 0;
                they can never intersect a window's own span)
    weights     (∫ at wend+1 − ∫ at wstart) / days in the window

Both `wstart` and `wend + 1 day` are boundaries by construction, so the two
lookups are plain equality joins.
"""

from __future__ import annotations

import duckdb


def build_weight_views(
    con: duckdb.DuckDBPyConnection,
    *,
    horizons: tuple[int, ...],
) -> None:
    """Create `sample_weights_wide`: one row per snapshot with a
    `sample_weight_{H}y` column per horizon (observability not yet applied —
    the output stage NULLs weights of unobservable labels)."""
    windows = " UNION ALL ".join(
        f"""
        SELECT permaticker, snapshot_date, snapshot_kind,
               {int(h)} AS horizon_years,
               snapshot_date AS wstart,
               CAST(snapshot_date + to_years({int(h)}) AS DATE) AS wend
        FROM labels_src
        """
        for h in horizons
    )
    con.execute(f"CREATE OR REPLACE TEMP VIEW weight_windows AS {windows}")
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW weight_events AS
        SELECT permaticker, horizon_years, d, sum(delta) AS delta
        FROM (
            SELECT permaticker, horizon_years, wstart AS d, 1 AS delta
            FROM weight_windows
            UNION ALL
            SELECT permaticker, horizon_years, wend + 1 AS d, -1 AS delta
            FROM weight_windows
        )
        GROUP BY permaticker, horizon_years, d
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW weight_segments AS
        SELECT permaticker, horizon_years, d,
               sum(delta) OVER win AS c,
               date_diff('day', d, lead(d) OVER win) AS seg_days
        FROM weight_events
        WINDOW win AS (PARTITION BY permaticker, horizon_years ORDER BY d)
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW weight_cumulative AS
        SELECT permaticker, horizon_years, d,
               coalesce(
                   sum(CASE WHEN c > 0 THEN seg_days / c::DOUBLE END)
                       OVER (PARTITION BY permaticker, horizon_years
                             ORDER BY d
                             ROWS BETWEEN UNBOUNDED PRECEDING
                                      AND 1 PRECEDING),
                   0) AS integral_before
        FROM weight_segments
        """
    )
    weight_cols = ", ".join(
        f"""max(sample_weight) FILTER (horizon_years = {int(h)})
                AS sample_weight_{int(h)}y"""
        for h in horizons
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW sample_weights_wide AS
        WITH per_horizon AS (
            SELECT w.permaticker, w.snapshot_date, w.snapshot_kind,
                   w.horizon_years,
                   (hi.integral_before - lo.integral_before)
                       / date_diff('day', w.wstart, w.wend + 1)
                       AS sample_weight
            FROM weight_windows w
            JOIN weight_cumulative lo
              ON lo.permaticker = w.permaticker
             AND lo.horizon_years = w.horizon_years
             AND lo.d = w.wstart
            JOIN weight_cumulative hi
              ON hi.permaticker = w.permaticker
             AND hi.horizon_years = w.horizon_years
             AND hi.d = w.wend + 1
        )
        SELECT permaticker, snapshot_date, snapshot_kind, {weight_cols}
        FROM per_horizon
        GROUP BY permaticker, snapshot_date, snapshot_kind
        """
    )
