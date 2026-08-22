"""Trend & consistency family (ADR 0015): long-history financial health.

Aggregates the `fund_history` / `div_history` foundation views
(src/features/history.py) into per-snapshot trend features over quarterly
windows of 4/8/12/20 quarters (matching the 1/2/3/5-year label horizons)
plus the annual dividend record over 10 fiscal years:

- `{s}_trend_{w}q` — `regr_slope(ln(value), years)`: annualized log growth
  (the exponential fit's rate), NULL unless the window holds at least
  `MIN_POINTS[w]` observations, all > 0.
- `{s}_consistency_{w}q` — `regr_r2` of the same fit (1 = textbook
  compounder; a constant series also scores 1: consistent, zero trend).
- `{s}_up_frac_{w}q` — fraction of available adjacent-quarter pairs that
  increased; needs `MIN_POINTS[w] - 1` pairs.
- `ocf_positive_frac_{w}q` — fraction of observations with `ncfo > 0`
  (carries the OCF-sign signal exactly where the log trend is NULL).
- `fund_history_quarters` — observations present in the 20q window.
- `div_*_10y` / `div_streak_10y` — years paid, current streak, cuts
  (TTM dividend below `DIVIDEND_CUT_RATIO ×` prior year's), years known.

Snapshots with no T0 filing are NULL across the family; dividend counters
are NULL when no year's dividend is known (missing stays NULL, never 0).
"""

from __future__ import annotations

import duckdb

from .sqlutil import safe_ln

WINDOWS: tuple[int, ...] = (4, 8, 12, 20)
# More than half the window's quarters must be present (ADR 0015 §6).
MIN_POINTS: dict[int, int] = {4: 3, 8: 5, 12: 7, 20: 11}
# A YoY drop of the TTM dividend below this ratio counts as a cut.
DIVIDEND_CUT_RATIO = 0.8

# feature-name prefix -> fund_history column
SERIES: dict[str, str] = {
    "revenue": "revenue",
    "tangibles": "tangibles",
    "ocf": "ncfo",
}


def _trend_exprs(name: str, col: str, w: int) -> list[str]:
    mp = MIN_POINTS[w]
    in_w = f"h.qoff < {w}"
    npos = f"count(*) FILTER (WHERE {in_w} AND h.{col} > 0)"
    nonpos = f"coalesce(bool_or(h.{col} <= 0) FILTER (WHERE {in_w}), FALSE)"
    fit_ok = f"{npos} >= {mp} AND NOT {nonpos}"
    # x = -qoff/4 puts time in years, increasing toward the snapshot.
    # safe_ln: ln() evaluates before FILTER, so non-positive values must
    # become NULL pairs (which regr_* ignores) rather than raise.
    fit_args = f"{safe_ln(f'h.{col}')}, -h.qoff / 4.0"
    fit_filter = f"FILTER (WHERE {in_w})"
    pair = (
        f"h.qoff <= {w - 2} AND h.prev_qoff = h.qoff + 1"
        f" AND h.{col} IS NOT NULL AND h.prev_{col} IS NOT NULL"
    )
    pairs = f"count(*) FILTER (WHERE {pair})"
    ups = f"count(*) FILTER (WHERE {pair} AND h.{col} > h.prev_{col})"
    return [
        f"CASE WHEN {fit_ok} THEN regr_slope({fit_args}) {fit_filter} END"
        f" AS {name}_trend_{w}q",
        f"CASE WHEN {fit_ok} THEN regr_r2({fit_args}) {fit_filter} END"
        f" AS {name}_consistency_{w}q",
        f"CASE WHEN {pairs} >= {mp - 1}"
        f" THEN CAST({ups} AS DOUBLE) / {pairs} END"
        f" AS {name}_up_frac_{w}q",
    ]


def _ocf_positive_expr(w: int) -> str:
    nobs = f"count(*) FILTER (WHERE h.qoff < {w} AND h.ncfo IS NOT NULL)"
    npos = f"count(*) FILTER (WHERE h.qoff < {w} AND h.ncfo > 0)"
    return (
        f"CASE WHEN {nobs} >= {MIN_POINTS[w]}"
        f" THEN CAST({npos} AS DOUBLE) / {nobs} END"
        f" AS ocf_positive_frac_{w}q"
    )


def build_trend_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_trend` view."""
    q_exprs = [
        expr
        for name, col in SERIES.items()
        for w in WINDOWS
        for expr in _trend_exprs(name, col, w)
    ]
    q_exprs += [_ocf_positive_expr(w) for w in WINDOWS]
    has_filing = "(b.fund_reportperiod IS NOT NULL)"
    q_exprs.append(
        f"CASE WHEN {has_filing} THEN count(h.qoff) END"
        " AS fund_history_quarters"
    )

    hist = "count(*) FILTER (WHERE v.div_ttm IS NOT NULL)"
    cut_pair = (
        "v.prev_yoff = v.yoff + 1 AND v.prev_div_ttm > 0"
        " AND v.div_ttm IS NOT NULL"
        f" AND v.div_ttm < {DIVIDEND_CUT_RATIO} * v.prev_div_ttm"
    )
    d_exprs = [
        f"CASE WHEN {hist} > 0"
        " THEN count(*) FILTER (WHERE v.div_ttm > 0) END"
        " AS div_years_paid_10y",
        f"CASE WHEN {hist} > 0"
        " THEN count(*) FILTER (WHERE v.streak_ok) END AS div_streak_10y",
        f"CASE WHEN {hist} > 0"
        f" THEN count(*) FILTER (WHERE {cut_pair}) END AS div_cuts_10y",
        f"CASE WHEN {has_filing} THEN {hist} END AS div_history_years_10y",
    ]

    trend_cols = [
        f"q.{name}_{stat}_{w}q"
        for name in SERIES
        for w in WINDOWS
        for stat in ("trend", "consistency", "up_frac")
    ]
    trend_cols += [f"q.ocf_positive_frac_{w}q" for w in WINDOWS]
    trend_cols.append("q.fund_history_quarters")
    trend_cols += [
        "d.div_years_paid_10y", "d.div_streak_10y", "d.div_cuts_10y",
        "d.div_history_years_10y",
    ]

    q_select = ",\n                   ".join(q_exprs)
    d_select = ",\n                   ".join(d_exprs)
    out_select = ",\n               ".join(trend_cols)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW features_trend AS
        WITH q AS (
            SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
                   {q_select}
            FROM fund_base b
            LEFT JOIN fund_history h
              USING (permaticker, snapshot_date, snapshot_kind)
            GROUP BY b.permaticker, b.snapshot_date, b.snapshot_kind,
                     {has_filing}
        ),
        d AS (
            SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
                   {d_select}
            FROM fund_base b
            LEFT JOIN div_history v
              USING (permaticker, snapshot_date, snapshot_kind)
            GROUP BY b.permaticker, b.snapshot_date, b.snapshot_kind,
                     {has_filing}
        )
        SELECT q.permaticker, q.snapshot_date, q.snapshot_kind,
               {out_select}
        FROM q
        JOIN d USING (permaticker, snapshot_date, snapshot_kind)
        """
    )
