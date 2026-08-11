"""End-to-end tests for the index-membership family (ADR 0015).

Synthetic weekday calendar 2015-01-01 .. 2017-12-31. Prices are constant per
stock, so all three snapshot kinds collapse onto the first trading day of
each quarter and every assertion below is hand-checkable:

- MSFT (500001) — a Dow constituent for the whole world (its spell in
  `reference/dow_membership.csv` is open-ended) and an S&P 500 constituent
  from the action table's first date via a `historical` row. Biggest market
  cap, so it also heads the Russell ranking.
- ACME (500002) — added to the S&P 500 on 2016-02-01 and removed on
  2017-05-01: the ordinary spell case.
- WBA  (500003) — its only S&P 500 action is a `removed` on 2017-08-01, so
  the seeding rule must make it a member from the table's first date. Its
  Dow spell (2018-06-26 onward) starts after this world ends, which must
  read as false, not true.
- NOFIL (500004) — no SF1 filings, hence no market cap on any ranking day:
  outside the Russell proxy (false), never NULL.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from features import cli as features_cli
from features.indexes import load_dow_spells
from features.source import ARQ_LEVEL_FIELDS, ART_FLOW_FIELDS
from identity import cli as identity_cli
from ingest.convert import csv_to_parquet
from ingest.tables import TABLES
from labels import cli as labels_cli

BASE = date(2015, 1, 1)
END = date(2017, 12, 31)

# ticker -> (permaticker, close, shares)
STOCKS = {
    "MSFT": (500001, 100.0, 1000),
    "ACME": (500002, 10.0, 100),
    "WBA": (500003, 5.0, 100),
    "NOFIL": (500004, 20.0, None),
}

SP500_COVERAGE_START = date(2015, 1, 5)
RUSSELL_COVERAGE_START = date(2015, 7, 1)  # first trading day >= July 1, 2015

TICKERS_CSV = """\
table,permaticker,ticker,name,exchange,category,sector,industry,famaindustry,siccode,scalemarketcap,isdelisted,firstpricedate,lastpricedate,lastupdated
SEP,500001,MSFT,Microsoft Corp,NASDAQ,Domestic Common Stock,Technology,Software,Business Services,7372,6 - Mega,N,2015-01-01,2017-12-31,2026-07-01
SEP,500002,ACME,Acme Industries,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,N,2015-01-01,2017-12-31,2026-07-01
SEP,500003,WBA,Walgreens Boots,NASDAQ,Domestic Common Stock,Healthcare,Pharma Retail,Retail,5912,4 - Mid,N,2015-01-01,2017-12-31,2026-07-01
SEP,500004,NOFIL,No Filings Corp,OTC,Domestic Common Stock,Industrials,Machinery,Machinery,3520,2 - Micro,N,2015-01-01,2017-12-31,2026-07-01
"""

# Constituent actions: a `historical` seed row, an ordinary added/removed
# pair, a bare `removed` (seeded member), and a no-op `current` row.
SP500_CSV = """\
ticker,date,action,name,contraticker,contraname
MSFT,2015-01-05,historical,Microsoft Corp,,
ACME,2016-02-01,added,Acme Industries,,
ACME,2017-05-01,removed,Acme Industries,,
WBA,2017-08-01,removed,Walgreens Boots,,
MSFT,2017-12-29,current,Microsoft Corp,,
"""

ACTIONS_CSV = """\
date,action,ticker,name,contraticker,contraname
2016-06-01,split,ACME,Acme Industries,,
"""


def weekdays(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def build_sep_csv() -> str:
    lines = ["ticker,date,close,closeadj,volume,lastupdated"]
    for day in weekdays(BASE, END):
        for ticker, (_, close, _) in STOCKS.items():
            lines.append(f"{ticker},{day},{close!r},{close!r},1000,2026-07-01")
    return "\n".join(lines) + "\n"


def build_sfp_csv() -> str:
    lines = ["ticker,date,close,closeadj,lastupdated"]
    for day in weekdays(BASE, END):
        lines.append(f"SPY,{day},100.0,100.0,2026-07-01")
    return "\n".join(lines) + "\n"


def build_sf1_csv() -> str:
    """One FY2014 filing per stock that has shares outstanding."""
    header = ",".join(
        ["ticker", "dimension", "calendardate", "datekey", "reportperiod",
         "lastupdated"]
        + list(ARQ_LEVEL_FIELDS)
        + list(ART_FLOW_FIELDS)
    )
    lines = [header]
    for ticker, (_, _, shares) in STOCKS.items():
        if shares is None:
            continue
        # Every field carries a number so the CSV sniffer types the whole
        # export numerically; only the share count varies across stocks.
        levels = {field: 100 for field in ARQ_LEVEL_FIELDS}
        levels |= {"assets": 1000, "sharesbas": shares, "sharefactor": 1}
        flows = {field: 50 for field in ART_FLOW_FIELDS}
        for dimension, fields, values in (
            ("ARQ", ARQ_LEVEL_FIELDS, levels),
            ("ART", ART_FLOW_FIELDS, flows),
        ):
            cells = [str(values.get(f, "")) for f in fields]
            blanks = [""] * (
                len(ARQ_LEVEL_FIELDS) + len(ART_FLOW_FIELDS) - len(fields)
            )
            data = cells + blanks if dimension == "ARQ" else blanks + cells
            lines.append(
                ",".join(
                    [ticker, dimension, "2014-12-31", "2015-03-02",
                     "2014-12-31", "2026-07-01"]
                    + data
                )
            )
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def index_world(tmp_path_factory) -> Path:
    """Data dir with identity + labels + features already run."""
    data_dir = tmp_path_factory.mktemp("index_world")
    raw = data_dir / "raw"
    for name, csv_text in (
        ("TICKERS", TICKERS_CSV),
        ("SF1", build_sf1_csv()),
        ("SEP", build_sep_csv()),
        ("SFP", build_sfp_csv()),
        ("ACTIONS", ACTIONS_CSV),
        ("SP500", SP500_CSV),
    ):
        csv_path = data_dir / f"{name}_fixture.csv"
        csv_path.write_text(csv_text)
        csv_to_parquet(csv_path, TABLES[name], raw / f"{name}.parquet")

    assert identity_cli.main(["--data-dir", str(data_dir)]) == 0
    assert labels_cli.main(["--data-dir", str(data_dir)]) == 0
    assert features_cli.main(["--data-dir", str(data_dir)]) == 0
    return data_dir


def row(data_dir: Path, ticker: str, snapshot_date: str, columns: str):
    path = data_dir / "interim" / "features" / "index.parquet"
    permaticker = STOCKS[ticker][0]
    rows = duckdb.sql(
        f"""
        SELECT {columns} FROM '{path}'
        WHERE permaticker = {permaticker} AND snapshot_kind = 'median'
          AND snapshot_date = DATE '{snapshot_date}'
        """
    ).fetchall()
    assert len(rows) == 1, rows
    return rows[0]


def test_one_row_per_snapshot(index_world):
    path = index_world / "interim" / "features" / "index.parquet"
    labels = index_world / "interim" / "labels.parquet"
    counts = duckdb.sql(
        f"""
        SELECT (SELECT count(*) FROM '{path}'),
               (SELECT count(*) FROM '{labels}'),
               (SELECT count(*) FROM (
                    SELECT DISTINCT permaticker, snapshot_date, snapshot_kind
                    FROM '{path}'))
        """
    ).fetchone()
    # 4 stocks x 12 quarters x 3 kinds, exactly aligned with labels.
    assert counts == (144, 144, 144)


def test_membership_is_null_before_an_index_starts(index_world):
    # 2015-01-01 precedes both the SP500 table's first action (2015-01-05)
    # and the first Russell reconstitution (2015-07-01); the Dow file covers
    # 1999 onward, so only that column is known.
    assert row(
        index_world,
        "MSFT",
        "2015-01-01",
        "in_sp500, days_in_sp500, in_russell1000, in_russell3000, in_dow",
    ) == (None, None, None, None, True)


def test_sp500_spell_from_added_and_removed(index_world):
    assert row(index_world, "ACME", "2015-04-01", "in_sp500, days_in_sp500") == (
        False,
        None,
    )
    # Added 2016-02-01: the 2016-04-01 snapshot is a member, tenure exact.
    tenure = (date(2016, 4, 1) - date(2016, 2, 1)).days
    assert row(index_world, "ACME", "2016-04-01", "in_sp500, days_in_sp500") == (
        True,
        float(tenure),
    )
    # Removed 2017-05-01: still a member on 2017-04-03, gone by 2017-07-03.
    assert row(index_world, "ACME", "2017-04-03", "in_sp500")[0] is True
    assert row(index_world, "ACME", "2017-07-03", "in_sp500, days_in_sp500") == (
        False,
        None,
    )


def test_sp500_seeds_members_whose_first_action_is_not_added(index_world):
    # WBA's only action is a 2017-08-01 removal, so it must count as a member
    # from the table's first date, with tenure measured from there.
    tenure = (date(2015, 4, 1) - SP500_COVERAGE_START).days
    assert row(index_world, "WBA", "2015-04-01", "in_sp500, days_in_sp500") == (
        True,
        float(tenure),
    )
    assert row(index_world, "WBA", "2017-07-03", "in_sp500")[0] is True
    assert row(index_world, "WBA", "2017-10-02", "in_sp500")[0] is False


def test_historical_and_current_rows_keep_a_continuous_spell(index_world):
    tenure = (date(2017, 10, 2) - SP500_COVERAGE_START).days
    assert row(index_world, "MSFT", "2017-10-02", "in_sp500, days_in_sp500") == (
        True,
        float(tenure),
    )


def test_dow_membership_comes_from_the_checked_in_history(index_world):
    # MSFT's spell is open-ended; ACME is not a Dow name; WBA's spell starts
    # in 2018, after this world ends.
    for ticker, expected in (("MSFT", True), ("ACME", False), ("WBA", False)):
        assert row(index_world, ticker, "2016-07-01", "in_dow")[0] is expected
    tenure = (date(2016, 7, 1) - date(1999, 11, 1)).days
    assert row(index_world, "MSFT", "2016-07-01", "days_in_dow") == (float(tenure),)


def test_russell_proxy_ranks_the_cross_section(index_world):
    cols = "in_russell1000, in_russell2000, in_russell3000"
    # Three ranked stocks in a four-stock world: all inside the top 1000.
    for ticker in ("MSFT", "ACME", "WBA"):
        assert row(index_world, ticker, "2016-01-01", cols) == (True, False, True)
    # NOFIL has no filing, so no market cap on the ranking day: outside the
    # proxy index (false), not unknown.
    assert row(index_world, "NOFIL", "2016-01-01", cols) == (False, False, False)


def test_major_index_is_the_union(index_world):
    # NOFIL: not in any index, but the Dow column is known -> false, not NULL.
    assert row(index_world, "NOFIL", "2016-01-01", "in_major_index")[0] is False
    assert row(index_world, "ACME", "2016-04-01", "in_major_index")[0] is True
    # 2015-01-01: S&P 500 and Russell unknown, Dow true -> true.
    assert row(index_world, "MSFT", "2015-01-01", "in_major_index")[0] is True


def test_sp500_columns_are_null_without_the_ingested_table(tmp_path):
    """A data dir built before SP500 was ingested still runs (ADR 0015)."""
    data_dir = tmp_path / "no_sp500"
    raw = data_dir / "raw"
    for name, csv_text in (
        ("TICKERS", TICKERS_CSV),
        ("SF1", build_sf1_csv()),
        ("SEP", build_sep_csv()),
        ("SFP", build_sfp_csv()),
        ("ACTIONS", ACTIONS_CSV),
    ):
        csv_path = data_dir / f"{name}_fixture.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text(csv_text)
        csv_to_parquet(csv_path, TABLES[name], raw / f"{name}.parquet")
    assert identity_cli.main(["--data-dir", str(data_dir)]) == 0
    assert labels_cli.main(["--data-dir", str(data_dir)]) == 0
    assert features_cli.main(["--data-dir", str(data_dir)]) == 0

    path = data_dir / "interim" / "features" / "index.parquet"
    assert duckdb.sql(
        f"""
        SELECT count(*), count(in_sp500), count(days_in_sp500), count(in_dow)
        FROM '{path}'
        """
    ).fetchone() == (144, 0, 0, 144)


# ---- the checked-in Dow history, no data required -------------------------


def members_on(day: date) -> set[str]:
    return {
        ticker
        for ticker, start, end in load_dow_spells()
        if date.fromisoformat(start) <= day <= date.fromisoformat(end)
    }


@pytest.mark.parametrize(
    "day",
    [
        "1999-11-01", "1999-12-01", "2002-05-06", "2004-04-08", "2005-11-21",
        "2008-02-19", "2008-09-22", "2009-06-08", "2012-09-24", "2013-09-20",
        "2015-03-19", "2018-06-26", "2019-04-02", "2020-08-31", "2024-02-26",
        "2024-11-08", "2026-01-02",
    ],
)
def test_dow_file_always_holds_thirty_names(day):
    assert len(members_on(date.fromisoformat(day))) == 30, day


def test_dow_spells_of_one_ticker_never_overlap():
    spells: dict[str, list[tuple[str, str]]] = {}
    for ticker, start, end in load_dow_spells():
        spells.setdefault(ticker, []).append((start, end))
    for ticker, windows in spells.items():
        windows.sort()
        for (_, prev_end), (next_start, _) in zip(windows, windows[1:]):
            assert prev_end < next_start, ticker
