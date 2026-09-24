"""End-to-end tests for the relative-value family (ADR 0018).

Own synthetic world (weekday calendar 2012-01-02 .. 2017-12-29; prices
constant within every calendar quarter, so each snapshot kind collapses
onto the quarter's first trading day), three stocks with flat
fundamentals — TTM netinc 20 / ncfo 10 / fcf 5 / revenue 100, equity 50,
tangibles 40, 10 shares — so every change in the ratios comes from the
price, and all six ratios move by the same factor:

- CHEAP (600001): quarterly filings 2012Q1 .. 2017Q3 filed 60 days after
  period end (the historical price anchor is `reportperiod + 45d`), close
  10 through 2016 then 5 from 2017-01-02: every ratio doubles (e.g.
  sales_yield 1 → 2, book_to_market 0.5 → 1). Pins the vs-median /
  midrank-percentile arithmetic and the 20q min-count boundary (11 priced
  buckets).
- PRE (600002): same filings filed 40 days after period end (anchor =
  datekey), but a steady loss (netinc −5), prices only from 2014-07-01 and
  none 2015-06-01 .. 2015-09-30 — pre-listing buckets and the bucket whose
  anchor falls in the gap (last print > 14 days old) stay unpriced, and
  the all-negative earnings_yield history has no median ratio (median ≤ 0)
  but still a percentile.
- NOFIL (600003): prices but no SF1 filings — the whole family is NULL.
"""

from __future__ import annotations

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
SEP,600001,CHEAP,Cheap Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,N,2012-01-02,2017-12-29,2026-07-01
SEP,600002,PRE,Pre Listing Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,2 - Micro,N,2014-07-01,2017-12-29,2026-07-01
SEP,600003,NOFIL,No Filings Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3550,2 - Micro,N,2012-01-02,2017-12-29,2026-07-01
"""

ACTIONS_CSV = """\
date,action,ticker,name,contraticker,contraname
2016-06-01,split,NOFIL,No Filings Corp,,
"""

PERIODS = quarter_ends(date(2012, 3, 31), date(2017, 9, 30))
FILING_LAG_DAYS = {"CHEAP": 60, "PRE": 40}
PRE_GAP = (date(2015, 6, 1), date(2015, 9, 30))


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
    levels = dict.fromkeys(ARQ_LEVEL_FIELDS, 1) | {
        "assets": 200, "equity": 50, "tangibles": 40, "debt": 0,
        "cashneq": 10, "sharesbas": 10, "sharefactor": 1,
    }
    for ticker, lag in FILING_LAG_DAYS.items():
        flows = dict.fromkeys(ART_FLOW_FIELDS, 0) | {
            "netinc": -5 if ticker == "PRE" else 20, "ncfo": 10, "fcf": 5,
            "revenue": 100,
        }
        for rp in PERIODS:
            datekey = rp + timedelta(days=lag)
            lines += sf1_rows(ticker, str(datekey), str(rp), levels, flows)
    return "\n".join(lines) + "\n"


def price(ticker: str, day: date) -> float | None:
    if ticker == "CHEAP":
        return 10.0 if day < date(2017, 1, 1) else 5.0
    if ticker == "PRE" and (
        day < date(2014, 7, 1) or PRE_GAP[0] <= day <= PRE_GAP[1]
    ):
        return None
    return 10.0


def build_sep_csv() -> str:
    lines = ["ticker,date,close,closeadj,volume,lastupdated"]
    for day in weekdays(BASE, END):
        for ticker in ("CHEAP", "PRE", "NOFIL"):
            close = price(ticker, day)
            if close is not None:
                lines.append(f"{ticker},{day},{close},{close},1000,2026-07-01")
    return "\n".join(lines) + "\n"


def build_sfp_csv() -> str:
    lines = ["ticker,date,close,closeadj,lastupdated"]
    for day in weekdays(BASE, END):
        lines.append(f"SPY,{day},100.0,100.0,2026-07-01")
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def relvalue_world(tmp_path_factory) -> Path:
    data_dir = tmp_path_factory.mktemp("relvalue_world")
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
        ["--data-dir", str(data_dir), "--families", "valuation", "relvalue"]
    ) == 0
    return data_dir


RATIOS = (
    "earnings_yield", "ocf_yield", "fcf_yield", "sales_yield",
    "book_to_market", "tangible_book_to_market",
)
COLUMNS = ", ".join(
    f"{r}_{stat}" for r in RATIOS for stat in ("vs_5y_median", "5y_pctile")
)


def expect(vs_median, pctile, **overrides):
    """Expected (vs_median, pctile) pairs for all six ratios, in COLUMNS
    order; `overrides` maps a ratio to its own pair."""
    pairs = [overrides.get(r, (vs_median, pctile)) for r in RATIOS]
    return tuple(v for pair in pairs for v in pair)


ALL_NULL = expect(None, None)


def relvalue_row(data_dir: Path, permaticker: int, snapshot_date: str,
                 columns: str = COLUMNS):
    path = data_dir / "interim" / "features" / "relvalue.parquet"
    rows = duckdb.sql(
        f"""
        SELECT {columns} FROM '{path}'
        WHERE permaticker = {permaticker} AND snapshot_kind = 'median'
          AND snapshot_date = DATE '{snapshot_date}'
        """
    ).fetchall()
    assert len(rows) == 1, rows
    return rows[0]


def test_cheap_vs_all_of_its_history(relvalue_world):
    # 2017-01-02 (close 5): T0 = 2016-09-30. Buckets 2012-03-31 ..
    # 2016-09-30 (19 obs), all anchored at reportperiod + 45d before the
    # step -> historical close 10 (marketcap 100; e.g. sales_yield 1,
    # book_to_market 0.5). Current marketcap 50 doubles every ratio ->
    # 2x the median, above every past value.
    row = relvalue_row(relvalue_world, 600001, "2017-01-02")
    assert row == pytest.approx(expect(2.0, 1.0))


def test_cheap_percentile_with_ties(relvalue_world):
    # 2017-10-02: T0 = 2017-06-30; the 20 buckets 2012-09-30 .. 2017-06-30
    # include 2016-12-31 / 2017-03-31 / 2017-06-30, anchored after the
    # step at close 5 (ratio equal to the current one). 17 below + 3 tied:
    # pctile (17 + 1.5) / 20; the median is still the pre-step value.
    row = relvalue_row(relvalue_world, 600001, "2017-10-02")
    assert row == pytest.approx(expect(2.0, 0.925))
    # The valuation family's snapshot ratios are the "current" values.
    path = relvalue_world / "interim" / "features" / "valuation.parquet"
    cur = duckdb.sql(
        f"""
        SELECT {", ".join(RATIOS)} FROM '{path}'
        WHERE permaticker = 600001 AND snapshot_kind = 'median'
          AND snapshot_date = DATE '2017-10-02'
        """
    ).fetchall()
    assert cur == [pytest.approx((0.4, 0.2, 0.1, 2.0, 1.0, 0.8))]


def test_cheap_min_count_boundary(relvalue_world):
    # 2015-01-01: T0 = 2014-09-30 -> 11 buckets back to 2012-03-31, exactly
    # the 20q minimum; flat price, so current = every past value (all ties).
    assert relvalue_row(relvalue_world, 600001, "2015-01-01") == pytest.approx(
        expect(1.0, 0.5)
    )
    # 2014-10-01: T0 = 2014-06-30 -> 10 buckets: below the minimum.
    assert relvalue_row(relvalue_world, 600001, "2014-10-01") == ALL_NULL


def test_pre_listing_and_stale_prices_are_unpriced(relvalue_world):
    # 2017-04-03: T0 = 2016-12-31. Buckets anchored (datekey = rp + 40d)
    # from 2014-08-09 (rp 2014-06-30) on have a print: 11 buckets, but
    # rp 2015-06-30's anchor 2015-08-09 sits in the price gap (last print
    # 2015-05-29, > 14 days old) -> 10 priced: NULL.
    assert relvalue_row(relvalue_world, 600002, "2017-04-03") == ALL_NULL
    # One quarter later the window holds 11 priced buckets. earnings_yield
    # is -0.05 in every bucket and now: the median is <= 0, so no median
    # ratio, but the percentile is sign-agnostic (all ties -> 0.5).
    assert relvalue_row(relvalue_world, 600002, "2017-07-03") == pytest.approx(
        expect(1.0, 0.5, earnings_yield=(None, 0.5))
    )


def test_no_filings_all_null(relvalue_world):
    row = relvalue_row(relvalue_world, 600003, "2017-10-02", "*")
    assert all(v is None for v in row[3:])
