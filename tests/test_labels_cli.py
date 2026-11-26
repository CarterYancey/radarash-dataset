"""End-to-end tests for the labels pipeline on a hand-checkable world.

Synthetic weekday calendar 2015-01-01 .. 2021-12-31, six stocks:

- GROW (300001): deterministic 12%/yr exponential growth, alive throughout.
  Checks the CAGR math, the terminal-month-average shave vs. point-to-point,
  the SPY-relative labels, and NULL labels for unobservable windows.
- DEAD (300002): constant 50.0, trades through 2016-06-30 then delists
  (ACTIONS: both `delisted` and `bankruptcyliquidation` — the specific
  reason must win). Constant prices also force the low/median/high dates
  to collapse onto the earliest day of each quarter.
- ZIG (300003): trades exactly seven days in 2015-Q1 with prices
  20, 40, 30, 10, 30, 50, 30, then voluntarily delists. Pins down the
  low/median/high snapshot dates (median tie -> earliest), and the
  delisting convention (final adjusted close carried at 0% to horizon)
  with exactly-known CAGRs from three different entry prices.
- BANK (300004): SIC 6021, excluded from the universe -> no snapshots.
- DIP (300005): piecewise-constant path whose peaks and troughs sit in
  different calendar quarters (100 → 60 → 30 → 120 → 24 → 150), pinning
  the max-drawdown segment fold with hand-computed values.
- WAVE (300006): a decaying sinusoid on a 5%/yr trend; its max drawdowns are
  cross-checked against a brute-force daily scan for every snapshot. It
  does not trade 2017-02-10 .. 2017-05-19 (a halt across a quarter
  boundary), so the forward-fill weighting of the decision-0022 path
  labels is exercised on a resumed path as well as on delistings.

SPY grows at exactly 8%/yr in SFP.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import math

import duckdb
import pytest

from identity import cli as identity_cli
from ingest.convert import csv_to_parquet
from ingest.tables import TABLES
from labels import cli as labels_cli

BASE = date(2015, 1, 1)
END = date(2021, 12, 31)

ZIG_PRICES = {
    date(2015, 1, 1): 20.0,
    date(2015, 1, 2): 40.0,
    date(2015, 1, 5): 30.0,
    date(2015, 1, 6): 10.0,  # low
    date(2015, 1, 7): 30.0,
    date(2015, 1, 8): 50.0,  # high
    date(2015, 1, 9): 30.0,  # final close
}



def dip_price(day: date) -> float:
    if day < date(2016, 1, 1):
        return 100.0
    if day <= date(2016, 1, 15):
        return 60.0
    if day < date(2016, 4, 1):
        return 30.0
    if day < date(2016, 7, 1):
        return 120.0
    if day < date(2016, 10, 1):
        return 24.0
    return 150.0


def wave_price(day: date) -> float:
    t = (day - BASE).days
    # Decaying swings: the first fall after entry is usually the deepest, so
    # it lands inside the entry quarter, a middle quarter, or the exit
    # quarter depending on the snapshot — all three segment kinds decide.
    amplitude = 0.4 * math.exp(-t / 600)
    return 100.0 * 1.05 ** (t / 365.25) * (1 + amplitude * math.sin(2 * math.pi * t / 97))


WAVE_HALT = (date(2017, 2, 10), date(2017, 5, 19))


def wave_trades(day: date) -> bool:
    return not WAVE_HALT[0] <= day <= WAVE_HALT[1]


TICKERS_CSV = """\
table,permaticker,ticker,name,exchange,category,sector,industry,famaindustry,siccode,scalemarketcap,isdelisted,firstpricedate,lastpricedate,lastupdated
SEP,300001,GROW,Growth Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,4 - Mid,N,2015-01-01,2021-12-31,2026-07-01
SEP,300002,DEAD,Dead Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3510,3 - Small,Y,2015-01-01,2016-06-30,2026-07-01
SEP,300003,ZIG,Zigzag Corp,OTC,Domestic Common Stock,Healthcare,Biotechnology,Pharmaceuticals,2836,2 - Micro,Y,2015-01-01,2015-01-09,2026-07-01
SEP,300004,BANK,Big Bank,NYSE,Domestic Common Stock,Financial Services,Banks,Banking,6021,5 - Large,N,2015-01-01,2021-12-31,2026-07-01
"""

# DEAD carries both a generic and a specific reason: priority must pick
# bankruptcyliquidation. ZIG's action lands after its last trade (grace
# window). GROW's split is not a delist reason and must be ignored.
ACTIONS_CSV = """\
date,action,ticker,name,contraticker,contraname
2016-06-30,delisted,DEAD,Dead Corp,,
2016-06-30,bankruptcyliquidation,DEAD,Dead Corp,,
2015-01-15,voluntarydelisting,ZIG,Zigzag Corp,,
2018-06-01,split,GROW,Growth Corp,,
"""


def weekdays(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def growth_price(day: date, base: float, annual_rate: float) -> float:
    return base * (1 + annual_rate) ** ((day - BASE).days / 365.25)


def grow_price(day: date) -> float:
    return growth_price(day, 100.0, 0.12)


def spy_price(day: date) -> float:
    return growth_price(day, 100.0, 0.08)


def build_sep_csv() -> str:
    lines = ["ticker,date,close,closeadj,lastupdated"]
    for day in weekdays(BASE, END):
        lines.append(f"GROW,{day},{grow_price(day)!r},{grow_price(day)!r},2026-07-01")
        if day <= date(2016, 6, 30):
            lines.append(f"DEAD,{day},50.0,50.0,2026-07-01")
        if day in ZIG_PRICES:
            px = ZIG_PRICES[day]
            lines.append(f"ZIG,{day},{px!r},{px!r},2026-07-01")
        if day.year == 2015:
            lines.append(f"BANK,{day},25.0,25.0,2026-07-01")
    return "\n".join(lines) + "\n"


# DIP and WAVE exist only in this module's world: the splits tests reuse
# TICKERS_CSV/build_sep_csv and hand-count its snapshots.
PATH_TICKERS_ROWS = """\
SEP,300005,DIP,Dip Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3520,3 - Small,N,2015-01-01,2021-12-31,2026-07-01
SEP,300006,WAVE,Wave Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3530,3 - Small,N,2015-01-01,2021-12-31,2026-07-01
"""


def build_path_sep_rows() -> str:
    lines = []
    for day in weekdays(BASE, END):
        lines.append(f"DIP,{day},{dip_price(day)!r},{dip_price(day)!r},2026-07-01")
        if wave_trades(day):
            lines.append(f"WAVE,{day},{wave_price(day)!r},{wave_price(day)!r},2026-07-01")
    return "\n".join(lines) + "\n"


def build_sfp_csv() -> str:
    lines = ["ticker,date,close,closeadj,lastupdated"]
    for day in weekdays(BASE, END):
        lines.append(f"SPY,{day},{spy_price(day)!r},{spy_price(day)!r},2026-07-01")
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def labels_world(tmp_path_factory) -> Path:
    """Data dir with the full pipeline (identity + labels) already run."""
    data_dir = tmp_path_factory.mktemp("labels_world")
    raw = data_dir / "raw"
    for name, csv_text in (
        ("TICKERS", TICKERS_CSV + PATH_TICKERS_ROWS),
        ("SEP", build_sep_csv() + build_path_sep_rows()),
        ("SFP", build_sfp_csv()),
        ("ACTIONS", ACTIONS_CSV),
    ):
        csv_path = data_dir / f"{name}_fixture.csv"
        csv_path.write_text(csv_text)
        csv_to_parquet(csv_path, TABLES[name], raw / f"{name}.parquet")

    assert identity_cli.main(["--data-dir", str(data_dir)]) == 0
    assert labels_cli.main(["--data-dir", str(data_dir)]) == 0
    return data_dir


def query(data_dir: Path, table: str, sql: str):
    path = data_dir / "interim" / f"{table}.parquet"
    return duckdb.sql(sql.format(t=f"'{path}'")).fetchall()


def one_row(data_dir: Path, table: str, sql: str):
    rows = query(data_dir, table, sql)
    assert len(rows) == 1, rows
    return rows[0]


def test_outputs_exist(labels_world):
    for name in ("snapshots.parquet", "labels.parquet"):
        assert (labels_world / "interim" / name).exists()


def test_snapshot_counts(labels_world):
    rows = query(
        labels_world,
        "snapshots",
        "SELECT permaticker, count(*) FROM {t} GROUP BY 1 ORDER BY 1",
    )
    # GROW/DIP/WAVE: 28 quarters, DEAD: 6, ZIG: 1 — three snapshots each;
    # BANK: none.
    assert rows == [
        (300001, 84),
        (300002, 18),
        (300003, 3),
        (300005, 84),
        (300006, 84),
    ]


def test_zigzag_snapshot_dates(labels_world):
    rows = query(
        labels_world,
        "snapshots",
        """
        SELECT snapshot_kind, snapshot_date, entry_closeadj, quarter_trading_days
        FROM {t} WHERE permaticker = 300003 ORDER BY snapshot_date
        """,
    )
    assert rows == [
        # Median value 30 traded on Jan 5, 7, and 9 — earliest date wins.
        ("median", date(2015, 1, 5), 30.0, 7),
        ("low", date(2015, 1, 6), 10.0, 7),
        ("high", date(2015, 1, 8), 50.0, 7),
    ]


def test_constant_price_collapses_to_first_day(labels_world):
    rows = query(
        labels_world,
        "snapshots",
        """
        SELECT DISTINCT snapshot_date FROM {t}
        WHERE permaticker = 300002 AND quarter = DATE '2015-01-01'
        """,
    )
    # Constant price: every kind ties everywhere -> earliest day of quarter.
    assert rows == [(date(2015, 1, 1),)]


def test_grow_low_high_dates_are_quarter_edges(labels_world):
    row = one_row(
        labels_world,
        "snapshots",
        """
        SELECT min(snapshot_date) FILTER (snapshot_kind = 'low'),
               max(snapshot_date) FILTER (snapshot_kind = 'high')
        FROM {t} WHERE permaticker = 300001 AND quarter = DATE '2015-04-01'
        """,
    )
    # Monotonic growth: low on the first trading day, high on the last.
    assert row == (date(2015, 4, 1), date(2015, 6, 30))


def zig_labels(labels_world, kind: str):
    return one_row(
        labels_world,
        "labels",
        f"""
        SELECT fwd_1y_cagr, fwd_1y_cagr_p2p, fwd_1y_min_cagr, fwd_1y_max_cagr,
               fwd_1y_excess_cagr, label_1y_cagr_ge_0, label_1y_cagr_ge_5,
               label_1y_beat_spy, delisted_in_window_1y, fwd_5y_cagr,
               delisted_in_window_5y
        FROM {{t}} WHERE permaticker = 300003 AND snapshot_kind = '{kind}'
        """,
    )


def test_zigzag_delisting_convention(labels_world):
    # Entry 10 on the low date; final close 30 carried at 0% to every
    # horizon, so the whole terminal window is exactly 30.
    (cagr, p2p, lo, hi, excess, ge0, ge5, beat, dw1, cagr5, dw5) = zig_labels(
        labels_world, "low"
    )
    assert cagr == pytest.approx(2.0)
    assert p2p == pytest.approx(2.0)
    assert lo == pytest.approx(2.0)
    assert hi == pytest.approx(2.0)
    # SPY does ~7.7% under the averaging convention.
    assert 1.90 < excess < 1.94
    assert (ge0, ge5, beat) == (True, True, True)
    assert dw1 == "voluntarydelisting"
    assert cagr5 == pytest.approx(3.0 ** 0.2 - 1)
    assert dw5 == "voluntarydelisting"

    # Entry 50 on the high date: -40% to the frozen final value.
    (cagr, p2p, lo, hi, excess, ge0, ge5, beat, dw1, cagr5, dw5) = zig_labels(
        labels_world, "high"
    )
    assert cagr == pytest.approx(-0.4)
    assert (ge0, ge5, beat) == (False, False, False)

    # Entry 30 on the median date: exactly flat -> ge_0 is inclusive.
    (cagr, p2p, lo, hi, excess, ge0, ge5, beat, dw1, cagr5, dw5) = zig_labels(
        labels_world, "median"
    )
    assert cagr == pytest.approx(0.0)
    assert (ge0, ge5, beat) == (True, False, False)


def test_extended_threshold_labels(labels_world):
    def zig_extended(kind: str):
        return one_row(
            labels_world,
            "labels",
            f"""
            SELECT label_1y_cagr_ge_15, label_1y_cagr_ge_20,
                   label_1y_excess_ge_5, label_1y_excess_ge_10
            FROM {{t}} WHERE permaticker = 300003 AND snapshot_kind = '{kind}'
            """,
        )

    # ZIG low: +200% CAGR, ~+192% excess — every rung clears.
    assert zig_extended("low") == (True, True, True, True)
    # ZIG median: exactly 0% CAGR, ~-7.7% excess — every rung fails.
    assert zig_extended("median") == (False, False, False, False)

    # GROW at 12%/yr vs SPY at 8%/yr: ~11.x% CAGR and ~3-5% excess, so
    # ge_10 holds but ge_15/ge_20 and excess_ge_10 don't.
    row = one_row(
        labels_world,
        "labels",
        """
        SELECT label_1y_cagr_ge_10, label_1y_cagr_ge_15, label_1y_cagr_ge_20,
               label_1y_excess_ge_10
        FROM {t} WHERE permaticker = 300001
          AND snapshot_kind = 'median' AND quarter = DATE '2016-01-01'
        """,
    )
    assert row == (True, False, False, False)

    # Unobservable horizon: the new columns are NULL like the rest.
    row = one_row(
        labels_world,
        "labels",
        """
        SELECT label_1y_cagr_ge_20, label_1y_excess_ge_5
        FROM {t} WHERE permaticker = 300001
          AND snapshot_kind = 'high' AND quarter = DATE '2021-10-01'
        """,
    )
    assert row == (None, None)


def test_terminal_price_columns(labels_world):
    # ZIG low snapshot: the whole terminal window is the frozen final close,
    # so every terminal price collapses to exactly 30.
    row = one_row(
        labels_world,
        "labels",
        """
        SELECT fwd_1y_closeadj_avg, fwd_1y_closeadj_p2p,
               fwd_1y_closeadj_min, fwd_1y_closeadj_max,
               fwd_1y_spy_cagr, fwd_1y_cagr, fwd_1y_excess_cagr
        FROM {t} WHERE permaticker = 300003 AND snapshot_kind = 'low'
        """,
    )
    avg, p2p, mn, mx, spy, cagr, excess = row
    assert avg == p2p == mn == mx == pytest.approx(30.0)
    assert 0.070 < spy < 0.080  # SPY at 8%/yr under the averaging convention
    assert excess == pytest.approx(cagr - spy)

    # GROW rises monotonically: the window max is its last close (= p2p),
    # and each stored CAGR must be re-derivable from its stored price.
    row = one_row(
        labels_world,
        "labels",
        """
        SELECT entry_closeadj, fwd_1y_closeadj_avg, fwd_1y_closeadj_p2p,
               fwd_1y_closeadj_min, fwd_1y_closeadj_max,
               fwd_1y_cagr, fwd_1y_cagr_p2p
        FROM {t} WHERE permaticker = 300001
          AND snapshot_kind = 'median' AND quarter = DATE '2016-01-01'
        """,
    )
    entry, avg, p2p, mn, mx, cagr, cagr_p2p = row
    assert mn < avg < mx
    assert mx == pytest.approx(p2p)
    assert cagr == pytest.approx(avg / entry - 1)
    assert cagr_p2p == pytest.approx(p2p / entry - 1)


def test_dead_delisted_in_window_and_reason_priority(labels_world):
    row = one_row(
        labels_world,
        "labels",
        """
        SELECT fwd_1y_cagr, delisted_in_window_1y,
               fwd_2y_cagr, delisted_in_window_2y, label_2y_beat_spy,
               fwd_2y_excess_cagr
        FROM {t} WHERE permaticker = 300002
          AND snapshot_kind = 'median' AND quarter = DATE '2015-01-01'
        """,
    )
    cagr1, dw1, cagr2, dw2, beat2, excess2 = row
    # Still trading at the 1y horizon end (delists 2016-06-30): flat, alive.
    assert cagr1 == pytest.approx(0.0)
    assert dw1 == "false"
    # Gone by the 2y horizon end: still 0% under the convention, and the
    # specific bankruptcyliquidation must beat the generic delisted row.
    assert cagr2 == pytest.approx(0.0)
    assert dw2 == "bankruptcyliquidation"
    assert beat2 is False
    assert -0.09 < excess2 < -0.06


def test_grow_labels(labels_world):
    row = one_row(
        labels_world,
        "labels",
        """
        SELECT fwd_1y_cagr, fwd_1y_cagr_p2p, fwd_1y_min_cagr, fwd_1y_max_cagr,
               fwd_1y_excess_cagr, label_1y_cagr_ge_8, label_1y_cagr_ge_10,
               label_1y_beat_spy, delisted_in_window_1y
        FROM {t} WHERE permaticker = 300001
          AND snapshot_kind = 'median' AND quarter = DATE '2016-01-01'
        """,
    )
    cagr, p2p, lo, hi, excess, ge8, ge10, beat, dw = row
    # 12%/yr growth; the 21-day trailing average shaves ~0.5% off the
    # endpoint, and weekend/leap-day shifts of the end date move the
    # point-to-point figure a few basis points either side of 12%.
    assert 0.110 < cagr < 0.120
    assert 0.118 < p2p < 0.121
    assert lo < cagr < hi
    assert 0.030 < excess < 0.050  # vs. SPY at 8%/yr under the same convention
    assert (ge8, ge10, beat) == (True, True, True)
    assert dw == "false"


def test_unobservable_horizons_are_null(labels_world):
    # 2021-Q4 snapshot: even the 1y window ends past the calendar.
    row = one_row(
        labels_world,
        "labels",
        """
        SELECT fwd_1y_cagr, delisted_in_window_1y, fwd_5y_cagr,
               fwd_1y_closeadj_avg, fwd_1y_spy_cagr
        FROM {t} WHERE permaticker = 300001
          AND snapshot_kind = 'high' AND quarter = DATE '2021-10-01'
        """,
    )
    assert row == (None, None, None, None, None)

    # Boundary: the 2020-Q4 high snapshot (2020-12-31) targets exactly the
    # last calendar day (2021-12-31) -> observable.
    row = one_row(
        labels_world,
        "labels",
        """
        SELECT snapshot_date, fwd_1y_cagr, fwd_2y_cagr
        FROM {t} WHERE permaticker = 300001
          AND snapshot_kind = 'high' AND quarter = DATE '2020-10-01'
        """,
    )
    assert row[0] == date(2020, 12, 31)
    assert row[1] is not None
    assert row[2] is None


def test_labels_row_per_snapshot(labels_world):
    (snapshots,) = one_row(labels_world, "snapshots", "SELECT count(*) FROM {t}")
    (labels,) = one_row(labels_world, "labels", "SELECT count(*) FROM {t}")
    assert snapshots == labels == 273


def test_max_drawdown_hand_checked(labels_world):
    def dd(permaticker: int, kind: str, quarter: date, horizon: str):
        """(peak-to-trough max drawdown, max drawdown from entry)."""
        return one_row(
            labels_world,
            "labels",
            f"""
            SELECT fwd_{horizon}_max_drawdown,
                   fwd_{horizon}_max_drawdown_from_entry
            FROM {{t}}
            WHERE permaticker = {permaticker} AND snapshot_kind = '{kind}'
              AND quarter = DATE '{quarter}'
            """,
        )

    q2015 = date(2015, 1, 1)
    # ZIG, all inside the entry quarter, frozen at 30 after delisting.
    # Low (entry 10) peaks at 50 then ends at 30: a 40% drawdown, but it
    # never closes below entry. High (entry 50) falls to 30. Median
    # (entry 30) drops to 10 first — the fall from entry counts for both.
    assert dd(300003, "low", q2015, "1y") == pytest.approx((0.4, 0.0))
    assert dd(300003, "high", q2015, "5y") == pytest.approx((0.4, 0.4))
    assert dd(300003, "median", q2015, "1y") == pytest.approx((2 / 3, 2 / 3))
    # Monotonic and constant paths never fall; DEAD stays 0 past delisting.
    assert dd(300001, "median", q2015, "5y") == pytest.approx((0.0, 0.0))
    assert dd(300002, "median", q2015, "2y") == pytest.approx((0.0, 0.0))

    # DIP from 2015-01-01 (entry 100). 1y ends 2016-01-01 at 60: 40%, and
    # the 30s later in that exit quarter are past the horizon end. 2y: the
    # peak 120 (2016-Q2) and trough 24 (2016-Q3) both sit in quarters
    # strictly inside the path: 80% peak-to-trough, 76% below entry.
    assert dd(300005, "median", q2015, "1y") == pytest.approx((0.4, 0.4))
    assert dd(300005, "median", q2015, "2y") == pytest.approx((0.8, 0.76))
    assert dd(300005, "median", q2015, "5y") == pytest.approx((0.8, 0.76))
    # Low of 2016-Q1 (entry 30 on 2016-01-18): up to 120, down to 24.
    assert dd(300005, "low", date(2016, 1, 1), "1y") == pytest.approx((0.8, 0.2))
    # Entry at the 120 peak (2016-04-01): fall to 24 in the next quarter.
    assert dd(300005, "median", date(2016, 4, 1), "1y") == pytest.approx((0.8, 0.8))
    # Entry at 150 (2016-10-03), flat forever after.
    assert dd(300005, "median", date(2016, 10, 1), "3y") == pytest.approx((0.0, 0.0))

    # Unobservable horizon: NULL like every other label.
    assert dd(300005, "high", date(2021, 10, 1), "1y") == (None, None)


def naive_max_drawdown(prices: list[float]) -> float:
    peak, worst = prices[0], 0.0
    for px in prices:
        peak = max(peak, px)
        worst = max(worst, 1 - px / peak)
    return worst


def add_years(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # Feb 29 -> Feb 28, as DuckDB's to_years does
        return day.replace(year=day.year + years, day=28)


def test_max_drawdown_matches_brute_force(labels_world):
    days = list(weekdays(BASE, END))
    series = {
        300005: [(d, dip_price(d)) for d in days],
        300006: [(d, wave_price(d)) for d in days if wave_trades(d)],
    }
    rows = query(
        labels_world,
        "labels",
        """
        SELECT permaticker, snapshot_date,
               [fwd_1y_max_drawdown, fwd_1y_max_drawdown_from_entry],
               [fwd_2y_max_drawdown, fwd_2y_max_drawdown_from_entry],
               [fwd_3y_max_drawdown, fwd_3y_max_drawdown_from_entry],
               [fwd_5y_max_drawdown, fwd_5y_max_drawdown_from_entry]
        FROM {t} WHERE permaticker IN (300005, 300006)
        """,
    )
    checked = 0
    for permaticker, snapshot_date, *stored in rows:
        for years, (max_dd, from_entry) in zip((1, 2, 3, 5), stored):
            target = add_years(snapshot_date, years)
            if target > END:
                assert (max_dd, from_entry) == (None, None)
                continue
            path = [
                px for d, px in series[permaticker] if snapshot_date <= d <= target
            ]
            assert max_dd == pytest.approx(naive_max_drawdown(path), abs=1e-12)
            assert from_entry == pytest.approx(1 - min(path) / path[0], abs=1e-12)
            checked += 1
    # WAVE's swings make most paths draw down across quarter boundaries.
    assert checked > 400


PATH_LABEL_COLUMNS = (
    "max_runup", "days_to_max", "days_to_min", "path_avg_return",
    "realized_vol", "spy_max_runup", "spy_max_drawdown",
    "spy_max_drawdown_from_entry", "spy_path_avg_return",
)


def path_labels(data_dir: Path, permaticker: int, kind: str, quarter: date,
                horizon: str):
    cols = ", ".join(f"fwd_{horizon}_{c}" for c in PATH_LABEL_COLUMNS[:5])
    return one_row(
        data_dir,
        "labels",
        f"""
        SELECT {cols} FROM {{t}}
        WHERE permaticker = {permaticker} AND snapshot_kind = '{kind}'
          AND quarter = DATE '{quarter}'
        """,
    )


def test_path_labels_hand_checked(labels_world):
    q2015 = date(2015, 1, 1)
    # ZIG low: entry 10 on 2015-01-06 (calendar day 3), then 30, 50, 30 and
    # the final 30 carried to the horizon end. 1y target 2016-01-06 = day
    # 264, so the path is 262 days: 10 + 30 + 50 + 259 x 30 = 7860.
    runup, to_max, to_min, avg_ret, vol = path_labels(
        labels_world, 300003, "low", q2015, "1y"
    )
    assert (runup, to_max, to_min) == (pytest.approx(4.0), 2, 0)
    assert avg_ret == pytest.approx(7860 / 262 / 10 - 1)
    r2 = math.log(3) ** 2 + 2 * math.log(5 / 3) ** 2
    assert vol == pytest.approx(math.sqrt(252 * r2 / 261))
    # ZIG high: entry 50 on day 5, then one print at 30, frozen. The path
    # never rises (run-up 0 on the entry day) and bottoms the next day.
    runup, to_max, to_min, avg_ret, vol = path_labels(
        labels_world, 300003, "high", q2015, "1y"
    )
    assert (runup, to_max, to_min) == (pytest.approx(0.0), 0, 1)
    # 1y target 2016-01-08 = day 266: 50 + 261 x 30 over 262 days.
    assert avg_ret == pytest.approx((50 + 261 * 30) / 262 / 50 - 1)
    assert vol == pytest.approx(math.sqrt(252 * math.log(0.6) ** 2 / 261))
    # DEAD: constant then delisted — nothing moves, ties resolve to entry.
    assert path_labels(labels_world, 300002, "median", q2015, "2y") == (
        pytest.approx(0.0), 0, 0, pytest.approx(0.0), pytest.approx(0.0),
    )
    # DIP from 2015-01-01 (entry 100), 2y (ends 2016-12-30): high 150
    # first printed 2016-10-03 — after the low 24, first printed
    # 2016-07-01 (the recovery ordering the two day counts encode).
    runup, to_max, to_min, avg_ret, vol = path_labels(
        labels_world, 300005, "median", q2015, "2y"
    )
    days = list(weekdays(BASE, END))
    assert runup == pytest.approx(0.5)
    assert to_max == days.index(date(2016, 10, 3))
    assert to_min == days.index(date(2016, 7, 1))
    # Unobservable horizon: NULL like every other label.
    assert path_labels(labels_world, 300005, "high", date(2021, 10, 1), "1y") == (
        None,) * 5


def forward_filled(prints: dict[date, float], days: list[date]) -> list[float]:
    """Forward-filled closes over `days` (the first day must be a print)."""
    path, last = [], None
    for d in days:
        last = prints.get(d, last)
        path.append(last)
    return path


def test_path_labels_match_brute_force(labels_world):
    days = list(weekdays(BASE, END))
    prints = {
        300001: {d: grow_price(d) for d in days},
        300002: {d: 50.0 for d in days if d <= date(2016, 6, 30)},
        300003: dict(ZIG_PRICES),
        300005: {d: dip_price(d) for d in days},
        300006: {d: wave_price(d) for d in days if wave_trades(d)},
    }
    spy = {d: spy_price(d) for d in days}
    select = ", ".join(
        "[" + ", ".join(f"fwd_{h}y_{c}" for c in PATH_LABEL_COLUMNS) + "]"
        for h in (1, 2, 3, 5)
    )
    rows = query(
        labels_world, "labels",
        f"SELECT permaticker, snapshot_date, {select} FROM {{t}}",
    )
    checked = halted = 0
    for permaticker, snapshot_date, *stored in rows:
        for years, got in zip((1, 2, 3, 5), stored):
            target = add_years(snapshot_date, years)
            if target > END:
                assert got == [None] * len(PATH_LABEL_COLUMNS)
                continue
            window = [d for d in days if snapshot_date <= d <= target]
            path = forward_filled(prints[permaticker], window)
            entry = path[0]
            r2 = sum(math.log(b / a) ** 2 for a, b in zip(path, path[1:]))
            bench = forward_filled(spy, window)
            want = (
                max(path) / entry - 1,
                path.index(max(path)),
                path.index(min(path)),
                sum(path) / len(path) / entry - 1,
                math.sqrt(252 * r2 / (len(path) - 1)),
                max(bench) / bench[0] - 1,
                naive_max_drawdown(bench),
                1 - min(bench) / bench[0],
                sum(bench) / len(bench) / bench[0] - 1,
            )
            assert got == pytest.approx(want, rel=1e-9, abs=1e-12), (
                permaticker, snapshot_date, years)
            checked += 1
            if permaticker == 300006 and any(
                WAVE_HALT[0] <= d <= WAVE_HALT[1] for d in window
            ):
                halted += 1
    assert checked > 600
    # Paths crossing WAVE's halt pin the forward-fill weights mid-path.
    assert halted > 30


def test_missing_inputs(tmp_path):
    assert labels_cli.main(["--data-dir", str(tmp_path)]) == 2
