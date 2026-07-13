"""End-to-end tests for the QA reports on a hand-checkable world.

Synthetic weekday calendar 2015-01-01 .. 2017-12-31, two stocks with constant
prices (so every quarter's low/median/high snapshots collapse onto the first
trading day of the quarter — snapshot dates are known by construction):

- GOODCO (400001): a model filer. ARQ rows for every fiscal quarter
  2012-03-31 .. 2017-09-30, each filed 45 days after the period end. Every
  snapshot therefore has a fresh filing (age 46-50 days) and, from 2015-Q3
  on, a full 3-year annual-lag chain (T3). Also carries MRQ rows equal to
  ARQ except one restated equity (2016-Q1: 50M -> 40M), and DAILY rows for
  2016 whose marketcap/pb are computed from the *as-reported* numbers — so
  the V7 check must conclude "closer to ARQ" on exactly the restated span.
- STALE (400002): two filings only — 2014-Q4 (filed 2015-02-14) and 2015-Q4
  (filed 2016-02-15, revenue NULL). Exercises: no-filing snapshots, every
  staleness bucket, the reportperiod-window YoY rule (its 2016+ snapshots
  are T1 because 2014-12-31 sits in [2015-12-31 - 395d, - 335d]), and
  tier-gating by staleness (2017-Q2 on: lag exists but the filing is stale).

SPY is constant too, so 1y labels are exactly 0% CAGR, ge_0 true, beat false.
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
from qa import cli as qa_cli

BASE = date(2015, 1, 1)
END = date(2017, 12, 31)

TICKERS_CSV = """\
table,permaticker,ticker,name,exchange,category,sector,industry,famaindustry,siccode,scalemarketcap,isdelisted,firstpricedate,lastpricedate,lastupdated
SEP,400001,GOODCO,Good Co,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,4 - Mid,N,2015-01-01,2017-12-31,2026-07-01
SEP,400002,STALE,Stale Filer Corp,OTC,Domestic Common Stock,Healthcare,Biotechnology,Pharmaceuticals,2836,2 - Micro,N,2015-01-01,2017-12-31,2026-07-01
"""

ACTIONS_CSV = """\
date,action,ticker,name,contraticker,contraname
2016-06-01,split,GOODCO,Good Co,,
"""

QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))


def weekdays(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def goodco_periods():
    for year in range(2012, 2018):
        for month, day in QUARTER_ENDS:
            rp = date(year, month, day)
            if rp <= date(2017, 9, 30):
                yield rp, rp + timedelta(days=45)


def build_sf1_csv() -> str:
    lines = [
        "ticker,dimension,calendardate,datekey,reportperiod,lastupdated,"
        "revenue,netinc,equity,sharesbas"
    ]
    for rp, dk in goodco_periods():
        lines.append(
            f"GOODCO,ARQ,{rp},{dk},{rp},{dk},1000,100,50000000,1000000"
        )
        # MRQ mirrors ARQ except one restated equity (2016-Q1: 50M -> 40M).
        equity = 40_000_000 if rp == date(2016, 3, 31) else 50_000_000
        lines.append(f"GOODCO,MRQ,{rp},{dk},{rp},{dk},1000,100,{equity},1000000")
    lines.append(
        "STALE,ARQ,2014-12-31,2015-02-14,2014-12-31,2015-02-14,200,10,100,2000000"
    )
    lines.append(
        "STALE,ARQ,2015-12-31,2016-02-15,2015-12-31,2016-02-15,,12,110,2000000"
    )
    return "\n".join(lines) + "\n"


def build_price_csv(rows: dict[str, float]) -> str:
    lines = ["ticker,date,close,closeadj,lastupdated"]
    for day in weekdays(BASE, END):
        for ticker, px in rows.items():
            lines.append(f"{ticker},{day},{px!r},{px!r},2026-07-01")
    return "\n".join(lines) + "\n"


def build_daily_csv() -> str:
    # 2016 only; marketcap in "millions" (close 100 x 1M shares = $100M),
    # pb from the AS-REPORTED equity of $50M: 100M / 50M = 2.0, always.
    lines = ["ticker,date,lastupdated,marketcap,ev,pe,pb,ps"]
    for day in weekdays(date(2016, 1, 1), date(2016, 12, 31)):
        lines.append(f"GOODCO,{day},{day},100.0,100.0,10.0,2.0,1.0")
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def qa_world(tmp_path_factory) -> Path:
    """Data dir with identity + labels + all three QA subcommands run."""
    data_dir = tmp_path_factory.mktemp("qa_world")
    raw = data_dir / "raw"
    for name, csv_text in (
        ("TICKERS", TICKERS_CSV),
        ("SEP", build_price_csv({"GOODCO": 100.0, "STALE": 20.0})),
        ("SFP", build_price_csv({"SPY": 100.0})),
        ("ACTIONS", ACTIONS_CSV),
        ("SF1", build_sf1_csv()),
        ("DAILY", build_daily_csv()),
    ):
        csv_path = data_dir / f"{name}_fixture.csv"
        csv_path.write_text(csv_text)
        csv_to_parquet(csv_path, TABLES[name], raw / f"{name}.parquet")

    assert identity_cli.main(["--data-dir", str(data_dir)]) == 0
    assert labels_cli.main(["--data-dir", str(data_dir)]) == 0

    report_dir = data_dir / "reports"
    common = ["--data-dir", str(data_dir), "--report-dir", str(report_dir)]
    assert qa_cli.main(["coverage", *common]) == 0
    assert qa_cli.main(["staleness", *common]) == 0
    assert qa_cli.main(["daily-pit", *common, "--sample-tickers", "10"]) == 0
    return data_dir


def query(data_dir: Path, table: str, sql: str):
    path = data_dir / "interim" / "qa" / f"{table}.parquet"
    return duckdb.sql(sql.format(t=f"'{path}'")).fetchall()


def test_outputs_exist(qa_world):
    for name in (
        "snapshot_coverage",
        "coverage_by_year",
        "coverage_by_sector",
        "null_rates_by_year",
        "null_rates_by_sector",
        "staleness_by_bucket",
        "staleness_by_year",
        "daily_freshness",
        "pit_marketcap_by_year",
        "pit_pb_check",
    ):
        assert (qa_world / "interim" / "qa" / f"{name}.parquet").exists()
    for name in ("coverage.md", "staleness.md", "daily_pit.md",
                 "coverage_by_year.csv", "staleness_by_bucket.csv"):
        assert (qa_world / "reports" / name).exists()


def test_coverage_by_year(qa_world):
    rows = query(
        qa_world,
        "coverage_by_year",
        """
        SELECT year, snapshots, with_filing, frac_fresh_183, frac_fresh_365,
               frac_t1, frac_t2, frac_t3
        FROM {t} ORDER BY year
        """,
    )
    # Hand-derived (module docstring): GOODCO is always fresh and is
    # T1/T2 throughout, T3 from 2015-Q3; STALE contributes the no-filing
    # 2015-Q1 row, becomes T1 only once its second filing exists (2016-Q2 on),
    # and goes stale (>365d) from 2017-Q2 on.
    assert rows == [
        (2015, 8, 7, 0.75, 0.875, 0.5, 0.5, 0.25),
        (2016, 8, 8, 0.75, 1.0, 0.875, 0.5, 0.5),
        (2017, 8, 8, 0.5, 0.625, 0.625, 0.5, 0.5),
    ]


def test_price_window_coverage(qa_world):
    # First snapshot has exactly one price day (itself); the 2015-Q4 snapshot
    # accrues 196 weekdays — just under the 200-day P12 bar.
    rows = query(
        qa_world,
        "snapshot_coverage",
        """
        SELECT snapshot_date, pdays_12m, p12_ok FROM {t}
        WHERE permaticker = 400001
          AND snapshot_date IN (DATE '2015-01-01', DATE '2015-10-01')
        ORDER BY snapshot_date
        """,
    )
    assert rows == [
        (date(2015, 1, 1), 1, False),
        (date(2015, 10, 1), 196, False),
    ]
    rows = query(
        qa_world,
        "coverage_by_year",
        "SELECT year, frac_p12, frac_p36 FROM {t} ORDER BY year",
    )
    # P36 (>=600 trading days) is only reachable from mid-2017 in a
    # 2015-start world: Q3/Q4 2017 pass, Q1/Q2 don't.
    assert rows == [(2015, 0.0, 0.0), (2016, 1.0, 0.0), (2017, 1.0, 0.5)]


def test_null_rates(qa_world):
    fields = {f for (f,) in query(qa_world, "null_rates_by_year",
                                  "SELECT DISTINCT field FROM {t}")}
    # Only the KEY_FIELDS present in this SF1 export are tracked.
    assert fields == {"revenue", "netinc", "equity", "sharesbas"}
    rows = query(
        qa_world,
        "null_rates_by_year",
        "SELECT year, null_rate FROM {t} WHERE field = 'revenue' ORDER BY year",
    )
    # STALE's 2015-Q4 filing has NULL revenue: it backs 3 of 2016's 8
    # with-filing snapshots and 4 of 2017's 8.
    assert rows == [(2015, 0.0), (2016, 0.375), (2017, 0.5)]


def test_staleness_buckets(qa_world):
    rows = query(
        qa_world,
        "staleness_by_bucket",
        "SELECT staleness_bucket, snapshots, labeled_1y FROM {t}",
    )
    # 24 median snapshots; 1y labels observable through 2016-12-31 only.
    assert rows == [
        ("no filing", 1, 1),
        ("0-93d", 14, 10),
        ("94-183d", 2, 2),
        ("184-365d", 4, 3),
        (">365d", 3, 0),
    ]
    (row,) = query(
        qa_world,
        "staleness_by_bucket",
        """
        SELECT mean_fwd_1y_cagr, frac_1y_ge_0, frac_1y_beat_spy,
               frac_delisted_1y
        FROM {t} WHERE staleness_bucket = '0-93d'
        """,
    )
    # Constant prices: exactly 0% CAGR, ge_0 inclusive, never beats flat SPY.
    assert row == (0.0, 1.0, 0.0, 0.0)


def test_daily_pit_freshness_and_marketcap(qa_world):
    (row,) = query(
        qa_world,
        "daily_freshness",
        "SELECT year, rows, median_lag_days, frac_lag_gt_35d FROM {t}",
    )
    # lastupdated == date on every fixture row: 261 weekdays in 2016, lag 0.
    assert row == (2016, 261, 0.0, 0.0)

    (row,) = query(
        qa_world,
        "pit_marketcap_by_year",
        "SELECT year, unit_scale, median_abs_err, frac_within_1pct FROM {t}",
    )
    # DAILY.marketcap is close x sharesbas in millions: scale 1e6, exact.
    assert row == (2016, 1_000_000.0, 0.0, 1.0)


def test_daily_pit_arq_vs_mrq(qa_world):
    (row,) = query(
        qa_world,
        "pit_pb_check",
        "SELECT year, discriminating_rows, frac_closer_to_arq FROM {t}",
    )
    # Equity is restated only for 2016-Q1, i.e. between its filing
    # (2016-05-15) and the next (2016-08-14): 65 weekdays. DAILY.pb was
    # built from as-reported equity, so it must side with ARQ everywhere.
    assert row == (2016, 65, 1.0)
    verdict = (qa_world / "reports" / "daily_pit.md").read_text()
    assert "closer to the **as-reported** book value 100.0%" in verdict


def test_missing_inputs(tmp_path):
    for command in ("coverage", "staleness", "daily-pit"):
        assert qa_cli.main([command, "--data-dir", str(tmp_path)]) == 2
