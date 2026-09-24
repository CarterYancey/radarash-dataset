"""Stage 1 — forward-path extraction (PLAN.md §6).

All delisting handling lives here and only here; the label functions in
`compute` are pure aggregations over these views. Two path extracts:

- `forward_paths` — the *terminal window* of each horizon (the last N
  trading days), all the endpoint labels need.
- `path_segments` — the *full* forward path from entry to horizon end,
  compressed to calendar-quarter segments carrying (max, min, max
  drawdown). That triple is closed under concatenation, so path-dependent
  labels (max drawdown today, triple-barrier later) fold the segments in
  order instead of scanning a snapshot × day join (~2B rows at real scale).

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
    """Create `horizon_ends`, `terminal_windows`, `forward_paths`,
    `benchmark_paths`, `benchmark_entries`, and the full-path
    `path_segments` (via `build_path_segment_views`)."""
    if any(int(h) < 1 for h in horizons):
        # path_segments relies on every horizon end landing in a later
        # calendar quarter than its snapshot date.
        raise ValueError(f"horizons must be >= 1 year, got {horizons}")
    horizon_list = ", ".join(str(int(h)) for h in horizons)
    span = int(window_days) - 1
    # Horizon ends and windows are keyed by (snapshot_date, horizon) — every
    # stock snapshotted on the same date shares them, and the benchmark
    # reuses them verbatim.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW horizon_ends AS
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
        )
        SELECT o.snapshot_date, o.horizon_years,
               c.date AS horizon_end, c.ix AS end_ix
        FROM observable o
        ASOF JOIN trading_calendar c ON o.target_date >= c.date
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW terminal_windows AS
        SELECT w.snapshot_date, w.horizon_years, w.horizon_end,
               c.date AS path_date,
               c.ix - (w.end_ix - {span}) AS pos
        FROM horizon_ends w
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
    build_path_segment_views(con)


def build_path_segment_views(con: duckdb.DuckDBPyConnection) -> None:
    """Create `path_price_rows`, `path_price_blocks`, and `path_segments`:
    the full forward path of every observable (snapshot, horizon), as an
    ordered list of calendar-quarter segments.

    A segment summarises a run of consecutive prints by (max, min, dd),
    where dd is the largest peak-to-trough fall *within* the run
    (`1 − trough/peak`, peak before trough; 0 if it never falls). Two runs
    A then B concatenate to (max, min, max(A.dd, B.dd, 1 − B.min/A.max)),
    so the path's max drawdown is a left fold over its segments in order
    (`compute`). The path [entry, horizon end] splits at quarter
    boundaries into: the *suffix* of the entry quarter from the snapshot
    date on, every *full* stock-quarter strictly between, and the *prefix*
    of the exit quarter up to the horizon end. Suffix/prefix stats are
    per-row window aggregates over the stock's own prints; full-quarter
    stats are a GROUP BY. Nothing scales with snapshots × days.

    Delisting (decision 0002) needs no special case: the forward-filled
    path only ever repeats real prints, and past the final print it is
    flat, contributing no new peak or trough — so the stock's own prints
    in [snapshot_date, horizon_end] carry exactly the forward path's
    extremes. The exit quarter is the quarter of the last print on or
    before the horizon end (an ASOF join); when that is the entry quarter
    itself (delisted within the snapshot's quarter) the path is just the
    entry suffix — horizons ≥ 1y put every horizon end in a later quarter,
    so no print of that quarter can lie past it.
    """
    # Per-print prefix (from quarter start) and suffix (to quarter end)
    # aggregates. The suffix drawdown recurses backwards: a fall starting
    # at row s bottoms at the lowest *later* print of the quarter, so
    # suf_dd = running max over s >= r of (1 − next_min(s) / px(s)).
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW path_price_rows AS
        WITH r AS (
            SELECT permaticker, date, closeadj AS px,
                   date_trunc('quarter', date)::DATE AS block,
                   max(closeadj) OVER pre AS pre_max,
                   min(closeadj) OVER pre AS pre_min,
                   max(closeadj) OVER suf AS suf_max,
                   min(closeadj) OVER suf AS suf_min,
                   min(closeadj) OVER (
                       PARTITION BY permaticker, date_trunc('quarter', date)
                       ORDER BY date
                       ROWS BETWEEN 1 FOLLOWING AND UNBOUNDED FOLLOWING
                   ) AS next_min
            FROM sep_resolved
            WINDOW
                pre AS (PARTITION BY permaticker, date_trunc('quarter', date)
                        ORDER BY date
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW),
                suf AS (PARTITION BY permaticker, date_trunc('quarter', date)
                        ORDER BY date
                        ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING)
        )
        SELECT permaticker, date, block, px,
               pre_max, pre_min,
               max(1 - px / pre_max) OVER (
                   PARTITION BY permaticker, block ORDER BY date
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
               ) AS pre_dd,
               suf_max, suf_min,
               max(greatest(0.0, coalesce(1 - next_min / px, 0.0))) OVER (
                   PARTITION BY permaticker, block ORDER BY date
                   ROWS BETWEEN CURRENT ROW AND UNBOUNDED FOLLOWING
               ) AS suf_dd
        FROM r
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW path_price_blocks AS
        SELECT permaticker, block,
               max(px) AS blk_max, min(px) AS blk_min, max(pre_dd) AS blk_dd
        FROM path_price_rows
        GROUP BY permaticker, block
        """
    )
    # Snapshot dates are the stock's own trading days, so the entry join is
    # an equi-join; the exit is the last print on or before the horizon end.
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW path_segments AS
        WITH ends AS (
            SELECT s.permaticker, s.snapshot_date, s.snapshot_kind,
                   h.horizon_years, h.horizon_end
            FROM snapshots s
            JOIN horizon_ends h USING (snapshot_date)
        ),
        anchored AS (
            SELECT e.*, a.block AS entry_block,
                   a.suf_max, a.suf_min, a.suf_dd
            FROM ends e
            JOIN path_price_rows a
              ON a.permaticker = e.permaticker AND a.date = e.snapshot_date
        ),
        bounded AS MATERIALIZED (
            SELECT a.*, z.block AS exit_block,
                   z.pre_max, z.pre_min, z.pre_dd
            FROM anchored a
            ASOF JOIN path_price_rows z
              ON a.permaticker = z.permaticker AND a.horizon_end >= z.date
        )
        SELECT permaticker, snapshot_date, snapshot_kind, horizon_years,
               entry_block AS seg_block,
               suf_max AS seg_max, suf_min AS seg_min, suf_dd AS seg_dd
        FROM bounded
        UNION ALL
        SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
               b.horizon_years, k.block, k.blk_max, k.blk_min, k.blk_dd
        FROM bounded b
        JOIN path_price_blocks k
          ON k.permaticker = b.permaticker
         AND k.block > b.entry_block AND k.block < b.exit_block
        UNION ALL
        SELECT permaticker, snapshot_date, snapshot_kind, horizon_years,
               exit_block, pre_max, pre_min, pre_dd
        FROM bounded
        WHERE exit_block > entry_block
        """
    )
