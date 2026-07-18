"""End-to-end tests for dataset assembly on a hand-checkable world.

Synthetic weekday calendar 2013-01-01 .. 2018-12-31, four stocks. MONE /
MTWO / MTHR are constant-price Industrials/Machinery peers with annual
filings FY2012–FY2016 (full T3 chains from 2016 on), whose fundamentals are
chosen so every Mohanram G7 signal, rank, and sector-rank is hand-derivable
— including exact-zero variabilities (constant ROA; revenue growth that is
exact in binary floating point). SOLO trades a single quarter (2016-Q1,
constant price, so all three snapshot kinds collapse onto one date): the
isolated-stock-quarter case whose uniqueness weight is exactly 1/3
(decision 0012), and a Technology singleton whose sector-rank the
thin-slice guard must NULL.

Assembly runs with --rank-guard 3 --min-industry-peers 3 so the four-stock
cross-sections clear the guards (the production defaults would NULL
everything, which is exactly what they are for).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import duckdb
import pytest

from assemble import cli as assemble_cli
from assemble.wide import feature_columns_in_order, rank_columns, secrank_columns
from features import cli as features_cli
from features.source import ARQ_LEVEL_FIELDS, ART_FLOW_FIELDS
from identity import cli as identity_cli
from ingest.convert import csv_to_parquet
from ingest.tables import TABLES
from labels import cli as labels_cli
from splits import cli as splits_cli

BASE = date(2013, 1, 1)
END = date(2018, 12, 31)

TICKERS_CSV = """\
table,permaticker,ticker,name,exchange,category,sector,industry,famaindustry,siccode,scalemarketcap,isdelisted,firstpricedate,lastpricedate,lastupdated
SEP,500001,MONE,Machinery One,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3500,3 - Small,N,2013-01-01,2018-12-31,2026-07-01
SEP,500002,MTWO,Machinery Two,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3510,3 - Small,N,2013-01-01,2018-12-31,2026-07-01
SEP,500003,MTHR,Machinery Three,NYSE,Domestic Common Stock,Industrials,Machinery,Machinery,3520,4 - Mid,N,2013-01-01,2018-12-31,2026-07-01
SEP,500004,SOLO,Solo Quarter Corp,OTC,Domestic Common Stock,Technology,Software - Application,Business Services,7372,1 - Nano,Y,2016-01-01,2016-03-31,2026-07-01
"""

ACTIONS_CSV = """\
date,action,ticker,name,contraticker,contraname
2016-04-05,delisted,SOLO,Solo Quarter Corp,,
"""

PRICES = {"MONE": 10.0, "MTWO": 20.0, "MTHR": 40.0, "SOLO": 5.0}

# Shared ARQ levels: same balance sheet everywhere so industry medians and
# per-share arithmetic stay trivial (only prices and flows differ).
LEVELS = {
    "assets": 1000, "assetsc": 400, "cashneq": 100, "receivables": 80,
    "inventory": 50, "ppnenet": 300, "investments": 20, "liabilities": 600,
    "liabilitiesc": 200, "debt": 250, "debtnc": 150, "equity": 400,
    "retearn": 120, "workingcapital": 200, "tangibles": 900, "invcap": 650,
    "sharesbas": 100, "sharefactor": 1,
}

# Shared ART flows for the fields no assertion touches; the per-stock dicts
# below override the hand-checked ones.
FLOW_DEFAULTS = {
    "gp": 200, "sgna": 100, "depamor": 30, "ebit": 70, "ebitda": 100,
    "intexp": 10, "fcf": 35, "ncfdebt": 0, "epsdil": 0.5,
}

# ART flows per (ticker, fiscal year). Revenue paths: MONE flat (YoY growth
# exactly 0.0), MTWO doubling (growth exactly 1.0 — exact in floats, so its
# growth variability is exactly zero), MTHR irregular (nonzero variability
# stddev({0.1, -0.1, 0.25}) ≈ 0.17559). Net income: constant for MONE/MTHR
# (ROA variability exactly zero), drifting for MTWO.
FLOWS = {
    "MONE": {
        2012: dict(revenue=1000, netinc=100, ncfo=150, rnd=50, capex=-100, ncfdiv=-10, ncfcommon=0),
        2013: dict(revenue=1000, netinc=100, ncfo=150, rnd=50, capex=-100, ncfdiv=-10, ncfcommon=0),
        2014: dict(revenue=1000, netinc=100, ncfo=150, rnd=50, capex=-100, ncfdiv=-10, ncfcommon=0),
        2015: dict(revenue=1000, netinc=100, ncfo=150, rnd=50, capex=-100, ncfdiv=-10, ncfcommon=0),
        2016: dict(revenue=1000, netinc=100, ncfo=150, rnd=50, capex=-100, ncfdiv=-10, ncfcommon=0),
    },
    "MTWO": {
        2012: dict(revenue=500, netinc=40, ncfo=100, rnd=20, capex=-50, ncfdiv=-40, ncfcommon=0),
        2013: dict(revenue=1000, netinc=50, ncfo=100, rnd=20, capex=-50, ncfdiv=-40, ncfcommon=0),
        2014: dict(revenue=2000, netinc=60, ncfo=100, rnd=20, capex=-50, ncfdiv=-40, ncfcommon=0),
        2015: dict(revenue=4000, netinc=70, ncfo=100, rnd=20, capex=-50, ncfdiv=-40, ncfcommon=0),
        2016: dict(revenue=8000, netinc=80, ncfo=100, rnd=20, capex=-50, ncfdiv=-40, ncfcommon=0),
    },
    "MTHR": {
        2012: dict(revenue=700, netinc=200, ncfo=300, capex=-200, ncfdiv=0, ncfcommon=-120),
        2013: dict(revenue=800, netinc=200, ncfo=300, capex=-200, ncfdiv=0, ncfcommon=-120),
        2014: dict(revenue=1000, netinc=200, ncfo=300, capex=-200, ncfdiv=0, ncfcommon=-120),
        2015: dict(revenue=900, netinc=200, ncfo=300, capex=-200, ncfdiv=0, ncfcommon=-120),
        2016: dict(revenue=990, netinc=200, ncfo=300, capex=-200, ncfdiv=0, ncfcommon=-120),
    },
}


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
            lines += sf1_rows(
                ticker, f"{fy + 1}-03-01", f"{fy}-12-31", LEVELS,
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
        for ticker in ("MONE", "MTWO", "MTHR"):
            px = PRICES[ticker]
            lines.append(f"{ticker},{day},{px},{px},1000,2026-07-01")
        if date(2016, 1, 1) <= day <= date(2016, 3, 31):
            lines.append(f"SOLO,{day},5.0,5.0,100,2026-07-01")
    return "\n".join(lines) + "\n"


def build_sfp_csv() -> str:
    lines = ["ticker,date,close,closeadj,lastupdated"]
    for day in weekdays(BASE, END):
        lines.append(f"SPY,{day},100.0,100.0,2026-07-01")
    return "\n".join(lines) + "\n"


@pytest.fixture(scope="module")
def assembled_world(tmp_path_factory) -> Path:
    """Data dir with the whole pipeline run, assembly included."""
    data_dir = tmp_path_factory.mktemp("assemble_world")
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
    assert splits_cli.main(["--data-dir", str(data_dir)]) == 0
    assert assemble_cli.main(
        ["--data-dir", str(data_dir), "--rank-guard", "3",
         "--min-industry-peers", "3"]
    ) == 0
    return data_dir


def dataset_dir(data_dir: Path) -> Path:
    return data_dir / "datasets" / "dataset_v1.0"


def query(data_dir: Path, sql: str):
    path = dataset_dir(data_dir) / "dataset.parquet"
    return duckdb.sql(sql.format(t=f"'{path}'")).fetchall()


def one_row(data_dir: Path, sql: str):
    rows = query(data_dir, sql)
    assert len(rows) == 1, rows
    return rows[0]


def machinery(data_dir: Path, columns: str, snapshot_date: str):
    """One row per machinery stock (median kind), ordered MONE, MTWO, MTHR."""
    rows = query(
        data_dir,
        f"""
        SELECT {columns} FROM {{t}}
        WHERE permaticker IN (500001, 500002, 500003)
          AND snapshot_kind = 'median'
          AND snapshot_date = DATE '{snapshot_date}'
        ORDER BY permaticker
        """,
    )
    assert len(rows) == 3, rows
    return rows


def test_dataset_directory_contents(assembled_world):
    out = dataset_dir(assembled_world)
    assert (out / "dataset.parquet").exists()
    assert (out / "splits.parquet").exists()
    assert (out / "split_folds.parquet").exists()
    assert (out / "manifest.json").exists()
    # The split files are verbatim copies of the interim artifacts.
    interim = assembled_world / "interim"
    for name in ("splits.parquet", "split_folds.parquet"):
        assert (out / name).read_bytes() == (interim / name).read_bytes()


def test_row_count_and_column_layout(assembled_world):
    # MONE/MTWO/MTHR: 24 quarters × 3 kinds; SOLO: 1 quarter × 3.
    assert query(
        assembled_world,
        "SELECT count(*), count(DISTINCT permaticker) FROM {t}",
    ) == [(219, 4)]

    labels_cols = [
        r[0]
        for r in duckdb.sql(
            f"DESCRIBE SELECT * FROM '{assembled_world / 'interim' / 'labels.parquet'}'"
        ).fetchall()
    ]
    key_meta = [
        c for c in labels_cols
        if not c.startswith(("fwd_", "label_", "delisted_in_window_"))
    ]
    label_matrix = [c for c in labels_cols if c not in key_meta]
    expected = (
        key_meta
        + list(feature_columns_in_order())
        + list(rank_columns())
        + list(secrank_columns())
        + label_matrix
        + [f"sample_weight_{h}y" for h in (1, 2, 3, 5)]
    )
    emitted = [
        r[0]
        for r in duckdb.sql(
            f"DESCRIBE SELECT * FROM '{dataset_dir(assembled_world) / 'dataset.parquet'}'"
        ).fetchall()
    ]
    assert emitted == expected


def test_ranks_within_quarter_and_kind(assembled_world):
    # 2017-Q2, median kind: sales_yield = FY2016 revenue / marketcap =
    # 1.0 (MONE), 4.0 (MTWO), 0.2475 (MTHR) -> percent ranks 0.5, 1.0, 0.
    rows = machinery(
        assembled_world, "sales_yield, sales_yield_rank", "2017-04-03"
    )
    assert rows == [
        (pytest.approx(1.0), pytest.approx(0.5)),
        (pytest.approx(4.0), pytest.approx(1.0)),
        (pytest.approx(0.2475), pytest.approx(0.0)),
    ]

    # 2016-Q1 includes SOLO, and predates the 2016-03-01 filings, so T0 is
    # FY2014 for everyone: MTHR 1000/4000 = 0.25 < SOLO 400/500 = 0.8 <
    # MONE 1000/1000 = MTWO 2000/2000 = 1.0 (a tie -> shared percent rank).
    rows = query(
        assembled_world,
        """
        SELECT permaticker, sales_yield, sales_yield_rank FROM {t}
        WHERE snapshot_kind = 'median' AND quarter = DATE '2016-01-01'
        ORDER BY sales_yield, permaticker
        """,
    )
    assert [(r[0], r[2]) for r in rows] == [
        (500003, pytest.approx(0.0)),
        (500004, pytest.approx(1 / 3)),
        (500001, pytest.approx(2 / 3)),
        (500002, pytest.approx(2 / 3)),
    ]


def test_sector_ranks_and_thin_slice_guard(assembled_world):
    # Industrials has 3 stocks (= guard): sector ranks exist. SOLO is the
    # only Technology stock: its sector cross-section is below the guard.
    rows = query(
        assembled_world,
        """
        SELECT permaticker, sales_yield_secrank FROM {t}
        WHERE snapshot_kind = 'median' AND quarter = DATE '2016-01-01'
        ORDER BY permaticker
        """,
    )
    assert rows == [
        (500001, pytest.approx(0.5)),   # MONE/MTWO tie above MTHR
        (500002, pytest.approx(0.5)),
        (500003, pytest.approx(0.0)),
        (500004, None),                 # thin-slice guard
    ]

    # The production default guard (20) NULLs every rank in this tiny world:
    # rebuild into a second version and check.
    assert assemble_cli.main(
        ["--data-dir", str(assembled_world), "--dataset-version", "1.0-guard20"]
    ) == 0
    guarded = (
        assembled_world / "datasets" / "dataset_v1.0-guard20" / "dataset.parquet"
    )
    assert duckdb.sql(
        f"SELECT count(sales_yield_rank) + count(sales_yield_secrank) "
        f"FROM '{guarded}'"
    ).fetchall() == [(0,)]


def test_mohanram_g7_hand_check(assembled_world):
    # 2017-Q2 (T0 = FY2016, full T3 chains, 3 Machinery peers).
    # Medians: roa 0.1, cfo/ta 0.15, roa_var 0, growth_var 0,
    # rnd/ta 0.02, capex/ta 0.1. Signals (ADR 0013 order):
    #   MONE: >med fails ×2, cfo>roa ✓, var<med fails ×2, rnd ✓, capex ✗ = 2
    #   MTWO: only cfo>roa ✓ = 1
    #   MTHR: roa ✓, cfo ✓, cfo>roa ✓, vars ✗✗, rnd ✗, capex ✓ = 4
    rows = machinery(
        assembled_world,
        "roa_variability_3y, revenue_growth_variability_3y, mohanram_g7, "
        "mohanram_g7_rank",
        "2017-04-03",
    )
    stddev_mthr = (
        (0.1 ** 2 + 0.1 ** 2 + 0.25 ** 2) / 3
        - ((0.1 - 0.1 + 0.25) / 3) ** 2
    ) ** 0.5 * (3 / 2) ** 0.5
    assert rows[0] == (0.0, 0.0, 2, pytest.approx(0.5))
    assert rows[1][0] == pytest.approx(0.0129099, abs=1e-6)
    assert rows[1][1:] == (0.0, 1, pytest.approx(0.0))
    assert rows[2][0] == 0.0
    assert rows[2][1] == pytest.approx(stddev_mthr)
    assert rows[2][2:] == (4, pytest.approx(1.0))

    # SOLO has no famaindustry peers and no T3 chain: NULL composite.
    assert one_row(
        assembled_world,
        "SELECT mohanram_g7 FROM {t} WHERE permaticker = 500004 "
        "AND snapshot_kind = 'median'",
    ) == (None,)


def test_conservative_score_hand_check(assembled_world):
    # Constant prices: vol_36m and mom_12_2 tie at 0 -> both ranks 0 for
    # everyone. Net payout yield: 0.01/0.02/0.03 -> ranks 0/0.5/1.
    # conservative = (1 - 0) + 0 + npy_rank.
    rows = machinery(
        assembled_world,
        "net_payout_yield, conservative_score, conservative_score_rank",
        "2017-04-03",
    )
    assert rows == [
        (pytest.approx(0.01), pytest.approx(1.0), pytest.approx(0.0)),
        (pytest.approx(0.02), pytest.approx(1.5), pytest.approx(0.5)),
        (pytest.approx(0.03), pytest.approx(2.0), pytest.approx(1.0)),
    ]

    # SOLO traded one quarter: no vol_36m -> no conservative score.
    assert one_row(
        assembled_world,
        "SELECT conservative_score FROM {t} WHERE permaticker = 500004 "
        "AND snapshot_kind = 'median'",
    ) == (None,)


def test_uniqueness_weights(assembled_world):
    # SOLO: one stock-quarter, constant price, so all three kinds share one
    # snapshot date -> three identical windows -> exactly 1/3 each
    # (decision 0012 §2). 3y/5y horizons are unobservable -> NULL.
    rows = query(
        assembled_world,
        """
        SELECT snapshot_kind, sample_weight_1y, sample_weight_2y,
               sample_weight_3y, sample_weight_5y
        FROM {t} WHERE permaticker = 500004
        """,
    )
    assert len(rows) == 3
    for _, w1, w2, w3, w5 in rows:
        assert w1 == pytest.approx(1 / 3)
        assert w2 == pytest.approx(1 / 3)
        assert (w3, w5) == (None, None)

    # MONE's first snapshot (2013-01-01, all kinds collapsed), 1y horizon:
    # window [2013-01-01, 2014-01-01], concurrency 3 per own-quarter sibling
    # kinds plus 3 more per later quarter start:
    #   90d @ c=3, 91d @ c=6, 92d @ c=9, 92d @ c=12, 1d @ c=15, over 366d.
    expected = (90 / 3 + 91 / 6 + 92 / 9 + 92 / 12 + 1 / 15) / 366
    assert one_row(
        assembled_world,
        """
        SELECT sample_weight_1y FROM {t}
        WHERE permaticker = 500001 AND snapshot_kind = 'median'
          AND snapshot_date = DATE '2013-01-01'
        """,
    ) == (pytest.approx(expected),)

    # Unobservable horizon -> NULL weight even though the window is defined.
    assert one_row(
        assembled_world,
        """
        SELECT sample_weight_1y, delisted_in_window_1y FROM {t}
        WHERE permaticker = 500001 AND snapshot_kind = 'median'
          AND snapshot_date = DATE '2018-10-01'
        """,
    ) == (None, None)

    # Weights are average uniqueness: in (0, 1] wherever observable.
    assert query(
        assembled_world,
        """
        SELECT count(*) FROM {t}
        WHERE (sample_weight_1y <= 0 OR sample_weight_1y > 1)
           OR (sample_weight_1y IS NULL) != (delisted_in_window_1y IS NULL)
        """,
    ) == [(0,)]


def test_manifest(assembled_world):
    manifest = json.loads(
        (dataset_dir(assembled_world) / "manifest.json").read_text()
    )
    assert manifest["dataset_version"] == "1.0"
    assert manifest["horizons_years"] == [1, 2, 3, 5]
    assert manifest["params"] == {"rank_guard": 3, "min_industry_peers": 3}
    assert manifest["rows"] == 219
    assert manifest["permatickers"] == 4
    assert manifest["input_rows"]["labels"] == 219
    assert manifest["columns"]["features"] == list(feature_columns_in_order())
    assert manifest["feature_versions"]["mohanram_g7"] == {
        "added": "1.0", "removed": None,
    }
    # Effective sample size: 1y sums every observable row's uniqueness.
    assert 0 < manifest["effective_rows"]["1y"] < 219


def test_dataset_versions_are_immutable(assembled_world):
    args = ["--data-dir", str(assembled_world), "--rank-guard", "3",
            "--min-industry-peers", "3"]
    assert assemble_cli.main(args) == 1  # refuses to overwrite
    assert assemble_cli.main(args + ["--force"]) == 0


def test_missing_inputs(tmp_path):
    assert assemble_cli.main(["--data-dir", str(tmp_path)]) == 2
