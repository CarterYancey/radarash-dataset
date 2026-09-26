"""Technical family: price-window features from SEP (ADR 0005 §3).

Windows are trading-day offsets on the dense market-calendar index (same
convention as the labels module), aggregated over the stock's own trading
days inside the window. Reference prices for point-offset returns are
as-of: the stock's last close at or before the offset, tolerating up to
STALE_REF_TRADING_DAYS of prior staleness (a thinly-traded stock with no
print near the reference point gets NULL, not a years-old price). These
features differ across the three snapshot kinds by construction — that is
decision 0001's margin-of-safety gradient.

Long-window price anchors (ADR 0019, research dataset-improvements §2.2):
`dist_5y_high` / `price_vs_5y_avg` over 1260 trading days (NULL below
`P60_MIN_OBS` prints — a "5-year" anchor over a shorter listing is a
different quantity, and its absence is the signal), long-term reversal
`mom_36_12`, the lottery/MAX factor `max_ret_21d` and the 12-month market
beta `beta_12m` against the labels' benchmark. The last two use only true
one-day returns (`prev_ix = ix - 1`), so a thin stock's multi-day jump
over a missing day neither poses as a daily MAX nor pairs with a one-day
benchmark return.

`conservative_score` is assembly-stage (M5) and not emitted here.
"""

from __future__ import annotations

import duckdb

# Longest lookback any feature needs: the 5-year anchors' 1260 trading days.
MAX_LOOKBACK_TRADING_DAYS = 1260
# Tolerated staleness of an as-of reference price (~1 month of trading).
STALE_REF_TRADING_DAYS = 21
# Minimum daily-return observations for the volatility features.
VOL_12M_MIN_OBS = 200
VOL_36M_MIN_OBS = 600
# Same ~80% coverage for the 5-year price anchors (1260 trading days).
P60_MIN_OBS = 1000
# Minimum true one-day returns in the 21-day MAX window (~70%).
MAX_RET_MIN_OBS = 15


def _ref_price(offset: int) -> str:
    """Last closeadj at ix <= snap.ix - offset, within the staleness band."""
    return (
        "max_by(p.closeadj, p.ix) FILTER ("
        f"p.ix BETWEEN snap.ix - {offset + STALE_REF_TRADING_DAYS}"
        f" AND snap.ix - {offset})"
    )


def build_technical_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_technical` view from `snapshots` and `sep_ix`."""
    p21, p126, p252 = _ref_price(21), _ref_price(126), _ref_price(252)
    p756 = _ref_price(756)
    daily = "p.prev_ix = p.ix - 1"
    beta_pair = f"p.ix >= snap.ix - 252 AND {daily} AND b.prev_ix = b.ix - 1"
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW features_technical AS
        WITH snap AS (
            SELECT s.permaticker, s.snapshot_date, s.snapshot_kind,
                   s.entry_closeadj, c.ix
            FROM snapshots s
            JOIN trading_calendar c ON c.date = s.snapshot_date
        ),
        win AS (
            SELECT snap.permaticker, snap.snapshot_date, snap.snapshot_kind,
                   any_value(snap.entry_closeadj) AS p0,
                   {p21} AS p21,
                   {p126} AS p126,
                   {p252} AS p252,
                   {p756} AS p756,
                   max(p.closeadj) FILTER (p.ix >= snap.ix - 252) AS high_52w,
                   max(p.closeadj) AS high_5y,
                   avg(p.closeadj) AS avg_5y,
                   count(p.closeadj) AS n_5y,
                   max(p.ret_1d) FILTER (p.ix > snap.ix - 21 AND {daily})
                       AS max_ret_21d,
                   count(p.ret_1d) FILTER (p.ix > snap.ix - 21 AND {daily})
                       AS n_ret_21d,
                   regr_slope(p.logret_1d, b.logret_1d) FILTER ({beta_pair})
                       AS beta_12m,
                   regr_count(p.logret_1d, b.logret_1d) FILTER ({beta_pair})
                       AS n_beta_12m,
                   stddev_samp(p.logret_1d) FILTER (p.ix >= snap.ix - 252)
                       AS sd_12m,
                   count(p.logret_1d) FILTER (p.ix >= snap.ix - 252)
                       AS n_12m,
                   stddev_samp(p.logret_1d) FILTER (p.ix >= snap.ix - 756)
                       AS sd_36m,
                   count(p.logret_1d) FILTER (p.ix >= snap.ix - 756)
                       AS n_36m,
                   median(p.dollar_volume) FILTER (p.ix >= snap.ix - 63)
                       AS dollar_volume_3m,
                   avg(abs(p.ret_1d) / p.dollar_volume) FILTER (
                       p.ix >= snap.ix - 252 AND p.dollar_volume > 0)
                       AS amihud_12m
            FROM snap
            JOIN sep_ix p
              ON p.permaticker = snap.permaticker
             AND p.ix BETWEEN snap.ix - {MAX_LOOKBACK_TRADING_DAYS}
                          AND snap.ix
            LEFT JOIN benchmark_ix b ON b.ix = p.ix
            GROUP BY 1, 2, 3
        )
        SELECT w.permaticker, w.snapshot_date, w.snapshot_kind,
               w.p21 / w.p252 - 1 AS mom_12_2,
               w.p252 / w.p756 - 1 AS mom_36_12,
               w.p0 / w.p126 - 1 AS ret_6m,
               w.p0 / w.p21 - 1 AS ret_1m,
               CASE WHEN w.n_ret_21d >= {MAX_RET_MIN_OBS}
                    THEN w.max_ret_21d END AS max_ret_21d,
               CASE WHEN w.n_12m >= {VOL_12M_MIN_OBS}
                    THEN w.sd_12m * sqrt(252) END AS vol_12m,
               CASE WHEN w.n_36m >= {VOL_36M_MIN_OBS}
                    THEN w.sd_36m * sqrt(252) END AS vol_36m,
               CASE WHEN w.n_beta_12m >= {VOL_12M_MIN_OBS}
                    THEN w.beta_12m END AS beta_12m,
               w.p0 / w.high_52w - 1 AS dist_52w_high,
               CASE WHEN w.n_5y >= {P60_MIN_OBS}
                    THEN w.p0 / w.high_5y - 1 END AS dist_5y_high,
               CASE WHEN w.n_5y >= {P60_MIN_OBS}
                    THEN w.p0 / w.avg_5y - 1 END AS price_vs_5y_avg,
               CASE WHEN m.marketcap > 0 THEN ln(m.marketcap) END
                   AS log_marketcap,
               w.dollar_volume_3m,
               w.amihud_12m
        FROM win w
        JOIN market_inputs m
          USING (permaticker, snapshot_date, snapshot_kind)
        """
    )
