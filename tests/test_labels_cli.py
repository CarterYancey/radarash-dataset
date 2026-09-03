"""End-to-end tests for the labels pipeline on a hand-checkable world.

Synthetic weekday calendar 2015-01-01 .. 2021-12-31, four stocks:

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

SPY grows at exactly 8%/yr in SFP.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

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
        ("TICKERS", TICKERS_CSV),
        ("SEP", build_sep_csv()),
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
    # GROW: 28 quarters, DEAD: 6, ZIG: 1 — three snapshots each; BANK: none.
    assert rows == [(300001, 84), (300002, 18), (300003, 3)]


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
    assert snapshots == labels == 105


def test_missing_inputs(tmp_path):
    assert labels_cli.main(["--data-dir", str(tmp_path)]) == 2
