"""End-to-end tests for the long-window price features (ADR 0019).

Own synthetic world, weekday calendar 2012-01-02 .. 2017-12-29 (> 1260
trading days before the tested snapshot). Every stock's price is constant
from 2017-10-02 on, so each of its Q4-2017 snapshot kinds collapses onto
2017-10-02 — the snapshot tested throughout. The benchmark (SPY) log price
alternates 0, 0.01, 0, 0.01, ... per trading day: daily log returns ±0.01,
two-day returns exactly 0.

- LONG (700001): piecewise-constant closeadj — 10 through 2013, 40 in
  2014 (the 5y high), 20 in 2015, 30 from 2016 (with a one-day spike to 33
  on 2017-09-15), 24 from 2017-10-02: dist_5y_high = 24/40 - 1,
  mom_36_12 = 30/40 - 1, max_ret_21d = 33/30 - 1.
- BETA (700002): log price = 2 × SPY's -> beta_12m exactly 2.
- THIN (700003): listed 2015-01-02 (< 1000 prints in the 5y window, no
  t-756 print), log price = 1.5 × SPY's, but trading only every other
  weekday over the 30 weekdays before the snapshot. Its returns there
  span two days (stock return 0 against a ±0.01 one-day SPY return): only
  true one-day pairs enter the beta (exactly 1.5), and the MAX window
  holds no one-day return at all.
- HOP (700004): flat at 30, no print on 2017-09-20, 36 from 2017-09-21:
  the +20% move spans two days, so the MAX window's 19 one-day returns
  are all 0 (max_ret_21d = 0, the pinned mass), not 0.2.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from features import cli as features_cli
from identity import cli as identity_cli
from ingest.convert import csv_to_parquet
from ingest.tables import TABLES
from labels import cli as labels_cli
from test_features_cli import sf1_rows, weekdays

BASE = date(2012, 1, 1)
END = date(2017, 12, 31)
SNAP = date(2017, 10, 2)
DAYS = list(weekdays(BASE, END))
SNAP_I = DAYS.index(SNAP)
THIN_GAP_START = SNAP_I - 30

TICKERS_CSV = """\
table,permaticker,ticker,name,exchange,category,sector,industry,famaindustry,siccode,scalemarketcap,isdelisted,firstpricedate,lastpricedate,lastupdated
SEP,700001,LONG,Long History Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,N,2012-01-02,2017-12-29,2026-07-01
SEP,700002,BETA,Beta Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,N,2012-01-02,2017-12-29,2026-07-01
SEP,700003,THIN,Thin Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3550,2 - Micro,N,2015-01-02,2017-12-29,2026-07-01
SEP,700004,HOP,Hop Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3550,2 - Micro,N,2012-01-02,2017-12-29,2026-07-01
"""

ACTIONS_CSV = """\
date,action,ticker,name,contraticker,contraname
2016-06-01,split,THIN,Thin Corp,,
"""


def spy_log(i: int) -> float:
    return 0.01 * (i % 2)


def long_price(day: date) -> float:
    if day >= SNAP:
        return 24.0
    if day == date(2017, 9, 15):
        return 33.0
    if day.year >= 2016:
        return 30.0
    return {2015: 20.0, 2014: 40.0}.get(day.year, 10.0)


def price(ticker: str, i: int) -> float | None:
    day = DAYS[i]
    j = min(i, SNAP_I)  # constant from the snapshot on
    if ticker == "LONG":
        return long_price(day)
    if ticker == "HOP":
        if day == date(2017, 9, 20):
            return None
        return 36.0 if day > date(2017, 9, 20) else 30.0
    if ticker == "BETA":
        return 50.0 * math.exp(2 * spy_log(j))
    if day < date(2015, 1, 2):
        return None
    if THIN_GAP_START <= i <= SNAP_I and (SNAP_I - i) % 2:
        return None  # every other weekday, snapshot day traded
    return 20.0 * math.exp(1.5 * spy_log(j))


def build_sep_csv() -> str:
    lines = ["ticker,date,close,closeadj,volume,lastupdated"]
    for i, day in enumerate(DAYS):
        for ticker in ("LONG", "BETA", "THIN", "HOP"):
            px = price(ticker, i)
            if px is not None:
                lines.append(f"{ticker},{day},{px},{px},1000,2026-07-01")
    return "\n".join(lines) + "\n"


def build_sfp_csv() -> str:
    lines = ["ticker,date,close,closeadj,lastupdated"]
    for i, day in enumerate(DAYS):
        px = 100.0 * math.exp(spy_log(i))
        lines.append(f"SPY,{day},{px},{px},2026-07-01")
    return "\n".join(lines) + "\n"


def build_sf1_csv() -> str:
    from features.source import ARQ_LEVEL_FIELDS, ART_FLOW_FIELDS

    header = ",".join(
        ["ticker", "dimension", "calendardate", "datekey", "reportperiod",
         "lastupdated"]
        + list(ARQ_LEVEL_FIELDS)
        + list(ART_FLOW_FIELDS)
    )
    # Every field numeric (an all-empty CSV column would type as VARCHAR).
    levels = dict.fromkeys(ARQ_LEVEL_FIELDS, 1) | {"sharesbas": 10}
    flows = dict.fromkeys(ART_FLOW_FIELDS, 1)
    rp = date(2017, 6, 30)
    lines = [header]
    for ticker in ("LONG", "BETA", "THIN", "HOP"):
        lines += sf1_rows(ticker, str(rp + timedelta(days=40)), str(rp),
                          levels, flows)
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def long_world(tmp_path_factory) -> Path:
    data_dir = tmp_path_factory.mktemp("technical_long_world")
    raw = data_dir / "raw"
    for name, csv_text in (
        ("TICKERS", TICKERS_CSV),
        ("SF1", build_sf1_csv()),
        ("SEP", build_sep_csv()),
        ("SFP", build_sfp_csv()),
        ("ACTIONS", ACTIONS_CSV),
    ):
        csv_path = data_dir / f"{name}_fixture.csv"
        csv_path.write_text(csv_text)
        csv_to_parquet(csv_path, TABLES[name], raw / f"{name}.parquet")

    assert identity_cli.main(["--data-dir", str(data_dir)]) == 0
    assert labels_cli.main(["--data-dir", str(data_dir)]) == 0
    assert features_cli.main(
        ["--data-dir", str(data_dir), "--families", "technical"]
    ) == 0
    return data_dir


COLUMNS = "dist_5y_high, price_vs_5y_avg, mom_36_12, max_ret_21d, beta_12m"


def rows(data_dir: Path, permaticker: int):
    path = data_dir / "interim" / "features" / "technical.parquet"
    return duckdb.sql(
        f"""
        SELECT snapshot_kind, {COLUMNS} FROM '{path}'
        WHERE permaticker = {permaticker}
          AND snapshot_date = DATE '{SNAP}'
        ORDER BY snapshot_kind
        """
    ).fetchall()


def test_long_history_anchors(long_world):
    # The reference points sit where the docstring says they do.
    assert long_price(DAYS[SNAP_I - 252]) == 30.0
    assert long_price(DAYS[SNAP_I - 756]) == 40.0
    assert DAYS[SNAP_I - 1260].year == 2012  # window reaches the 10s
    window = [long_price(d) for d in DAYS[SNAP_I - 1260 : SNAP_I + 1]]
    got = rows(long_world, 700001)
    assert [r[0] for r in got] == ["high", "low", "median"]
    for row in got:
        assert row[1:5] == pytest.approx((
            24 / 40 - 1,                      # dist_5y_high
            24 / (sum(window) / len(window)) - 1,  # price_vs_5y_avg
            30 / 40 - 1,                      # mom_36_12
            33 / 30 - 1,                      # max_ret_21d (09-15 spike)
        ), abs=1e-12)


def test_exact_beta(long_world):
    for row in rows(long_world, 700002):
        assert row[5] == pytest.approx(2.0)
        # Log price alternates by 0.02: simple one-day returns e^±0.02 - 1.
        assert row[4] == pytest.approx(math.exp(0.02) - 1)


def test_thin_trader(long_world):
    for row in rows(long_world, 700003):
        dist5, avg5, mom36, max21, beta = row[1:]
        assert (dist5, avg5, mom36) == (None, None, None)  # too young
        assert max21 is None  # no one-day return in the last 21 days
        # Two-day returns (0 vs a ±0.01 one-day SPY move) would pull the
        # slope toward 0; only one-day pairs count, >= 200 remain.
        assert beta == pytest.approx(1.5)


def test_max_ret_uses_one_day_returns_only(long_world):
    got = rows(long_world, 700004)
    assert len(got) == 3
    for row in got:
        assert row[4] == 0.0
