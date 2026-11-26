"""Fundamental-history family (ADR 0023): today's fundamentals against the
stock's own record.

Every other fundamentals family describes the *current* filing (levels,
one-to-three-year changes) or the *direction* of a few series (trend). This
family answers the question a fundamentals investor asks next — "is today's
number normal for this company?" — from the same point-in-time history
buckets as the trend and relative-value families (src/features/history.py:
`fund_history`, 20 quarterly buckets; `annual_history`, fiscal-year
offsets 0..10). Five groups:

- **Own-norm profitability** — for `METRICS` (roa, roe, gross and
  operating margin, each recomputed per bucket from that bucket's own
  filing): `{m}_5y_median` (the normal level), `{m}_5y_std` (how stable it
  is), `{m}_5y_z` (`(current − mean) / std`: how unusual today is, in the
  stock's own units).
- **Normalized earnings power** — the price paid for average rather than
  latest earnings: `{earnings,ocf,fcf}_yield_5y_avg` (mean TTM flow over
  the window ÷ today's marketcap), `earnings_yield_5y_peak` (best TTM
  netinc of the window), `earnings_yield_at_5y_median_margin` (median net
  margin × today's revenue), `earnings_yield_10y_avg` (ten fiscal years,
  the Graham/Shiller form, nominal).
- **Distance from the own peak** — `{revenue,netinc,bvps}_vs_5y_peak`
  (`current / window max − 1`, ≤ 0) and
  `{…}_quarters_since_5y_peak` (0 = at the peak now): a fresh dip from a
  recent peak reads differently from a five-year slide.
- **Earnings surprise** — `{netinc,revenue}_sue_8q`: the latest
  adjacent-quarter change in the TTM figure (which equals the latest
  quarter minus the same quarter a year earlier) over the standard
  deviation of the eight changes before it — seasonal-random-walk SUE.
- **Ten-year record** — `ni_positive_years_10y` / `ni_history_years_10y`,
  and `{revenue,bvps,shares}_cagr_10y` over the full ten years.

Windowed statistics need `MIN_POINTS[20]` (11) of the 20 quarterly
observations, the ten-year averages `MIN_YEARS` of 10; unmet ⇒ NULL, as is
every column when the snapshot has no T0 filing. Nothing here reads a
price except today's marketcap (`market_inputs`), so the only inputs are
filings with `datekey < snapshot_date`.
"""

from __future__ import annotations

import duckdb

from .history import ANNUAL_YEARS, HISTORY_QUARTERS
from .sqlutil import safe_div
from .trend import MIN_POINTS

# metric name -> (numerator, denominator) in fund_history; NULL unless the
# denominator is > 0 (registry null rule, same as the level features).
METRICS: dict[str, tuple[str, str]] = {
    "roa": ("netinc", "assets"),
    "roe": ("netinc", "equity"),
    "gross_margin": ("gp", "revenue"),
    "operating_margin": ("ebit", "revenue"),
}
# yield name -> TTM flow in fund_history, for `{name}_5y_avg`
AVG_YIELDS: dict[str, str] = {
    "earnings_yield": "netinc",
    "ocf_yield": "ncfo",
    "fcf_yield": "fcf",
}
# series with `{name}_vs_5y_peak` / `{name}_quarters_since_5y_peak`
PEAK_SERIES: tuple[str, ...] = ("revenue", "netinc", "bvps")
# series with `{name}_sue_8q`
SUE_SERIES: tuple[str, ...] = ("netinc", "revenue")
SUE_QUARTERS = 8  # changes in the denominator (the eight before the latest)
SUE_MIN_CHANGES = 6
# series with `{name}_cagr_10y`
CAGR_SERIES: tuple[str, ...] = ("revenue", "bvps", "shares")
# Known fiscal years required by the ten-year averages (more than half).
MIN_YEARS = 6

_MIN_Q = MIN_POINTS[HISTORY_QUARTERS]


def _cur(col: str) -> str:
    """The current (qoff 0 = T0 filing) value of a bucket column."""
    return f"any_value(h.{col}) FILTER (WHERE h.qoff = 0)"


def _quarterly_exprs() -> list[str]:
    exprs: list[str] = []
    for name in METRICS:
        enough = f"count(h.{name}) >= {_MIN_Q}"
        z = safe_div(f"{_cur(name)} - avg(h.{name})", f"stddev_samp(h.{name})")
        exprs += [
            f"CASE WHEN {enough} THEN median(h.{name}) END AS {name}_5y_median",
            f"CASE WHEN {enough} THEN stddev_samp(h.{name}) END AS {name}_5y_std",
            f"CASE WHEN {enough} THEN {z} END AS {name}_5y_z",
        ]
    for name, col in AVG_YIELDS.items():
        exprs.append(
            f"CASE WHEN count(h.{col}) >= {_MIN_Q} THEN avg(h.{col}) END"
            f" AS {col}_avg"
        )
    exprs += [
        f"CASE WHEN count(h.netinc) >= {_MIN_Q} THEN max(h.netinc) END"
        " AS netinc_peak",
        f"CASE WHEN count(h.net_margin) >= {_MIN_Q}"
        f" THEN median(h.net_margin) * {_cur('revenue')} END"
        " AS netinc_at_median_margin",
    ]
    for name in PEAK_SERIES:
        enough = f"count(h.{name}) >= {_MIN_Q}"
        # struct order = (value, then the most recent quarter at it)
        since = (
            f"-max({{'v': h.{name}, 'nq': -h.qoff}})"
            f" FILTER (WHERE h.{name} IS NOT NULL).nq"
        )
        exprs += [
            f"CASE WHEN {enough}"
            f" THEN {safe_div(_cur(name), f'max(h.{name})')} - 1 END"
            f" AS {name}_vs_5y_peak",
            f"CASE WHEN {enough} THEN {since} END"
            f" AS {name}_quarters_since_5y_peak",
        ]
    for name in SUE_SERIES:
        pair = (
            f"h.prev_qoff = h.qoff + 1 AND h.{name} IS NOT NULL"
            f" AND h.prev_{name} IS NOT NULL"
        )
        change = f"h.{name} - h.prev_{name}"
        prior = f"FILTER (WHERE {pair} AND h.qoff BETWEEN 1 AND {SUE_QUARTERS})"
        latest = f"any_value({change}) FILTER (WHERE {pair} AND h.qoff = 0)"
        sue = safe_div(latest, f"stddev_samp({change}) {prior}")
        exprs.append(
            f"CASE WHEN count(*) {prior} >= {SUE_MIN_CHANGES} THEN {sue} END"
            f" AS {name}_sue_8q"
        )
    return exprs


def _annual_exprs() -> list[str]:
    last10 = f"FILTER (WHERE y.yoff < {ANNUAL_YEARS})"
    exprs = [
        f"CASE WHEN count(y.netinc) {last10} >= {MIN_YEARS}"
        f" THEN avg(y.netinc) {last10} END AS netinc_avg_10y",
        f"count(*) FILTER (WHERE y.yoff < {ANNUAL_YEARS} AND y.netinc > 0)"
        " AS ni_positive_years",
        f"count(y.netinc) {last10} AS ni_history_years",
    ]
    for name in CAGR_SERIES:
        now = f"any_value(y.{name}) FILTER (WHERE y.yoff = 0)"
        then = f"any_value(y.{name}) FILTER (WHERE y.yoff = {ANNUAL_YEARS})"
        # a negative ratio under a fractional exponent would be NaN: NULL.
        exprs.append(
            f"CASE WHEN {then} > 0 AND {now} >= 0"
            f" THEN pow({now} / {then}, 1.0 / {ANNUAL_YEARS}) - 1 END"
            f" AS {name}_cagr_10y"
        )
    return exprs


def build_fundhist_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_fundhist` view."""
    metric_cols = ",\n                   ".join(
        f"{safe_div(f'{num}', f'{den}')} AS {name}"
        for name, (num, den) in METRICS.items()
    )
    q_select = ",\n                   ".join(_quarterly_exprs())
    y_select = ",\n                   ".join(_annual_exprs())

    out = [
        f"q.{name}_5y_{stat}"
        for name in METRICS
        for stat in ("median", "std", "z")
    ]
    out += [
        f"{safe_div(f'q.{col}_avg', 'c.marketcap')} AS {name}_5y_avg"
        for name, col in AVG_YIELDS.items()
    ]
    out += [
        f"{safe_div('q.netinc_peak', 'c.marketcap')} AS earnings_yield_5y_peak",
        f"{safe_div('q.netinc_at_median_margin', 'c.marketcap')}"
        " AS earnings_yield_at_5y_median_margin",
        f"{safe_div('y.netinc_avg_10y', 'c.marketcap')} AS earnings_yield_10y_avg",
    ]
    for name in PEAK_SERIES:
        out += [f"q.{name}_vs_5y_peak", f"q.{name}_quarters_since_5y_peak"]
    out += [f"q.{name}_sue_8q" for name in SUE_SERIES]
    out += [
        "CASE WHEN y.ni_history_years > 0 THEN y.ni_positive_years END"
        " AS ni_positive_years_10y",
        "CASE WHEN c.has_filing THEN coalesce(y.ni_history_years, 0) END"
        " AS ni_history_years_10y",
    ]
    out += [f"y.{name}_cagr_10y" for name in CAGR_SERIES]
    out_select = ",\n               ".join(out)

    key = "permaticker, snapshot_date, snapshot_kind"
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW features_fundhist AS
        WITH c AS (
            SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
                   b.fund_reportperiod IS NOT NULL AS has_filing,
                   m.marketcap
            FROM fund_base b
            JOIN market_inputs m USING ({key})
        ),
        h AS (
            SELECT {key}, qoff, prev_qoff,
                   netinc, ncfo, fcf, revenue, bvps,
                   prev_netinc, prev_revenue,
                   {safe_div('netinc', 'revenue')} AS net_margin,
                   {metric_cols}
            FROM fund_history
            WHERE qoff < {HISTORY_QUARTERS}
        ),
        q AS (
            SELECT h.permaticker, h.snapshot_date, h.snapshot_kind,
                   {q_select}
            FROM h
            GROUP BY h.permaticker, h.snapshot_date, h.snapshot_kind
        ),
        y AS (
            SELECT y.permaticker, y.snapshot_date, y.snapshot_kind,
                   {y_select}
            FROM annual_history y
            GROUP BY y.permaticker, y.snapshot_date, y.snapshot_kind
        )
        SELECT c.permaticker, c.snapshot_date, c.snapshot_kind,
               {out_select}
        FROM c
        LEFT JOIN q USING ({key})
        LEFT JOIN y USING ({key})
        """
    )
