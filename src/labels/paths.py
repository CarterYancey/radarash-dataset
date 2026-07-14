"""Stage 1 — forward-path extraction (PLAN.md §6).

All delisting handling lives here and only here; the label functions in
`compute` are pure aggregations over these views. v1 endpoint labels only
need the *terminal window* of each horizon (the last N trading days), so
that is what gets extracted; triple-barrier labels later widen this module
to full paths without touching the label functions.

Delisting convention (docs/decisions/0002): the forward price on any trading
day is the security's most recent adjusted close on or before that day
(an ASOF join). Past the final trade this forward-fills the final adjusted
close — the position is carried at its last trading value with a 0% return
to the horizon. The same fill covers ordinary trading halts.

A horizon window exists only when the nominal end date (`snapshot_date + H
years`) is on or before the last calendar date — otherwise the outcome is
not yet observable and every label for that (snapshot, horizon) stays NULL.
Delisted stocks are deliberately not exempted: their own path is frozen, but
the benchmark's is not, and a delisted company can relist.
"""

from __future__ import annotations

import duckdb

HORIZON_YEARS = (1, 2, 3, 5)

# "Terminal-month average": the end value of a horizon-H label is the mean
# adjusted close over the 21 trading days ENDING at snapshot_date + H
# (the "or ending at" variant of PLAN.md §6), damping endpoint noise.
TERMINAL_WINDOW_TRADING_DAYS = 21


def build_path_views(
    con: duckdb.DuckDBPyConnection,
    *,
    horizons: tuple[int, ...] = HORIZON_YEARS,
    window_days: int = TERMINAL_WINDOW_TRADING_DAYS,
) -> None:
    """Create `terminal_windows`, `forward_paths`, `benchmark_paths`,
    and `benchmark_entries`."""
    horizon_list = ", ".join(str(int(h)) for h in horizons)
    span = int(window_days) - 1
    # Windows are keyed by (snapshot_date, horizon) — every stock snapshotted
    # on the same date shares them, and the benchmark reuses them verbatim.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW terminal_windows AS
        WITH horizons AS (
            SELECT unnest([{horizon_list}]) AS horizon_years
        ),
        snapshot_dates AS (
            SELECT DISTINCT snapshot_date FROM snapshots
        ),
        targets AS (
            SELECT sd.snapshot_date, h.horizon_years,
                   sd.snapshot_date + to_years(h.horizon_years) AS target_date
            FROM snapshot_dates sd
            CROSS JOIN horizons h
        ),
        observable AS (
            SELECT * FROM targets
            WHERE target_date <= (SELECT max(date) FROM trading_calendar)
        ),
        window_ends AS (
            SELECT o.snapshot_date, o.horizon_years,
                   c.date AS horizon_end, c.ix AS end_ix
            FROM observable o
            ASOF JOIN trading_calendar c ON o.target_date >= c.date
        )
        SELECT w.snapshot_date, w.horizon_years, w.horizon_end,
               c.date AS path_date,
               c.ix - (w.end_ix - {span}) AS pos
        FROM window_ends w
        JOIN trading_calendar c ON c.ix BETWEEN w.end_ix - {span} AND w.end_ix
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW forward_paths AS
        SELECT s.permaticker, s.snapshot_date, s.snapshot_kind,
               w.horizon_years, w.horizon_end, w.path_date, w.pos,
               p.closeadj,
               w.path_date > d.last_price_date AS is_extension
        FROM snapshots s
        JOIN terminal_windows w USING (snapshot_date)
        JOIN delistings d USING (permaticker)
        ASOF JOIN sep_resolved p
            ON s.permaticker = p.permaticker AND w.path_date >= p.date
        """
    )
    # LEFT joins on the benchmark: absolute labels must survive windows the
    # benchmark doesn't cover; only the relative labels go NULL there.
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW benchmark_paths AS
        SELECT w.snapshot_date, w.horizon_years, w.path_date, w.pos,
               p.closeadj AS spy_closeadj
        FROM terminal_windows w
        ASOF LEFT JOIN benchmark_prices p ON w.path_date >= p.date
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW benchmark_entries AS
        SELECT sd.snapshot_date, p.closeadj AS spy_entry_closeadj
        FROM (SELECT DISTINCT snapshot_date FROM snapshots) sd
        ASOF LEFT JOIN benchmark_prices p ON sd.snapshot_date >= p.date
        """
    )
