"""End-to-end tests for the inference dataset on a hand-checkable world.

Synthetic weekday calendar 2013-01-01 .. 2018-12-31, four stocks (the
assemble-test cast, ADR 0014 twists added):

- MONE / MTHR trade through the last day; MTWO's last print is 2018-12-26
  (three trading days early — inside the default staleness tolerance, so it
  snapshots on its own last trade date).
- MONE files its FY2017 report ON the last trading day (datekey =
  2018-12-31): the inference as-of is inclusive, so that same-day filing is
  its T0 — the training rule would have used FY2016.
- SOLO trades only 2016-Q1 and is delisted: absent from the latest
  inference cross-section, present under `--as-of 2016-02-15`.

Runs use --rank-guard 3 --min-industry-peers 3 so the three-stock
cross-sections clear the guards.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import duckdb
import pytest

from assemble.wide import feature_columns_in_order, rank_columns, secrank_columns
from features.source import ARQ_LEVEL_FIELDS, ART_FLOW_FIELDS
from identity import cli as identity_cli
from inference import cli as inference_cli
from ingest.convert import csv_to_parquet
from ingest.tables import TABLES

BASE = date(2013, 1, 1)
END = date(2018, 12, 31)
MTWO_LAST = date(2018, 12, 26)

TICKERS_CSV = """\
table,permaticker,ticker,name,exchange,category,sector,industry,famaindustry,siccode,scalemarketcap,isdelisted,firstpricedate,lastpricedate,lastupdated
SEP,500001,MONE,Machinery One,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,N,2013-01-01,2018-12-31,2026-07-01
SEP,500002,MTWO,Machinery Two,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3510,3 - Small,N,2013-01-01,2018-12-26,2026-07-01
SEP,500003,MTHR,Machinery Three,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3520,4 - Mid,N,2013-01-01,2018-12-31,2026-07-01
SEP,500004,SOLO,Solo Quarter Corp,OTC,Domestic Common Stock,Technology,Software - Application,Business Services,7372,1 - Nano,Y,2016-01-01,2016-03-31,2026-07-01
"""

PRICES = {"MONE": 10.0, "MTWO": 20.0, "MTHR": 40.0, "SOLO": 5.0}

LEVELS = {
    "assets": 1000, "assetsc": 400, "cashneq": 100, "receivables": 80,
    "inventory": 50, "ppnenet": 300, "investments": 20, "liabilities": 600,
    "liabilitiesc": 200, "debt": 250, "debtnc": 150, "equity": 400,
    "retearn": 120, "workingcapital": 200, "tangibles": 900, "invcap": 650,
    "sharesbas": 100, "sharefactor": 1,
}

FLOW_DEFAULTS = {
    "gp": 200, "sgna": 100, "depamor": 30, "ebit": 70, "ebitda": 100,
    "intexp": 10, "fcf": 35, "ncfdebt": 0, "epsdil": 0.5,
}

# ART flows per (ticker, fiscal year); datekey is FY+1 March 1 except
# MONE's FY2017, filed on the last trading day itself (see module doc).
FLOWS = {
    "MONE": {
        2013: dict(revenue=1000, netinc=100, ncfo=150, rnd=50, capex=-100, ncfdiv=-10, ncfcommon=0),
        2014: dict(revenue=1000, netinc=100, ncfo=150, rnd=50, capex=-100, ncfdiv=-10, ncfcommon=0),
        2015: dict(revenue=1000, netinc=100, ncfo=150, rnd=50, capex=-100, ncfdiv=-10, ncfcommon=0),
        2016: dict(revenue=1000, netinc=100, ncfo=150, rnd=50, capex=-100, ncfdiv=-10, ncfcommon=0),
        2017: dict(revenue=2000, netinc=100, ncfo=150, rnd=50, capex=-100, ncfdiv=-10, ncfcommon=0),
    },
    "MTWO": {
        2013: dict(revenue=1000, netinc=50, ncfo=100, rnd=20, capex=-50, ncfdiv=-40, ncfcommon=0),
        2014: dict(revenue=2000, netinc=60, ncfo=100, rnd=20, capex=-50, ncfdiv=-40, ncfcommon=0),
        2015: dict(revenue=4000, netinc=70, ncfo=100, rnd=20, capex=-50, ncfdiv=-40, ncfcommon=0),
        2016: dict(revenue=8000, netinc=80, ncfo=100, rnd=20, capex=-50, ncfdiv=-40, ncfcommon=0),
    },
    "MTHR": {
        2013: dict(revenue=800, netinc=200, ncfo=300, capex=-200, ncfdiv=0, ncfcommon=-120),
        2014: dict(revenue=1000, netinc=200, ncfo=300, capex=-200, ncfdiv=0, ncfcommon=-120),
        2015: dict(revenue=900, netinc=200, ncfo=300, capex=-200, ncfdiv=0, ncfcommon=-120),
        2016: dict(revenue=990, netinc=200, ncfo=300, capex=-200, ncfdiv=0, ncfcommon=-120),
    },
}

MONE_SAME_DAY_FY = 2017


def sf1_rows(ticker: str, datekey: str, reportperiod: str, levels, flows):
    def row(dimension: str, fields: tuple, values: dict) -> str:
        cells = [str(values.get(f, "")) for f in fields]
        blanks = [""] * (len(ARQ_LEVEL_FIELDS) + len(ART_FLOW_FIELDS) - len(fields))
        data = cells + blanks if dimension == "ARQ" else blanks + cells
        return ",".join(
            [ticker, dimension, reportperiod, datekey, reportperiod, "2026-07-01"]
            + data
        )

    return [row("ARQ", ARQ_LEVEL_FIELDS, levels), row("ART", ART_FLOW_FIELDS, flows)]


def build_sf1_csv() -> str:
    header = ",".join(
        ["ticker", "dimension", "calendardate", "datekey", "reportperiod",
         "lastupdated"]
        + list(ARQ_LEVEL_FIELDS)
        + list(ART_FLOW_FIELDS)
    )
    lines = [header]
    for ticker, by_year in FLOWS.items():
        for fy, flows in by_year.items():
            datekey = (
                END.isoformat()
                if (ticker, fy) == ("MONE", MONE_SAME_DAY_FY)
                else f"{fy + 1}-03-01"
            )
            lines += sf1_rows(
                ticker, datekey, f"{fy}-12-31", LEVELS,
                {**FLOW_DEFAULTS, **flows},
            )
    lines += sf1_rows(
        "SOLO", "2015-03-01", "2014-12-31", LEVELS, {"revenue": 400}
    )
    return "\n".join(lines) + "\n"


def weekdays(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def build_sep_csv() -> str:
    lines = ["ticker,date,close,closeadj,volume,lastupdated"]
    for day in weekdays(BASE, END):
        for ticker in ("MONE", "MTHR"):
            px = PRICES[ticker]
            lines.append(f"{ticker},{day},{px},{px},1000,2026-07-01")
        if day <= MTWO_LAST:
            lines.append(f"MTWO,{day},20.0,20.0,1000,2026-07-01")
        if date(2016, 1, 1) <= day <= date(2016, 3, 31):
            lines.append(f"SOLO,{day},5.0,5.0,100,2026-07-01")
    return "\n".join(lines) + "\n"


GUARD_ARGS = ["--rank-guard", "3", "--min-industry-peers", "3"]


@pytest.fixture(scope="module")
def inference_world(tmp_path_factory) -> Path:
    """Data dir with identity + the default (latest as-of) inference run."""
    data_dir = tmp_path_factory.mktemp("inference_world")
    raw = data_dir / "raw"
    for name, csv_text in (
        ("TICKERS", TICKERS_CSV),
        ("SF1", build_sf1_csv()),
        ("SEP", build_sep_csv()),
    ):
        csv_path = data_dir / f"{name}_fixture.csv"
        csv_path.write_text(csv_text)
        csv_to_parquet(csv_path, TABLES[name], raw / f"{name}.parquet")

    assert identity_cli.main(["--data-dir", str(data_dir)]) == 0
    assert inference_cli.main(
        ["--data-dir", str(data_dir)] + GUARD_ARGS
    ) == 0
    return data_dir


def dataset_path(data_dir: Path, as_of: str = "2018-12-31") -> Path:
    return data_dir / "datasets" / f"inference_{as_of}" / "dataset.parquet"


def query(data_dir: Path, sql: str, as_of: str = "2018-12-31"):
    return duckdb.sql(
        sql.format(t=f"'{dataset_path(data_dir, as_of)}'")
    ).fetchall()


def test_cross_section_and_key_columns(inference_world):
    # SOLO (delisted 2016) is out; MTWO snapshots on its own last print.
    rows = query(
        inference_world,
        """
        SELECT permaticker, ticker, quarter, snapshot_kind, snapshot_date,
               entry_closeadj
        FROM {t} ORDER BY permaticker
        """,
    )
    # quarter is TIMESTAMP-typed (date_trunc), same as training snapshots.
    q4 = datetime(2018, 10, 1)
    assert rows == [
        (500001, "MONE", q4, "inference", END, 10.0),
        (500002, "MTWO", q4, "inference", MTWO_LAST, 20.0),
        (500003, "MTHR", q4, "inference", END, 40.0),
    ]


def test_column_layout(inference_world):
    emitted = [
        r[0]
        for r in duckdb.sql(
            f"DESCRIBE SELECT * FROM '{dataset_path(inference_world)}'"
        ).fetchall()
    ]
    assert emitted == (
        ["permaticker", "ticker", "quarter", "snapshot_kind",
         "snapshot_date", "entry_closeadj"]
        + list(feature_columns_in_order())
        + list(rank_columns())
        + list(secrank_columns())
    )
    # Nothing forward-looking leaks in.
    assert not [
        c for c in emitted
        if c.startswith(("fwd_", "label_", "delisted_in_window_", "sample_weight_"))
    ]


def test_same_day_filing_is_used(inference_world):
    # MONE's FY2017 filing has datekey = snapshot_date: the inclusive
    # inference as-of picks it as T0 (age 0), and its lag-1 partner is the
    # FY2016 filing -> revenue growth 2000/1000 - 1.
    assert query(
        inference_world,
        """
        SELECT fund_datekey, fund_reportperiod, fundamentals_age_days,
               has_filing_365d, sales_yield, revenue_growth_1y
        FROM {t} WHERE permaticker = 500001
        """,
    ) == [(END, date(2017, 12, 31), 0, True, pytest.approx(2.0),
           pytest.approx(1.0))]

    # MTWO/MTHR keep their FY2016 filings, aged from their own snapshot date.
    assert query(
        inference_world,
        """
        SELECT permaticker, fund_reportperiod, fundamentals_age_days,
               has_filing_365d
        FROM {t} WHERE permaticker IN (500002, 500003) ORDER BY permaticker
        """,
    ) == [
        (500002, date(2016, 12, 31), (MTWO_LAST - date(2017, 3, 1)).days, False),
        (500003, date(2016, 12, 31), (END - date(2017, 3, 1)).days, False),
    ]


def test_ranks_over_the_inference_cross_section(inference_world):
    # sales_yield: MONE 2000/1000 = 2, MTWO 8000/2000 = 4, MTHR 990/4000 =
    # 0.2475 -> percent ranks 0.5 / 1 / 0; Industrials sector ranks match
    # (all three are Machinery peers at the guard).
    assert query(
        inference_world,
        """
        SELECT permaticker, sales_yield, sales_yield_rank,
               sales_yield_secrank
        FROM {t} ORDER BY permaticker
        """,
    ) == [
        (500001, pytest.approx(2.0), pytest.approx(0.5), pytest.approx(0.5)),
        (500002, pytest.approx(4.0), pytest.approx(1.0), pytest.approx(1.0)),
        (500003, pytest.approx(0.2475), pytest.approx(0.0), pytest.approx(0.0)),
    ]


def test_conservative_score(inference_world):
    # Constant prices: vol_36m and mom_12_2 rank 0 everywhere. Net payout
    # yield 0.01 / 0.02 / 0.03 -> ranks 0 / 0.5 / 1 ->
    # conservative = 1 + npy_rank, ranked 0 / 0.5 / 1.
    assert query(
        inference_world,
        """
        SELECT net_payout_yield, conservative_score, conservative_score_rank
        FROM {t} ORDER BY permaticker
        """,
    ) == [
        (pytest.approx(0.01), pytest.approx(1.0), pytest.approx(0.0)),
        (pytest.approx(0.02), pytest.approx(1.5), pytest.approx(0.5)),
        (pytest.approx(0.03), pytest.approx(2.0), pytest.approx(1.0)),
    ]


def test_manifest(inference_world):
    manifest = json.loads(
        (dataset_path(inference_world).parent / "manifest.json").read_text()
    )
    assert manifest["dataset_kind"] == "inference"
    assert manifest["as_of"] == "2018-12-31"
    assert manifest["params"] == {
        "max_price_age_days": 5, "rank_guard": 3, "min_industry_peers": 3,
    }
    assert manifest["rows"] == 3
    assert manifest["permatickers"] == 3
    assert manifest["rows_with_stale_price"] == 1  # MTWO
    assert manifest["columns"]["features"] == list(feature_columns_in_order())
    assert "labels" not in manifest["columns"]
    assert set(manifest["input_rows"]) == {"SF1", "SEP", "mapping", "universe"}


def test_as_of_in_the_past(inference_world):
    # 2016-02-15 predates SOLO's delisting and the 2016-03-01 filings: four
    # stocks, T0 = FY2014 for the machinery trio -> the same sales_yield
    # ordering as the training 2016-Q1 cross-section.
    assert inference_cli.main(
        ["--data-dir", str(inference_world), "--as-of", "2016-02-15"]
        + GUARD_ARGS
    ) == 0
    rows = query(
        inference_world,
        """
        SELECT permaticker, snapshot_date, sales_yield, sales_yield_rank
        FROM {t} ORDER BY sales_yield, permaticker
        """,
        as_of="2016-02-15",
    )
    d = date(2016, 2, 15)
    assert rows == [
        (500003, d, pytest.approx(0.25), pytest.approx(0.0)),
        (500004, d, pytest.approx(0.8), pytest.approx(1 / 3)),
        (500001, d, pytest.approx(1.0), pytest.approx(2 / 3)),
        (500002, d, pytest.approx(1.0), pytest.approx(2 / 3)),
    ]


def test_price_age_tolerance(inference_world):
    # As of 2018-12-27 with zero tolerance, MTWO (last print 12-26) drops.
    assert inference_cli.main(
        ["--data-dir", str(inference_world), "--as-of", "2018-12-27",
         "--max-price-age-days", "0"] + GUARD_ARGS
    ) == 0
    assert query(
        inference_world,
        "SELECT permaticker FROM {t} ORDER BY permaticker",
        as_of="2018-12-27",
    ) == [(500001,), (500003,)]


def test_inference_directories_are_immutable(inference_world):
    args = ["--data-dir", str(inference_world)] + GUARD_ARGS
    assert inference_cli.main(args) == 1  # refuses to overwrite
    assert inference_cli.main(args + ["--force"]) == 0


def test_missing_inputs(tmp_path):
    assert inference_cli.main(["--data-dir", str(tmp_path)]) == 2
