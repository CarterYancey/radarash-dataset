"""End-to-end tests for the features pipeline on a hand-checkable world.

Synthetic weekday calendar 2015-01-01 .. 2017-12-31, four stocks:

- ACME (400001): constant price 10.0 (all snapshot kinds collapse onto the
  first trading day of each quarter), two annual filings with round-number
  fundamentals (FY2014 filed 2015-03-02, FY2015 filed 2016-03-01) plus an
  FY2015 amendment filed 2016-05-02 restating revenue 600 -> 630. Pins down
  every fundamentals formula, the T0 as-of join, the reportperiod lag
  matching, staleness metadata, and version-of-history semantics (the
  2016-Q2 snapshot must not see the amendment; 2016-Q3 must).
- NEG (400002): the null-rule gauntlet — negative equity/EBITDA/EV, zero
  revenue and intexp, no debt, missing workingcapital/inventory, single
  filing (no lag partner).
- GROW (400003): deterministic 12%/yr exponential growth, no SF1 filings.
  Checks the technical window math on a moving price and that fundamentals
  stay NULL without breaking price-based features.
- BANK (400004): SIC 6021, excluded from the universe -> no feature rows.
- STRAD (400005): trades five days in 2016-Q1 only, with its FY2015 filing
  landing mid-quarter (datekey 2016-02-15) *between* the median/low snapshot
  dates (Jan 4 / Jan 15) and the high date (Mar 15). Pins the straddle rule:
  fundamentals resolve strictly per snapshot_date, so same-quarter kinds on
  opposite sides of a filing use different filings.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from features import cli as features_cli
from features.registry import FAMILIES
from features.source import ARQ_LEVEL_FIELDS, ART_FLOW_FIELDS
from identity import cli as identity_cli
from ingest.convert import csv_to_parquet
from ingest.tables import TABLES
from labels import cli as labels_cli

BASE = date(2015, 1, 1)
END = date(2017, 12, 31)

TICKERS_CSV = """\
table,permaticker,ticker,name,exchange,category,sector,industry,famaindustry,siccode,scalemarketcap,isdelisted,firstpricedate,lastpricedate,lastupdated
SEP,400001,ACME,Acme Industries,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,N,2015-01-01,2017-12-31,2026-07-01
SEP,400002,NEG,Negative Corp,OTC,Domestic Common Stock,Healthcare,Biotechnology,Pharmaceuticals,2836,2 - Micro,Y,2015-01-01,2016-12-31,2026-07-01
SEP,400003,GROW,Growth Corp,NYSE,Domestic Common Stock,Technology,Software - Application,Business Services,7372,4 - Mid,N,2015-01-01,2017-12-31,2026-07-01
SEP,400004,BANK,Big Bank,NYSE,Domestic Common Stock,Financial Services,Banks,Banking,6021,5 - Large,N,2015-01-01,2017-12-31,2026-07-01
SEP,400005,STRAD,Straddle Corp,OTC,Domestic Common Stock,Industrials,Machinery,Machinery,3550,2 - Micro,Y,2016-01-04,2016-03-31,2026-07-01
"""

STRAD_PRICES = {
    date(2016, 1, 4): 20.0,   # median (tie -> earliest)
    date(2016, 1, 15): 10.0,  # low, before the 2016-02-15 filing
    date(2016, 2, 1): 20.0,
    date(2016, 3, 15): 30.0,  # high, after the 2016-02-15 filing
    date(2016, 3, 31): 20.0,
}

ACTIONS_CSV = """\
date,action,ticker,name,contraticker,contraname
2016-06-01,split,GROW,Growth Corp,,
"""

ACME_FY2014_LEVELS = {
    "assets": 1000, "assetsc": 400, "cashneq": 100, "receivables": 80,
    "inventory": 50, "ppnenet": 300, "investments": 20, "liabilities": 600,
    "liabilitiesc": 200, "debt": 250, "debtnc": 150, "equity": 400,
    "retearn": 120, "workingcapital": 200, "tangibles": 900, "invcap": 650,
    "sharesbas": 100, "sharefactor": 1,
}
ACME_FY2014_FLOWS = {
    "revenue": 500, "gp": 200, "sgna": 100, "depamor": 30, "ebit": 70,
    "ebitda": 100, "intexp": 10, "netinc": 40, "ncfo": 60, "fcf": 35,
    "ncfcommon": -5, "ncfdebt": 10, "ncfdiv": -8, "epsdil": 0.4,
}
ACME_FY2015_LEVELS = {
    "assets": 1200, "assetsc": 480, "cashneq": 150, "receivables": 90,
    "inventory": 60, "ppnenet": 330, "investments": 30, "liabilities": 660,
    "liabilitiesc": 220, "debt": 260, "debtnc": 140, "equity": 540,
    "retearn": 160, "workingcapital": 260, "tangibles": 1080, "invcap": 700,
    "sharesbas": 110, "sharefactor": 1,
}
ACME_FY2015_FLOWS = {
    "revenue": 600, "gp": 270, "sgna": 110, "depamor": 33, "ebit": 90,
    "ebitda": 123, "intexp": 9, "netinc": 60, "ncfo": 90, "fcf": 50,
    "ncfcommon": 4, "ncfdebt": -10, "ncfdiv": -10, "epsdil": 0.55,
    "rnd": 12, "capex": -25,
}
NEG_FY2015_LEVELS = {
    "assets": 500, "assetsc": 100, "cashneq": 200, "ppnenet": 100,
    "liabilities": 600, "liabilitiesc": 150, "debt": 0, "debtnc": 0,
    "equity": -100, "retearn": -300, "sharesbas": 50, "sharefactor": 1,
}
NEG_FY2015_FLOWS = {
    "revenue": 0, "ebit": -30, "ebitda": -20, "intexp": 0, "netinc": -50,
    "ncfo": -10, "ncfcommon": 20, "ncfdebt": 0, "ncfdiv": 0, "epsdil": -1.0,
}


def sf1_rows(ticker: str, datekey: str, reportperiod: str, levels, flows):
    def row(dimension: str, fields: tuple, values: dict) -> str:
        cells = [str(values.get(f, "")) for f in fields]
        blanks = [""] * (len(ARQ_LEVEL_FIELDS) + len(ART_FLOW_FIELDS) - len(fields))
        if dimension == "ARQ":
            data = cells + blanks
        else:
            data = blanks + cells
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
    lines += sf1_rows("ACME", "2015-03-02", "2014-12-31",
                      ACME_FY2014_LEVELS, ACME_FY2014_FLOWS)
    lines += sf1_rows("ACME", "2016-03-01", "2015-12-31",
                      ACME_FY2015_LEVELS, ACME_FY2015_FLOWS)
    # FY2015 amendment: revenue restated 600 -> 630, everything else equal.
    lines += sf1_rows("ACME", "2016-05-02", "2015-12-31",
                      ACME_FY2015_LEVELS, {**ACME_FY2015_FLOWS, "revenue": 630})
    lines += sf1_rows("NEG", "2016-03-01", "2015-12-31",
                      NEG_FY2015_LEVELS, NEG_FY2015_FLOWS)
    strad_levels = {"assets": 400, "sharesbas": 10, "sharefactor": 1}
    lines += sf1_rows("STRAD", "2015-05-01", "2014-12-31",
                      strad_levels, {"revenue": 100})
    lines += sf1_rows("STRAD", "2016-02-15", "2015-12-31",
                      strad_levels, {"revenue": 200})
    return "\n".join(lines) + "\n"


def weekdays(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


def grow_price(day: date) -> float:
    return 100.0 * 1.12 ** ((day - BASE).days / 365.25)


def build_sep_csv() -> str:
    lines = ["ticker,date,close,closeadj,volume,lastupdated"]
    for day in weekdays(BASE, END):
        lines.append(f"ACME,{day},10.0,10.0,1000,2026-07-01")
        lines.append(
            f"GROW,{day},{grow_price(day)!r},{grow_price(day)!r},2000,2026-07-01"
        )
        lines.append(f"BANK,{day},25.0,25.0,3000,2026-07-01")
        if day <= date(2016, 12, 31):
            lines.append(f"NEG,{day},1.0,1.0,500,2026-07-01")
        if day in STRAD_PRICES:
            px = STRAD_PRICES[day]
            lines.append(f"STRAD,{day},{px!r},{px!r},100,2026-07-01")
    return "\n".join(lines) + "\n"


def build_sfp_csv() -> str:
    lines = ["ticker,date,close,closeadj,lastupdated"]
    for day in weekdays(BASE, END):
        lines.append(f"SPY,{day},100.0,100.0,2026-07-01")
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def features_world(tmp_path_factory) -> Path:
    """Data dir with identity + labels + features already run."""
    data_dir = tmp_path_factory.mktemp("features_world")
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
    assert features_cli.main(["--data-dir", str(data_dir)]) == 0
    return data_dir


def query(data_dir: Path, family: str, sql: str):
    path = data_dir / "interim" / "features" / f"{family}.parquet"
    return duckdb.sql(sql.format(t=f"'{path}'")).fetchall()


def one_row(data_dir: Path, family: str, sql: str):
    rows = query(data_dir, family, sql)
    assert len(rows) == 1, rows
    return rows[0]


def acme(data_dir: Path, family: str, columns: str, snapshot_date: str):
    return one_row(
        data_dir,
        family,
        f"""
        SELECT {columns} FROM {{t}}
        WHERE permaticker = 400001 AND snapshot_kind = 'median'
          AND snapshot_date = DATE '{snapshot_date}'
        """,
    )


def test_outputs_exist_with_shared_key_and_counts(features_world):
    # ACME 12 quarters, NEG 8, GROW 12, STRAD 1 -> 33 quarters x 3 kinds;
    # BANK none.
    for family in FAMILIES:
        rows = query(
            features_world,
            family,
            "SELECT count(*), count(DISTINCT permaticker) FROM {t}",
        )
        assert rows == [(99, 4)], family


def test_meta_staleness_and_provenance(features_world):
    row = acme(
        features_world,
        "meta",
        "fund_datekey, fund_reportperiod, fundamentals_age_days, "
        "has_filing_183d, has_filing_365d, negative_equity, "
        "negative_ebitda, negative_ev",
        "2016-04-01",
    )
    assert row == (
        date(2016, 3, 1), date(2015, 12, 31), 31,
        True, True, False, False, False,
    )

    # 305 days after the FY2014 filing: outside 183d, inside 365d.
    row = acme(
        features_world,
        "meta",
        "fund_datekey, fundamentals_age_days, has_filing_183d, has_filing_365d",
        "2016-01-01",
    )
    assert row == (date(2015, 3, 2), 305, False, True)

    # Before the first filing: NULL provenance, flags determinably false,
    # sign flags unknown (ADR 0006).
    row = acme(
        features_world,
        "meta",
        "fund_datekey, fundamentals_age_days, has_filing_183d, "
        "has_filing_365d, negative_equity",
        "2015-01-01",
    )
    assert row == (None, None, False, False, None)


def test_amendment_is_invisible_until_filed(features_world):
    # 2016-Q2 predates the 2016-05-02 amendment: original revenue 600.
    assert acme(features_world, "growth", "revenue_growth_1y", "2016-04-01") == (
        pytest.approx(0.2),
    )
    # 2016-Q3 sees the amendment (freshest datekey): revenue 630.
    row = acme(
        features_world, "meta", "fund_datekey, fundamentals_age_days", "2016-07-01"
    )
    assert row == (date(2016, 5, 2), 60)
    assert acme(features_world, "growth", "revenue_growth_1y", "2016-07-01") == (
        pytest.approx(0.26),
    )


def test_acme_valuation(features_world):
    row = acme(
        features_world,
        "valuation",
        "earnings_yield, ocf_yield, fcf_yield, sales_yield, book_to_market, "
        "tangible_book_to_market, ebit_to_ev, ebitda_to_ev, dividend_yield, "
        "net_payout_yield, ncav_to_marketcap, ev_to_marketcap",
        "2016-04-01",
    )
    # marketcap = 10 * 110 = 1100; ev = 1100 + 260 - 150 = 1210.
    assert row == pytest.approx(
        (60 / 1100, 90 / 1100, 50 / 1100, 600 / 1100, 540 / 1100,
         1080 / 1100, 90 / 1210, 123 / 1210, 10 / 1100, 6 / 1100,
         -180 / 1100, 1210 / 1100)
    )


def test_acme_profitability(features_world):
    row = acme(
        features_world,
        "profitability",
        "gp_to_assets, roa, roe, ebit_to_invcap, roc_greenblatt, "
        "gross_margin, operating_margin, net_margin, fcf_margin, "
        "cfo_to_assets, asset_turnover",
        "2016-04-01",
    )
    assert row == pytest.approx(
        (270 / 1200, 0.05, 60 / 540, 90 / 700, 90 / 590,
         0.45, 0.15, 0.10, 50 / 600, 0.075, 0.5)
    )


def test_acme_growth(features_world):
    row = acme(
        features_world,
        "growth",
        "revenue_growth_1y, revenue_growth_3y, epsdil_growth_1y, "
        "roa_delta_1y, gross_margin_delta_1y, gross_margin_delta_2y, "
        "asset_turnover_delta_1y, asset_growth_1y, share_count_growth_1y",
        "2016-04-01",
    )
    assert row[1] is None  # no FY2012 partner
    assert row[5] is None  # no FY2013 partner
    assert (row[0], row[2], row[3], row[4], row[6], row[7], row[8]) == (
        pytest.approx(0.2),
        pytest.approx(0.375),
        pytest.approx(0.05 - 0.04),
        pytest.approx(0.45 - 0.40),
        pytest.approx(0.0),
        pytest.approx(0.2),
        pytest.approx(0.1),
    )

    # T0 = FY2014 with no FY2013 partner: the whole family is NULL.
    row = acme(features_world, "growth", "*", "2016-01-01")
    assert all(v is None for v in row[3:])


def test_acme_solvency(features_world):
    row = acme(
        features_world,
        "solvency",
        "wc_to_assets, retearn_to_assets, ebit_to_assets, "
        "marketcap_to_liabilities, equity_to_liabilities, "
        "liabilities_to_assets, cl_to_ca, current_ratio, quick_ratio, "
        "cash_to_assets, debt_to_equity, net_debt_to_ebitda, "
        "interest_coverage, ffo_to_liabilities, log_assets, "
        "ni_change_scaled, two_year_loss, liab_gt_assets",
        "2016-04-01",
    )
    assert row[:16] == pytest.approx(
        (260 / 1200, 160 / 1200, 0.075, 1100 / 660, 540 / 660, 0.55,
         220 / 480, 480 / 220, 420 / 220, 0.125, 260 / 540, 110 / 123,
         10.0, 90 / 660, math.log(1200), 0.2)
    )
    assert row[16:] == (False, False)

    wc_ta, re_ta, ebit_ta = 260 / 1200, 160 / 1200, 90 / 1200
    z, z_dd, zmij = acme(
        features_world, "solvency", "altman_z, altman_z_dd, zmijewski",
        "2016-04-01",
    )
    assert z == pytest.approx(
        1.2 * wc_ta + 1.4 * re_ta + 3.3 * ebit_ta + 0.6 * (1100 / 660) + 0.5
    )
    assert z_dd == pytest.approx(
        6.56 * wc_ta + 3.26 * re_ta + 6.72 * ebit_ta + 1.05 * (540 / 660)
    )
    assert zmij == pytest.approx(
        -4.336 - 4.513 * 0.05 + 5.679 * 0.55 + 0.004 * (480 / 220)
    )


def test_acme_quality(features_world):
    row = acme(
        features_world,
        "quality",
        "dsri, gmi, aqi, sgi, depi, sgai, lvgi, accruals_to_assets, "
        "beneish_m, piotroski_f, noa_to_assets, ext_financing_to_assets",
        "2016-04-01",
    )
    dsri, gmi = 0.15 / 0.16, 0.40 / 0.45
    aqi, sgi, depi = 0.325 / 0.30, 1.2, 1.0
    sgai, lvgi, tata = (110 / 600) / 0.2, 0.40 / 0.45, -30 / 1200
    beneish = (
        -4.84 + 0.92 * dsri + 0.528 * gmi + 0.404 * aqi + 0.892 * sgi
        + 0.115 * depi - 0.172 * sgai + 4.679 * tata - 0.327 * lvgi
    )
    # F-score: signals 1-6 and 8 pass; 7 fails (ncfcommon = 4 > 0) and
    # 9 fails (asset turnover flat at 0.5 -> not an increase).
    assert row == pytest.approx(
        (dsri, gmi, aqi, sgi, depi, sgai, lvgi, tata, beneish, 7,
         0.62, -0.005)
    )

    # ADR 0013 G-score inputs: rnd/capex are T0 intensities; the FY2014
    # filing reports neither, so unreported R&D counts as 0 while capex
    # stays NULL. Variabilities need four annual filings - ACME has two.
    assert acme(
        features_world,
        "quality",
        "rnd_to_assets, capex_to_assets, roa_variability_3y, "
        "revenue_growth_variability_3y",
        "2016-04-01",
    ) == (pytest.approx(12 / 1200), pytest.approx(25 / 1200), None, None)
    assert acme(
        features_world,
        "quality",
        "rnd_to_assets, capex_to_assets",
        "2016-01-01",
    ) == (0.0, None)


def neg_row(features_world, family: str, columns: str):
    return one_row(
        features_world,
        family,
        f"""
        SELECT {columns} FROM {{t}}
        WHERE permaticker = 400002 AND snapshot_kind = 'median'
          AND snapshot_date = DATE '2016-04-01'
        """,
    )


def test_neg_null_rules(features_world):
    assert neg_row(
        features_world, "meta", "negative_equity, negative_ebitda, negative_ev"
    ) == (True, True, True)

    # marketcap = 1 * 50 = 50; ev = 50 + 0 - 200 = -150.
    row = neg_row(
        features_world,
        "valuation",
        "earnings_yield, book_to_market, ebit_to_ev, ebitda_to_ev, "
        "ev_to_marketcap, dividend_yield",
    )
    assert row == (-1.0, -2.0, None, None, -3.0, 0.0)

    row = neg_row(
        features_world,
        "profitability",
        "roe, gross_margin, net_margin, roa, roc_greenblatt",
    )
    assert row == (None, None, None, pytest.approx(-0.1), None)

    row = neg_row(
        features_world,
        "solvency",
        "interest_coverage, net_debt_to_ebitda, debt_to_equity, "
        "wc_to_assets, quick_ratio, current_ratio, liab_gt_assets, "
        "two_year_loss, altman_z",
    )
    assert row == (
        None, None, None, None, None, pytest.approx(100 / 150), True,
        None, None,
    )

    # Single filing: every lagged feature is NULL.
    row = neg_row(features_world, "growth", "*")
    assert all(v is None for v in row[3:])
    assert neg_row(features_world, "quality", "piotroski_f, beneish_m") == (
        None, None,
    )


def grow_row(features_world, columns: str, snapshot_date: str):
    return one_row(
        features_world,
        "technical",
        f"""
        SELECT {columns} FROM {{t}}
        WHERE permaticker = 400003 AND snapshot_kind = 'low'
          AND snapshot_date = DATE '{snapshot_date}'
        """,
    )


def test_technical_constant_price(features_world):
    row = acme(
        features_world,
        "technical",
        "mom_12_2, ret_6m, ret_1m, vol_12m, vol_36m, dist_52w_high, "
        "log_marketcap, dollar_volume_3m, amihud_12m",
        "2016-04-01",
    )
    mom, r6, r1, v12, v36, dist, logmc, dv, amihud = row
    assert (mom, r6, r1, v12, dist, amihud) == (0, 0, 0, 0, 0, 0)
    assert v36 is None  # only ~325 return obs by 2016-04-01, guard is 600
    assert logmc == pytest.approx(math.log(1100))
    assert dv == pytest.approx(10_000.0)


def test_technical_growth_stock(features_world):
    # Monotonic 12%/yr growth, low-kind snapshot = first trading day of Q4
    # 2017 (2017-10-02). Offsets in trading days land ~29/182/333 calendar
    # days back, so returns sit near 1.12^(days/365.25) - 1.
    row = grow_row(
        features_world,
        "mom_12_2, ret_6m, ret_1m, vol_12m, vol_36m, dist_52w_high, "
        "log_marketcap, dollar_volume_3m, amihud_12m",
        "2017-10-02",
    )
    mom, r6, r1, v12, v36, dist, logmc, dv, amihud = row
    assert 0.08 < mom < 0.12
    assert 0.04 < r6 < 0.07
    assert 0.005 < r1 < 0.012
    assert 0 < v12 < 0.01  # weekend gaps make tiny but nonzero volatility
    assert 0 < v36 < 0.01  # >600 obs by late 2017
    assert dist == pytest.approx(0.0)  # monotonic growth: today is the high
    assert logmc is None  # GROW has no filings -> no share count
    assert 250_000 < dv < 290_000  # price ~135 x volume 2000
    assert 0 < amihud < 1e-6


def test_same_quarter_kinds_straddling_a_filing(features_world):
    # STRAD's FY2015 filing (datekey 2016-02-15) lands between the
    # median/low snapshot dates and the high date of the same quarter:
    # fundamentals must resolve per snapshot_date, not per quarter.
    rows = query(
        features_world,
        "meta",
        """
        SELECT snapshot_kind, snapshot_date, fund_datekey, fund_reportperiod
        FROM {t} WHERE permaticker = 400005 ORDER BY snapshot_date
        """,
    )
    assert rows == [
        ("median", date(2016, 1, 4), date(2015, 5, 1), date(2014, 12, 31)),
        ("low", date(2016, 1, 15), date(2015, 5, 1), date(2014, 12, 31)),
        ("high", date(2016, 3, 15), date(2016, 2, 15), date(2015, 12, 31)),
    ]

    # The straddle shows up in values too: revenue 100 before the filing,
    # 200 after; marketcap = entry close x 10 shares.
    rows = query(
        features_world,
        "valuation",
        """
        SELECT snapshot_kind, sales_yield FROM {t}
        WHERE permaticker = 400005 ORDER BY snapshot_date
        """,
    )
    assert rows == [
        ("median", pytest.approx(100 / 200)),
        ("low", pytest.approx(100 / 100)),
        ("high", pytest.approx(200 / 300)),
    ]


def test_classification(features_world):
    assert acme(
        features_world,
        "classification",
        "sector, industry, famaindustry, scalemarketcap, siccode",
        "2016-04-01",
    ) == ("Industrials", "Machinery", "Machinery", "3 - Small", 3500)


def test_missing_inputs(tmp_path):
    assert features_cli.main(["--data-dir", str(tmp_path)]) == 2
