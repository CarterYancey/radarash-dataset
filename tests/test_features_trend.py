"""End-to-end tests for the trend & consistency family (ADR 0015).

Own synthetic world (weekday calendar 2015-01-01 .. 2017-12-31, constant
prices so every snapshot kind collapses onto the first trading day of the
quarter), three stocks:

- STEADY (500001): quarterly filings 2012Q1 .. 2017Q3, revenue/tangibles/
  ncfo growing at exactly 5%/2%/3% per quarter (textbook compounder:
  slope = 4·ln(rate), r² = 1, up_frac = 1), TTM dividend 8 through 2015
  then cut to 3 (one 0.8×-rule cut, streak unbroken). Early snapshots pin
  the partial-window min-count boundary (11 obs = exactly the 20q minimum).
  Book value per share compounds at exactly 1.5% per quarter across one
  buyback (10 shares through 2016, 8 from 2017-Q1) and TTM netinc is
  negative in the four periods of 2015 only (ADR 0023's bvps / shares
  series and `ni_positive_frac`).
- YOUNG (500002): three quarterly filings, 10%/quarter revenue growth —
  4q features populate, 8q+ stay NULL; one known dividend year, unpaid.
- NOFIL (500003): prices but no SF1 filings — the whole family is NULL.
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
from test_features_cli import build_sfp_csv, sf1_rows, weekdays

BASE = date(2015, 1, 1)
END = date(2017, 12, 31)

TICKERS_CSV = """\
table,permaticker,ticker,name,exchange,category,sector,industry,famaindustry,siccode,scalemarketcap,isdelisted,firstpricedate,lastpricedate,lastupdated
SEP,500001,STEADY,Steady Compounder,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,N,2015-01-01,2017-12-31,2026-07-01
SEP,500002,YOUNG,Young Corp,NYSE,Domestic Common Stock,Technology,Software - Application,Business Services,7372,2 - Micro,N,2015-01-01,2017-12-31,2026-07-01
SEP,500003,NOFIL,No Filings Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3550,2 - Micro,N,2015-01-01,2017-12-31,2026-07-01
"""

ACTIONS_CSV = """\
date,action,ticker,name,contraticker,contraname
2016-06-01,split,YOUNG,Young Corp,,
"""


def quarter_ends(first: date, last: date) -> list[date]:
    ends = [
        date(y, m, d)
        for y in range(first.year, last.year + 1)
        for m, d in ((3, 31), (6, 30), (9, 30), (12, 31))
    ]
    return [e for e in ends if first <= e <= last]


STEADY_PERIODS = quarter_ends(date(2012, 3, 31), date(2017, 9, 30))
YOUNG_PERIODS = quarter_ends(date(2016, 9, 30), date(2017, 3, 31))


def steady_dividend(reportperiod: date) -> float:
    return 8.0 if reportperiod < date(2016, 1, 1) else 3.0


def steady_shares(reportperiod: date) -> float:
    # One buyback: 10 shares through 2016-Q4, 8 from 2017-Q1.
    return 10.0 if reportperiod < date(2017, 1, 1) else 8.0


def steady_netinc(reportperiod: date) -> float:
    # Profitable except the four TTM periods of 2015.
    return -5.0 if reportperiod.year == 2015 else 10.0


def build_sf1_csv() -> str:
    from features.source import ARQ_LEVEL_FIELDS, ART_FLOW_FIELDS

    header = ",".join(
        ["ticker", "dimension", "calendardate", "datekey", "reportperiod",
         "lastupdated"]
        + list(ARQ_LEVEL_FIELDS)
        + list(ART_FLOW_FIELDS)
    )
    lines = [header]
    for i, rp in enumerate(STEADY_PERIODS):
        datekey = rp + timedelta(days=40)
        levels = {
            "assets": 1000, "tangibles": 300 * 1.02**i, "debt": 50,
            "cashneq": 25, "sharesbas": steady_shares(rp), "sharefactor": 1,
            "equity": 40 * steady_shares(rp) * 1.015**i,
        }
        flows = {
            "revenue": 100 * 1.05**i, "ncfo": 20 * 1.03**i,
            "ncfdiv": -steady_dividend(rp),
            "netinc": steady_netinc(rp),
        }
        lines += sf1_rows("STEADY", str(datekey), str(rp), levels, flows)
    for i, rp in enumerate(YOUNG_PERIODS):
        datekey = rp + timedelta(days=40)
        levels = {"assets": 200, "debt": 0, "cashneq": 10,
                  "sharesbas": 5, "sharefactor": 1, "equity": 100}
        flows = {"revenue": 100 * 1.10**i, "ncfo": 10, "ncfdiv": 0,
                 "netinc": 1}
        lines += sf1_rows("YOUNG", str(datekey), str(rp), levels, flows)
    return "\n".join(lines) + "\n"


def build_sep_csv() -> str:
    lines = ["ticker,date,close,closeadj,volume,lastupdated"]
    for day in weekdays(BASE, END):
        for ticker in ("STEADY", "YOUNG", "NOFIL"):
            lines.append(f"{ticker},{day},10.0,10.0,1000,2026-07-01")
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def trend_world(tmp_path_factory) -> Path:
    data_dir = tmp_path_factory.mktemp("trend_world")
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
        ["--data-dir", str(data_dir), "--families", "trend"]
    ) == 0
    return data_dir


def trend_row(data_dir: Path, permaticker: int, snapshot_date: str,
              columns: str):
    path = data_dir / "interim" / "features" / "trend.parquet"
    rows = duckdb.sql(
        f"""
        SELECT {columns} FROM '{path}'
        WHERE permaticker = {permaticker} AND snapshot_kind = 'median'
          AND snapshot_date = DATE '{snapshot_date}'
        """
    ).fetchall()
    assert len(rows) == 1, rows
    return rows[0]


def test_steady_full_window(trend_world):
    # 2017-Q4 median snapshot (constant price -> first trading day,
    # 2017-10-02); T0 = FY-period 2017-06-30 filed 2017-08-09. All 20
    # quarterly buckets are populated.
    row = trend_row(
        trend_world, 500001, "2017-10-02",
        "revenue_trend_4q, revenue_trend_8q, revenue_trend_12q, "
        "revenue_trend_20q, revenue_consistency_20q, revenue_up_frac_20q, "
        "tangibles_trend_20q, ocf_trend_20q, ocf_positive_frac_20q, "
        "fund_history_quarters",
    )
    r = 4 * math.log(1.05)
    assert row == pytest.approx(
        (r, r, r, r, 1.0, 1.0, 4 * math.log(1.02), 4 * math.log(1.03),
         1.0, 20)
    )


def test_steady_dividend_record(trend_world):
    # Annual buckets off 2017-06-30: TTM dividend 3, 3, 8, 8, 8, 8 —
    # six known years, all paid, one cut (8 -> 3 is below 0.8x).
    row = trend_row(
        trend_world, 500001, "2017-10-02",
        "div_years_paid_10y, div_streak_10y, div_cuts_10y, "
        "div_history_years_10y",
    )
    assert row == (6, 6, 1, 6)


def test_steady_partial_window(trend_world):
    # First snapshot (2015-01-01): T0 = 2014-09-30, history reaches back
    # 10 quarters to 2012-03-31 -> 11 observations, exactly the 20q
    # minimum. Dividends: three known years (2012..2014), all paid at 8.
    row = trend_row(
        trend_world, 500001, "2015-01-01",
        "fund_history_quarters, revenue_trend_12q, revenue_trend_20q, "
        "revenue_consistency_20q, div_years_paid_10y, div_streak_10y, "
        "div_cuts_10y, div_history_years_10y",
    )
    r = 4 * math.log(1.05)
    assert row == pytest.approx((11, r, r, 1.0, 3, 3, 0, 3))


def test_young_short_history(trend_world):
    # Three filings (T0 = 2017-03-31 filed 2017-05-10 at the 2017-07-03
    # snapshot): the 4q window has its 3-point minimum, 8q+ stay NULL.
    row = trend_row(
        trend_world, 500002, "2017-07-03",
        "revenue_trend_4q, revenue_consistency_4q, revenue_up_frac_4q, "
        "revenue_trend_8q, revenue_up_frac_8q, fund_history_quarters, "
        "div_years_paid_10y, div_streak_10y, div_cuts_10y, "
        "div_history_years_10y",
    )
    assert row[:3] == pytest.approx((4 * math.log(1.10), 1.0, 1.0))
    assert row[3:] == (None, None, 3, 0, 0, 0, 1)


def test_bvps_shares_and_ni_sign(trend_world):
    # 2017-Q4, T0 = 2017-06-30 (qoff 0), all 20 buckets present.
    row = trend_row(
        trend_world, 500001, "2017-10-02",
        "bvps_trend_4q, bvps_trend_20q, bvps_consistency_20q, "
        "bvps_up_frac_20q, shares_trend_20q, shares_up_frac_4q, "
        "shares_up_frac_20q, ni_positive_frac_4q, ni_positive_frac_12q, "
        "ni_positive_frac_20q",
    )
    b = 4 * math.log(1.015)
    assert row[:4] == pytest.approx((b, b, 1.0, 1.0))
    # Share count: 10 for qoff 2..19, 8 at qoff 0 and 1 — a falling fit,
    # and not one adjacent-quarter increase.
    xs = [-q / 4 for q in range(20)]
    ys = [math.log(8 if q < 2 else 10) for q in range(20)]
    mx, my = sum(xs) / 20, sum(ys) / 20
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum(
        (x - mx) ** 2 for x in xs
    )
    assert row[4] == pytest.approx(slope)
    assert slope < 0
    assert row[5:7] == (0.0, 0.0)
    # Losses in the four 2015 periods = qoff 6..9: clear of the 4q window,
    # 4 of 12, 4 of 20.
    assert row[7:] == pytest.approx((1.0, 8 / 12, 16 / 20))


def test_shares_have_no_consistency_column(trend_world):
    path = trend_world / "interim" / "features" / "trend.parquet"
    cols = [r[0] for r in duckdb.sql(f"DESCRIBE SELECT * FROM '{path}'").fetchall()]
    assert "bvps_consistency_4q" in cols
    assert not [c for c in cols if c.startswith("shares_consistency")]


def test_no_filings_all_null(trend_world):
    row = trend_row(trend_world, 500003, "2017-10-02", "*")
    assert all(v is None for v in row[3:])
