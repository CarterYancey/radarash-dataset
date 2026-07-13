"""Stage 2 — label functions over the extracted paths (README §6).

Pure aggregations: no delisting logic here (that lives in `paths`). For each
(snapshot, horizon) the terminal window collapses to average / min / max /
last-close values, each converted to a CAGR against the snapshot's entry
price with the nominal exponent 1/H (the actual window end may land a
weekend-shift early; the nominal horizon keeps thresholds comparable).

`delisted_in_window` is a single VARCHAR per horizon: 'false' when the
security still traded at the horizon end, otherwise the delist reason itself
(no separate reason column). NULL means the horizon is not yet observable —
no label was computed at all.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from identity.source import sql_quote

from .delistings import UNKNOWN_DELIST_REASON
from .paths import HORIZON_YEARS

logger = logging.getLogger(__name__)

# Binary-label thresholds on the terminal-month-average CAGR, in percent.
CAGR_THRESHOLDS_PCT = (0, 5, 8, 10)

NOT_DELISTED = "false"


def build_label_views(
    con: duckdb.DuckDBPyConnection,
    *,
    horizons: tuple[int, ...] = HORIZON_YEARS,
    thresholds_pct: tuple[int, ...] = CAGR_THRESHOLDS_PCT,
) -> None:
    """Create `labels_long` (one row per snapshot × observable horizon) and
    `labels_wide` (one row per snapshot, horizon-suffixed columns)."""
    threshold_cols = ",\n               ".join(
        f"fwd_cagr >= {pct / 100.0} AS cagr_ge_{pct}" for pct in thresholds_pct
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW labels_long AS
        WITH stock_stats AS (
            SELECT permaticker, snapshot_date, snapshot_kind, horizon_years,
                   any_value(horizon_end) AS horizon_end,
                   avg(closeadj) AS terminal_avg,
                   min(closeadj) AS terminal_min,
                   max(closeadj) AS terminal_max,
                   max_by(closeadj, pos) AS terminal_close
            FROM forward_paths
            GROUP BY permaticker, snapshot_date, snapshot_kind, horizon_years
        ),
        bench_stats AS (
            SELECT snapshot_date, horizon_years,
                   avg(spy_closeadj) AS spy_terminal_avg
            FROM benchmark_paths
            GROUP BY snapshot_date, horizon_years
        ),
        cagrs AS (
            SELECT st.permaticker, st.snapshot_date, st.snapshot_kind,
                   st.horizon_years, st.horizon_end,
                   pow(st.terminal_avg / s.entry_closeadj,
                       1.0 / st.horizon_years) - 1 AS fwd_cagr,
                   pow(st.terminal_close / s.entry_closeadj,
                       1.0 / st.horizon_years) - 1 AS fwd_cagr_p2p,
                   pow(st.terminal_min / s.entry_closeadj,
                       1.0 / st.horizon_years) - 1 AS fwd_min_cagr,
                   pow(st.terminal_max / s.entry_closeadj,
                       1.0 / st.horizon_years) - 1 AS fwd_max_cagr,
                   pow(b.spy_terminal_avg / e.spy_entry_closeadj,
                       1.0 / st.horizon_years) - 1 AS spy_cagr,
                   d.is_delisted, d.last_price_date, d.delist_reason
            FROM stock_stats st
            JOIN snapshots s USING (permaticker, snapshot_date, snapshot_kind)
            JOIN delistings d USING (permaticker)
            LEFT JOIN bench_stats b USING (snapshot_date, horizon_years)
            LEFT JOIN benchmark_entries e USING (snapshot_date)
        )
        SELECT permaticker, snapshot_date, snapshot_kind, horizon_years,
               horizon_end,
               fwd_cagr, fwd_cagr_p2p, fwd_min_cagr, fwd_max_cagr,
               fwd_cagr - spy_cagr AS fwd_excess_cagr,
               {threshold_cols},
               fwd_cagr > spy_cagr AS beat_spy,
               CASE WHEN is_delisted AND last_price_date < horizon_end
                    THEN coalesce(delist_reason,
                                  {sql_quote(UNKNOWN_DELIST_REASON)})
                    ELSE {sql_quote(NOT_DELISTED)}
               END AS delisted_in_window
        FROM cagrs
        """
    )

    blocks = []
    for h in horizons:
        tag = f"{int(h)}y"
        flt = f"FILTER (WHERE l.horizon_years = {int(h)})"
        cols = [
            f"any_value(l.fwd_cagr) {flt} AS fwd_{tag}_cagr",
            f"any_value(l.fwd_cagr_p2p) {flt} AS fwd_{tag}_cagr_p2p",
            f"any_value(l.fwd_min_cagr) {flt} AS fwd_{tag}_min_cagr",
            f"any_value(l.fwd_max_cagr) {flt} AS fwd_{tag}_max_cagr",
            f"any_value(l.fwd_excess_cagr) {flt} AS fwd_{tag}_excess_cagr",
            *(
                f"any_value(l.cagr_ge_{pct}) {flt} AS label_{tag}_cagr_ge_{pct}"
                for pct in thresholds_pct
            ),
            f"any_value(l.beat_spy) {flt} AS label_{tag}_beat_spy",
            f"any_value(l.delisted_in_window) {flt} AS delisted_in_window_{tag}",
        ]
        blocks.append(",\n               ".join(cols))
    wide_columns = ",\n               ".join(blocks)

    # LEFT JOIN keeps snapshots whose every horizon is still unobservable:
    # they must appear with all-NULL labels, not vanish (that would silently
    # shrink the recent end of the dataset).
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW labels_wide AS
        SELECT s.permaticker, s.ticker, s.quarter, s.quarter_trading_days,
               s.snapshot_date, s.snapshot_kind, s.entry_closeadj,
               {wide_columns}
        FROM snapshots s
        LEFT JOIN labels_long l
            USING (permaticker, snapshot_date, snapshot_kind)
        GROUP BY ALL
        """
    )


def write_labels_table(
    con: duckdb.DuckDBPyConnection,
    interim_dir: Path,
) -> dict[str, int]:
    """Write labels.parquet; return and log summary counts."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    labels_path = interim_dir / "labels.parquet"
    rows = con.execute(
        f"""
        COPY (
            SELECT * FROM labels_wide
            ORDER BY permaticker, snapshot_date, snapshot_kind
        )
        TO {sql_quote(str(labels_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    ).fetchone()[0]

    per_horizon = con.execute(
        f"""
        SELECT horizon_years,
               count(*) AS labeled,
               count(*) FILTER (delisted_in_window <> {sql_quote(NOT_DELISTED)})
                   AS delisted_in_window
        FROM labels_long
        GROUP BY horizon_years
        ORDER BY horizon_years
        """
    ).fetchall()

    counts = {"label_rows": int(rows)}
    for horizon_years, labeled, delisted in per_horizon:
        counts[f"labeled_{horizon_years}y"] = int(labeled)
        counts[f"delisted_in_window_{horizon_years}y"] = int(delisted)
        logger.info(
            "labels %dy: %d snapshots labeled, %d delisted in window",
            horizon_years,
            labeled,
            delisted,
        )
    logger.info("labels: %d rows -> %s", rows, labels_path)
    return counts
