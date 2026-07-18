"""End-to-end tests for `sharadar-qa splits-diag` on a hand-checkable world.

Synthetic weekday calendar 2015-01-01 .. 2017-12-31, two stocks with quarterly
filings (constant fundamentals, filed 45 days after each period end,
2013-Q4 .. 2017-Q3 periods):

- SPIKE (600001): price 100 every day EXCEPT the quarter's 5th weekday
  (2015-01-07, price 50) and 6th weekday (2015-01-08, price 200) of 2015-Q1
  only. So exactly one quarter has spread kinds (low = Jan 7, high = Jan 8,
  median = Jan 1) and every other quarter's kinds collapse onto the first
  weekday. Because no later spikes exist, every terminal window averages
  exactly 100, giving exact labels for 2015-Q1: 1y CAGR low = +100%,
  median = 0%, high = -50%; 2y low = sqrt(2)-1, high = sqrt(.5)-1. An
  amendment of the 2014-09-30 period (revenue 1000 -> 2000) filed on
  2015-01-07 lands *between* the low and high dates: the high kind reads
  revenue 2000 while low/median read 1000 — one filing-straddle quarter.
- FLAT (600002): constant price 20 — all kinds collapse, all CAGRs exactly
  0%, nothing ever differs or flips.

SPY is constant, so beat_spy is CAGR > 0.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from features import cli as features_cli
from features.source import ARQ_LEVEL_FIELDS, ART_FLOW_FIELDS
from identity import cli as identity_cli
from ingest.convert import csv_to_parquet
from ingest.tables import TABLES
from labels import cli as labels_cli
from qa import cli as qa_cli

BASE = date(2015, 1, 1)
END = date(2017, 12, 31)

TICKERS_CSV = """\
table,permaticker,ticker,name,exchange,category,sector,industry,famaindustry,siccode,scalemarketcap,isdelisted,firstpricedate,lastpricedate,lastupdated
SEP,600001,SPIKE,Spike Corp,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,N,2015-01-01,2017-12-31,2026-07-01
SEP,600002,FLAT,Flat Corp,NYSE,Domestic Common Stock,Technology,Software - Application,Business Services,7372,3 - Small,N,2015-01-01,2017-12-31,2026-07-01
"""

ACTIONS_CSV = """\
date,action,ticker,name,contraticker,contraname
2016-06-01,split,SPIKE,Spike Corp,,
"""

SPIKE_PRICES = {date(2015, 1, 7): 50.0, date(2015, 1, 8): 200.0}

# Every SF1 field gets a value so the CSV converter can type every column.
SPIKE_LEVELS = {
    "assets": 1000, "assetsc": 400, "cashneq": 100, "receivables": 80,
    "inventory": 50, "ppnenet": 300, "investments": 20, "liabilities": 400,
    "liabilitiesc": 150, "debt": 200, "debtnc": 100, "equity": 600,
    "retearn": 250, "workingcapital": 250, "tangibles": 900, "invcap": 700,
    "sharesbas": 100, "sharefactor": 1,
}
SPIKE_FLOWS = {
    "revenue": 1000, "gp": 400, "sgna": 200, "depamor": 50, "ebit": 150,
    "ebitda": 200, "intexp": 10, "netinc": 100, "ncfo": 150, "fcf": 90,
    "ncfcommon": 0, "ncfdebt": 0, "ncfdiv": -5, "epsdil": 1.0,
    "rnd": 30, "capex": -60,
}
FLAT_LEVELS = {
    "assets": 500, "assetsc": 200, "cashneq": 50, "receivables": 40,
    "inventory": 25, "ppnenet": 150, "investments": 10, "liabilities": 200,
    "liabilitiesc": 75, "debt": 100, "debtnc": 50, "equity": 300,
    "retearn": 125, "workingcapital": 125, "tangibles": 450, "invcap": 350,
    "sharesbas": 100, "sharefactor": 1,
}
FLAT_FLOWS = {
    "revenue": 200, "gp": 80, "sgna": 40, "depamor": 10, "ebit": 30,
    "ebitda": 40, "intexp": 2, "netinc": 10, "ncfo": 20, "fcf": 15,
    "ncfcommon": 0, "ncfdebt": 0, "ncfdiv": -1, "epsdil": 0.1,
    "rnd": 5, "capex": -12,
}

QUARTER_ENDS = ((3, 31), (6, 30), (9, 30), (12, 31))


def weekdays(start: date, end: date):
    day = start
    while day <= end:
        if day.weekday() < 5:
            yield day
        day += timedelta(days=1)


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


def filing_periods():
    for year in range(2013, 2018):
        for month, day in QUARTER_ENDS:
            rp = date(year, month, day)
            if date(2013, 12, 31) <= rp <= date(2017, 9, 30):
                yield rp, rp + timedelta(days=45)


def build_sf1_csv() -> str:
    header = ",".join(
        ["ticker", "dimension", "calendardate", "datekey", "reportperiod",
         "lastupdated"]
        + list(ARQ_LEVEL_FIELDS)
        + list(ART_FLOW_FIELDS)
    )
    lines = [header]
    for rp, dk in filing_periods():
        lines += sf1_rows("SPIKE", str(dk), str(rp), SPIKE_LEVELS, SPIKE_FLOWS)
        lines += sf1_rows("FLAT", str(dk), str(rp), FLAT_LEVELS, FLAT_FLOWS)
    # Amendment of the 2014-09-30 period filed ON the low date (2015-01-07):
    # usable strictly after datekey, so the high kind (Jan 8) sees revenue
    # 2000 while low (Jan 7) and median (Jan 1) still see 1000.
    lines += sf1_rows(
        "SPIKE", "2015-01-07", "2014-09-30",
        SPIKE_LEVELS, {**SPIKE_FLOWS, "revenue": 2000},
    )
    return "\n".join(lines) + "\n"


def build_sep_csv() -> str:
    lines = ["ticker,date,close,closeadj,volume,lastupdated"]
    for day in weekdays(BASE, END):
        spike = SPIKE_PRICES.get(day, 100.0)
        lines.append(f"SPIKE,{day},{spike!r},{spike!r},1000,2026-07-01")
        lines.append(f"FLAT,{day},20.0,20.0,1000,2026-07-01")
    return "\n".join(lines) + "\n"


def build_sfp_csv() -> str:
    lines = ["ticker,date,close,closeadj,lastupdated"]
    for day in weekdays(BASE, END):
        lines.append(f"SPY,{day},100.0,100.0,2026-07-01")
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def diag_world(tmp_path_factory) -> Path:
    """Data dir with identity + labels + features + splits-diag run."""
    data_dir = tmp_path_factory.mktemp("diag_world")
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
    assert qa_cli.main([
        "splits-diag",
        "--data-dir", str(data_dir),
        "--report-dir", str(data_dir / "reports"),
        "--test-starts", "2017-01-01",
        "--embargo-days", "30",
        "--twin-sample", "16",
    ]) == 0
    return data_dir


def query(data_dir: Path, table: str, sql: str):
    path = data_dir / "interim" / "qa" / f"{table}.parquet"
    return duckdb.sql(sql.format(t=f"'{path}'")).fetchall()


def test_outputs_exist(diag_world):
    for name in (
        "feature_intraquarter",
        "filing_straddle",
        "label_kind_flip",
        "label_variance_decomposition",
        "label_serial_correlation",
        "twin_relations",
        "twin_label_corr",
        "twin_pairs",
        "purge_cost",
    ):
        assert (diag_world / "interim" / "qa" / f"{name}.parquet").exists()
    for name in ("splits_diag.md", "feature_intraquarter.csv", "purge_cost.csv"):
        assert (diag_world / "reports" / name).exists()


def test_feature_intraquarter(diag_world):
    rows = query(
        diag_world,
        "feature_intraquarter",
        """
        SELECT feature, groups, frac_groups_differ, median_rel_range
        FROM {t}
        WHERE feature IN ('earnings_yield', 'net_margin',
                          'liabilities_to_assets', 'fundamentals_age_days',
                          'vol_12m')
        ORDER BY feature
        """,
    )
    # 24 (stock, quarter) groups. Price-driven earnings_yield differs only in
    # SPIKE 2015-Q1 (the only spread quarter): netinc 100 / marketcap
    # {50,100,200}x100 -> {.02,.01,.005}, rel range (max-min)/median = 1.5.
    # net_margin differs only via the straddle (0.1 vs 2000-revenue 0.05):
    # rel range 0.5. Pure-fundamental ratios never differ. Ages on the spread
    # quarter are 48/54/1 days. vol_12m needs >=200 price days, so only the
    # 8 quarters from 2016 on have values (16 groups), all kind-collapsed.
    assert rows == [
        ("earnings_yield", 24, pytest.approx(1 / 24, abs=1e-4), 1.5),
        ("fundamentals_age_days", 24, pytest.approx(1 / 24, abs=1e-4),
         pytest.approx((54 - 1) / 48, abs=1e-4)),
        ("liabilities_to_assets", 24, 0.0, None),
        ("net_margin", 24, pytest.approx(1 / 24, abs=1e-4), 0.5),
        ("vol_12m", 16, 0.0, None),
    ]


def test_filing_straddle(diag_world):
    assert query(
        diag_world, "filing_straddle", "SELECT * FROM {t}"
    ) == [(24, 1, pytest.approx(1 / 24, abs=1e-4))]


def test_label_kind_flip(diag_world):
    rows = query(
        diag_world,
        "label_kind_flip",
        "SELECT horizon, label, groups, frac_flip FROM {t} ORDER BY horizon, label",
    )
    labels = ["beat_spy", "cagr_ge_0", "cagr_ge_10", "cagr_ge_5", "cagr_ge_8"]
    # 1y observable for 2015-Q1..2016-Q4 (16 groups), 2y for 2015 (8 groups).
    # Only SPIKE 2015-Q1 flips (low +100%/+41.4% vs high -50%/-29.3%
    # straddles every threshold and the flat SPY); everything else is 0%
    # everywhere, so no other group flips at any threshold.
    expected = (
        [("1y", lbl, 16, 0.0625) for lbl in labels]
        + [("2y", lbl, 8, 0.125) for lbl in labels]
        + [("3y", lbl, 0, None) for lbl in labels]
        + [("5y", lbl, 0, None) for lbl in labels]
    )
    assert rows == expected


def test_label_variance_decomposition(diag_world):
    rows = query(
        diag_world,
        "label_variance_decomposition",
        "SELECT * FROM {t} ORDER BY horizon",
    )
    # 1y, all kinds: 48 labeled rows, values {1.0, -0.5, 0 x 46}.
    # total_ss = 1.25 - 48*(0.5/48)^2 = 239/192; within_ss = 3*var({1,0,-.5})
    # = 7/6; share = 224/239. Median rows are all exactly 0% -> zero variance,
    # quarter-FE share undefined (NULL).
    h1 = rows[0]
    assert h1[0:2] == ("1y", 48)
    assert h1[2] == pytest.approx((239 / 192) / 48, abs=1e-6)
    assert h1[3] == pytest.approx(224 / 239, abs=1e-4)
    assert h1[4:7] == (16, 0.0, None)

    # 2y: 24 labeled rows, values {sqrt(2)-1, sqrt(0.5)-1, 0 x 22}.
    lo, hi = 2 ** 0.5 - 1, 0.5 ** 0.5 - 1
    n, s, ss = 24, lo + hi, lo * lo + hi * hi
    total_ss = ss - n * (s / n) ** 2
    within_ss = 3 * (ss / 3 - (s / 3) ** 2)
    h2 = rows[1]
    assert h2[0:2] == ("2y", 24)
    assert h2[2] == pytest.approx(total_ss / n, abs=1e-6)
    assert h2[3] == pytest.approx(within_ss / total_ss, abs=1e-4)
    assert h2[4:7] == (8, 0.0, None)

    # Unobservable horizons: empty slices, NULL shares.
    assert rows[2] == ("3y", 0, 0.0, None, 0, 0.0, None)
    assert rows[3] == ("5y", 0, 0.0, None, 0, 0.0, None)


def test_label_serial_correlation(diag_world):
    rows = query(
        diag_world,
        "label_serial_correlation",
        "SELECT horizon, lag_quarters, pairs, label_corr FROM {t} "
        "ORDER BY horizon, lag_quarters",
    )
    # Median labels are 0% everywhere -> zero variance -> corr is NULL; the
    # join itself is pinned by exact pair counts (8 labeled quarters per
    # stock at 1y, 4 at 2y, none at 3y/5y).
    assert rows == [
        ("1y", 1, 14, None), ("1y", 2, 12, None),
        ("1y", 3, 10, None), ("1y", 4, 8, None),
        ("2y", 1, 6, None), ("2y", 2, 4, None),
        ("2y", 3, 2, None), ("2y", 4, 0, None),
        ("3y", 1, 0, None), ("3y", 2, 0, None),
        ("3y", 3, 0, None), ("3y", 4, 0, None),
        ("5y", 1, 0, None), ("5y", 2, 0, None),
        ("5y", 3, 0, None), ("5y", 4, 0, None),
    ]


def test_twin_pairs(diag_world):
    # Twin space = median rows with all 12 axes present: vol_12m gates it to
    # 2016-Q1 on -> 8 quarters x 2 stocks = 16 rows, all sampled.
    rows = query(
        diag_world,
        "twin_pairs",
        """
        SELECT count(*),
               sum((permaticker = nn_permaticker AND quarter = nn_quarter)::INT)
        FROM {t}
        """,
    )
    assert rows == [(16, 0)]
    relations = {r[0] for r in query(
        diag_world, "twin_pairs", "SELECT DISTINCT nn_relation FROM {t}"
    )}
    assert relations <= {
        "same_stock_within_1y", "same_stock_distant",
        "same_quarter_peer", "unrelated",
    }
    (total_share,) = query(
        diag_world, "twin_relations", "SELECT sum(share) FROM {t}"
    )[0]
    assert total_share == pytest.approx(1.0, abs=1e-3)


def test_twin_label_corr_shape(diag_world):
    rows = query(
        diag_world,
        "twin_label_corr",
        "SELECT horizon, pairing, labeled_pairs FROM {t} ORDER BY horizon, pairing",
    )
    assert [(h, p) for h, p, _n in rows] == [
        (h, p)
        for h in ("1y", "2y", "3y", "5y")
        for p in ("nearest", "random")
    ]
    by_key = {(h, p): n for h, p, n in rows}
    # 3y/5y are never observable in this world.
    assert by_key[("3y", "nearest")] == 0 and by_key[("5y", "random")] == 0


def test_purge_cost(diag_world):
    rows = query(diag_world, "purge_cost", "SELECT * FROM {t} ORDER BY horizon")
    # 72 snapshot rows (12 quarters x 3 kinds x 2 stocks); pool before
    # 2017-01-01 = 48. 1y + 30d eligibility keeps exactly the 2015 rows (24);
    # every longer horizon purges the whole pool. Test window = 2017's 8
    # median rows.
    assert rows == [
        (date(2017, 1, 1), "1y", 48, 24, 24, 0.5, 8),
        (date(2017, 1, 1), "2y", 48, 0, 48, 1.0, 8),
        (date(2017, 1, 1), "3y", 48, 0, 48, 1.0, 8),
        (date(2017, 1, 1), "5y", 48, 0, 48, 1.0, 8),
    ]


def test_missing_inputs(tmp_path):
    assert qa_cli.main(["splits-diag", "--data-dir", str(tmp_path)]) == 2
