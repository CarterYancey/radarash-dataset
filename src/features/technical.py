"""Technical family: price-window features from SEP (ADR 0005 §3).

Windows are trading-day offsets on the dense market-calendar index (same
convention as the labels module), aggregated over the stock's own trading
days inside the window. Reference prices for point-offset returns are
as-of: the stock's last close at or before the offset, tolerating up to
STALE_REF_TRADING_DAYS of prior staleness (a thinly-traded stock with no
print near the reference point gets NULL, not a years-old price). These
features differ across the three snapshot kinds by construction — that is
decision 0001's margin-of-safety gradient.

`conservative_score` is assembly-stage (M5) and not emitted here.
"""

from __future__ import annotations

import duckdb

# Longest lookback any feature needs: vol_36m's 756 trading days.
MAX_LOOKBACK_TRADING_DAYS = 756
# Tolerated staleness of an as-of reference price (~1 month of trading).
STALE_REF_TRADING_DAYS = 21
# Minimum daily-return observations for the volatility features.
VOL_12M_MIN_OBS = 200
VOL_36M_MIN_OBS = 600


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
                   max(p.closeadj) FILTER (p.ix >= snap.ix - 252) AS high_52w,
                   stddev_samp(p.logret_1d) FILTER (p.ix >= snap.ix - 252)
                       AS sd_12m,
                   count(p.logret_1d) FILTER (p.ix >= snap.ix - 252)
                       AS n_12m,
                   stddev_samp(p.logret_1d) AS sd_36m,
                   count(p.logret_1d) AS n_36m,
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
            GROUP BY 1, 2, 3
        )
        SELECT w.permaticker, w.snapshot_date, w.snapshot_kind,
               w.p21 / w.p252 - 1 AS mom_12_2,
               w.p0 / w.p126 - 1 AS ret_6m,
               w.p0 / w.p21 - 1 AS ret_1m,
               CASE WHEN w.n_12m >= {VOL_12M_MIN_OBS}
                    THEN w.sd_12m * sqrt(252) END AS vol_12m,
               CASE WHEN w.n_36m >= {VOL_36M_MIN_OBS}
                    THEN w.sd_36m * sqrt(252) END AS vol_36m,
               w.p0 / w.high_52w - 1 AS dist_52w_high,
               CASE WHEN m.marketcap > 0 THEN ln(m.marketcap) END
                   AS log_marketcap,
               w.dollar_volume_3m,
               w.amihud_12m
        FROM win w
        JOIN market_inputs m
          USING (permaticker, snapshot_date, snapshot_kind)
        """
    )
