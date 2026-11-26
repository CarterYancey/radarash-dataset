"""End-to-end tests for the fundamental-history family (ADR 0023).

Own synthetic world (weekday calendar 2012-01-02 .. 2017-12-29; constant
close 10, so each snapshot kind collapses onto the quarter's first trading
day), three stocks:

- CYC (700001): quarterly filings 2012Q1 .. 2017Q3 filed 40 days after
  period end, 10 shares (marketcap 100), assets 200. A long flat record
  with a fresh dip: TTM netinc 20 until the last two filings before the
  2017-Q4 snapshot (12, then 4), equity 100 then 90, revenue rising by 5
  every quarter (always at its own peak; constant changes ⇒ no SUE),
  gp = revenue (gross margin exactly 1), ebit 10% of revenue then 5%.
- OLD (700002): fiscal-year filings only, 2007 .. 2017 (period end
  June 30) — eleven annual observations for the ten-year record, but only
  five of the twenty quarterly buckets, so every 5y column stays NULL.
  Revenue and shares double over the ten years, book value per share
  quadruples, three loss years; the 2007 profit of 1000 sits at year
  offset 10, outside the ten-year average.
- NOFIL (700003): prices but no SF1 filings — the whole family is NULL.
"""

from __future__ import annotations

import math
import statistics
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
from test_features_trend import quarter_ends

BASE = date(2012, 1, 1)
END = date(2017, 12, 31)

TICKERS_CSV = """\
table,permaticker,ticker,name,exchange,category,sector,industry,famaindustry,siccode,scalemarketcap,isdelisted,firstpricedate,lastpricedate,lastupdated
SEP,700001,CYC,Cyclical Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,N,2012-01-02,2017-12-29,2026-07-01
SEP,700002,OLD,Old Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,N,2012-01-02,2017-12-29,2026-07-01
SEP,700003,NOFIL,No Filings Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3550,2 - Micro,N,2012-01-02,2017-12-29,2026-07-01
"""

ACTIONS_CSV = """\
date,action,ticker,name,contraticker,contraname
2016-06-01,split,NOFIL,No Filings Corp,,
"""

CYC_PERIODS = quarter_ends(date(2012, 3, 31), date(2017, 9, 30))
OLD_YEARS = range(2007, 2018)
OLD_LOSS_YEARS = (2010, 2013, 2016)


def cyc_netinc(i: int) -> float:
    return {20: 12.0, 21: 4.0}.get(i, 20.0)


def cyc_equity(i: int) -> float:
    return 90.0 if i >= 21 else 100.0


def cyc_revenue(i: int) -> float:
    return 100.0 + 5 * i


def cyc_ebit(i: int) -> float:
    return (0.05 if i >= 21 else 0.10) * cyc_revenue(i)


def build_sf1_csv() -> str:
    from features.source import ARQ_LEVEL_FIELDS, ART_FLOW_FIELDS

    header = ",".join(
        ["ticker", "dimension", "calendardate", "datekey", "reportperiod",
         "lastupdated"]
        + list(ARQ_LEVEL_FIELDS)
        + list(ART_FLOW_FIELDS)
    )
    lines = [header]
    # Every field numeric (an all-empty CSV column would type as VARCHAR).
    base_levels = dict.fromkeys(ARQ_LEVEL_FIELDS, 1) | {
        "assets": 200, "debt": 0, "cashneq": 10, "sharefactor": 1,
    }
    base_flows = dict.fromkeys(ART_FLOW_FIELDS, 0)
    for i, rp in enumerate(CYC_PERIODS):
        levels = base_levels | {"equity": cyc_equity(i), "sharesbas": 10}
        flows = base_flows | {
            "netinc": cyc_netinc(i), "ncfo": 10, "fcf": 5,
            "revenue": cyc_revenue(i), "gp": cyc_revenue(i),
            "ebit": cyc_ebit(i),
        }
        lines += sf1_rows(
            "CYC", str(rp + timedelta(days=40)), str(rp), levels, flows
        )
    for k, year in enumerate(OLD_YEARS):  # k = 0 (2007) .. 10 (2017)
        rp = date(year, 6, 30)
        shares = 10 * 2 ** (k / 10)
        levels = base_levels | {
            "equity": 10 * 4 ** (k / 10) * shares, "sharesbas": shares,
        }
        netinc = 1000 if year == 2007 else (
            -4 if year in OLD_LOSS_YEARS else 10
        )
        flows = base_flows | {
            "netinc": netinc, "revenue": 100 * 2 ** (k / 10), "gp": 50,
            "ebit": 10, "ncfo": 10, "fcf": 5,
        }
        lines += sf1_rows(
            "OLD", str(rp + timedelta(days=40)), str(rp), levels, flows
        )
    return "\n".join(lines) + "\n"


def build_sep_csv() -> str:
    lines = ["ticker,date,close,closeadj,volume,lastupdated"]
    for day in weekdays(BASE, END):
        for ticker in ("CYC", "OLD", "NOFIL"):
            lines.append(f"{ticker},{day},10.0,10.0,1000,2026-07-01")
    return "\n".join(lines) + "\n"


def build_sfp_csv() -> str:
    lines = ["ticker,date,close,closeadj,lastupdated"]
    for day in weekdays(BASE, END):
        lines.append(f"SPY,{day},100.0,100.0,2026-07-01")
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def fundhist_world(tmp_path_factory) -> Path:
    data_dir = tmp_path_factory.mktemp("fundhist_world")
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
        ["--data-dir", str(data_dir), "--families", "fundhist"]
    ) == 0
    return data_dir


def fundhist_row(data_dir: Path, permaticker: int, snapshot_date: str,
                 columns: str):
    path = data_dir / "interim" / "features" / "fundhist.parquet"
    rows = duckdb.sql(
        f"""
        SELECT {columns} FROM '{path}'
        WHERE permaticker = {permaticker} AND snapshot_kind = 'median'
          AND snapshot_date = DATE '{snapshot_date}'
        """
    ).fetchall()
    assert len(rows) == 1, rows
    return rows[0]


# 2017-Q4 median snapshot = 2017-10-02; T0 = period 2017-06-30 (index 21,
# filed 2017-08-09 — the 2017-09-30 filing lands 2017-11-09, after it).
# The 20 buckets are period indexes 2 .. 21 (qoff 19 .. 0).
WINDOW = range(2, 22)
T0 = 21


def test_own_norm_profitability(fundhist_world):
    row = fundhist_row(
        fundhist_world, 700001, "2017-10-02",
        "roa_5y_median, roa_5y_std, roa_5y_z, roe_5y_median, roe_5y_z, "
        "gross_margin_5y_median, gross_margin_5y_std, gross_margin_5y_z, "
        "operating_margin_5y_median, operating_margin_5y_z",
    )
    roa = [cyc_netinc(i) / 200 for i in WINDOW]
    roe = [cyc_netinc(i) / cyc_equity(i) for i in WINDOW]
    opm = [cyc_ebit(i) / cyc_revenue(i) for i in WINDOW]

    def z(values):
        return (values[-1] - statistics.mean(values)) / statistics.stdev(values)

    # 18 quarters at roa 0.10, then 0.06 and 0.02: the norm is 0.10 and
    # today sits almost four of its own standard deviations below it.
    assert row[0] == pytest.approx(0.10)
    assert row[1] == pytest.approx(statistics.stdev(roa))
    assert row[2] == pytest.approx(z(roa))
    assert -3.9 < row[2] < -3.7
    assert row[3] == pytest.approx(0.20)
    assert row[4] == pytest.approx(z(roe))
    # Gross margin exactly 1 throughout: median 1, no dispersion, and a z
    # over a zero standard deviation is NULL, not ±inf.
    assert row[5:8] == (1.0, 0.0, None)
    assert row[8] == pytest.approx(0.10)
    assert row[9] == pytest.approx(z(opm))


def test_normalized_earnings_power(fundhist_world):
    row = fundhist_row(
        fundhist_world, 700001, "2017-10-02",
        "earnings_yield_5y_avg, ocf_yield_5y_avg, fcf_yield_5y_avg, "
        "earnings_yield_5y_peak, earnings_yield_at_5y_median_margin, "
        "earnings_yield_10y_avg",
    )
    # marketcap = 10 x 10 shares = 100. Mean TTM netinc (18x20+12+4)/20.
    assert row[:4] == pytest.approx((0.188, 0.10, 0.05, 0.20))
    # Median net margin x today's revenue (205): what the usual margin
    # would earn on current sales — far above the trailing yield 0.04.
    margin = statistics.median(cyc_netinc(i) / cyc_revenue(i) for i in WINDOW)
    assert row[4] == pytest.approx(margin * 205 / 100)
    assert row[4] > 0.2
    # Annual buckets off 2017-06-30 reach 2012-06-30: six known fiscal
    # years (exactly the minimum), netinc 4 + 5 x 20.
    assert row[5] == pytest.approx(104 / 6 / 100)


def test_distance_from_own_peak_and_sue(fundhist_world):
    row = fundhist_row(
        fundhist_world, 700001, "2017-10-02",
        "revenue_vs_5y_peak, revenue_quarters_since_5y_peak, "
        "netinc_vs_5y_peak, netinc_quarters_since_5y_peak, "
        "bvps_vs_5y_peak, bvps_quarters_since_5y_peak, "
        "netinc_sue_8q, revenue_sue_8q",
    )
    # Revenue is at its high today; netinc last stood at 20 two quarters
    # ago (ties resolve to the most recent quarter) and is 80% below it;
    # book value per share fell from 10 to 9 this quarter.
    assert row[:2] == (0.0, 0)
    assert row[2:4] == (pytest.approx(-0.8), 2)
    assert row[4:6] == (pytest.approx(-0.1), 1)
    # Latest TTM change 4 - 12 = -8; the eight before it are -8 and seven
    # zeros (sample variance 8).
    assert row[6] == pytest.approx(-8 / math.sqrt(8))
    # Revenue changes are all exactly 5: zero dispersion ⇒ NULL.
    assert row[7] is None


def test_ten_year_record_partial_history(fundhist_world):
    row = fundhist_row(
        fundhist_world, 700001, "2017-10-02",
        "ni_positive_years_10y, ni_history_years_10y, revenue_cagr_10y, "
        "bvps_cagr_10y, shares_cagr_10y",
    )
    assert row == (6, 6, None, None, None)


def test_min_count_boundary(fundhist_world):
    cols = (
        "roa_5y_median, earnings_yield_5y_avg, revenue_vs_5y_peak, "
        "netinc_quarters_since_5y_peak, netinc_sue_8q, "
        "earnings_yield_10y_avg, ni_history_years_10y"
    )
    # 2014-10-01: T0 = 2014-06-30 (index 9) — ten quarterly observations,
    # one short of the 20q minimum. SUE needs only nine filings; three
    # known fiscal years are too few for the ten-year average.
    row = fundhist_row(fundhist_world, 700001, "2014-10-01", cols)
    assert row[:4] == (None, None, None, None)
    assert row[4] is None  # all changes zero: no dispersion
    assert row[5:] == (None, 3)
    # One quarter later (T0 index 10): exactly eleven.
    row = fundhist_row(fundhist_world, 700001, "2015-01-01", cols)
    assert row[:4] == pytest.approx((0.10, 0.20, 0.0, 0))
    assert row[5:] == (None, 3)


def test_old_ten_year_record(fundhist_world):
    row = fundhist_row(
        fundhist_world, 700002, "2017-10-02",
        "revenue_cagr_10y, bvps_cagr_10y, shares_cagr_10y, "
        "ni_positive_years_10y, ni_history_years_10y, "
        "earnings_yield_10y_avg",
    )
    assert row[:3] == pytest.approx(
        (2 ** 0.1 - 1, 4 ** 0.1 - 1, 2 ** 0.1 - 1)
    )
    assert row[3:5] == (7, 10)
    # Fiscal 2008..2017: seven years at 10, three at -4; the 1000 of 2007
    # is year offset 10 and stays out. marketcap = 10 x 20 shares.
    assert row[5] == pytest.approx((7 * 10 - 3 * 4) / 10 / 200)


def test_old_annual_filer_has_no_5y_columns(fundhist_world):
    # Five of twenty quarterly buckets: every 20q statistic is NULL.
    row = fundhist_row(
        fundhist_world, 700002, "2017-10-02",
        "roa_5y_median, roa_5y_z, earnings_yield_5y_avg, "
        "earnings_yield_5y_peak, earnings_yield_at_5y_median_margin, "
        "revenue_vs_5y_peak, revenue_quarters_since_5y_peak, netinc_sue_8q",
    )
    assert row == (None,) * 8


def test_no_filings_all_null(fundhist_world):
    row = fundhist_row(fundhist_world, 700003, "2017-10-02", "*")
    assert all(v is None for v in row[3:])
