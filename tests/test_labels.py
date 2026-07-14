from datetime import date

import duckdb
import pytest

from labels.compute import build_labels
from labels.snapshots import build_snapshots


def copy_query(path, query):
    duckdb.sql(f"COPY ({query}) TO ? (FORMAT PARQUET)", params=[str(path)])


def test_snapshot_uses_earliest_observed_discrete_median(tmp_path):
    raw, interim = tmp_path / "raw", tmp_path / "interim"
    raw.mkdir()
    interim.mkdir()
    copy_query(
        interim / "universe.parquet",
        """SELECT 1::BIGINT permaticker,'ABC'::VARCHAR ticker,
                  DATE '2020-01-01' firstpricedate,DATE '2020-03-31' lastpricedate""",
    )
    copy_query(
        raw / "SEP.parquet",
        """SELECT * FROM (VALUES
           ('ABC',DATE '2020-01-02',1.0),('ABC',DATE '2020-01-03',2.0),
           ('ABC',DATE '2020-01-06',2.0),('ABC',DATE '2020-01-07',4.0))
           prices(ticker,date,closeadj)""",
    )

    stats = build_snapshots(raw, interim, start_year=2020)

    assert stats.snapshots == 3
    rows = duckdb.sql(
        "SELECT snapshot_kind,snapshot_date,entry_closeadj FROM read_parquet(?) ORDER BY snapshot_kind",
        params=[str(interim / "snapshots.parquet")],
    ).fetchall()
    assert rows == [
        ("high", date(2020, 1, 7), 4.0),
        ("low", date(2020, 1, 2), 1.0),
        ("median", date(2020, 1, 3), 2.0),
    ]


def test_delisted_label_carries_final_value_and_embeds_reason(tmp_path):
    raw, interim = tmp_path / "raw", tmp_path / "interim"
    raw.mkdir()
    interim.mkdir()
    copy_query(
        interim / "universe.parquet",
        """SELECT 1::BIGINT permaticker,'ABC'::VARCHAR ticker,'Y'::VARCHAR isdelisted,
                  DATE '2020-06-30' lastpricedate""",
    )
    copy_query(
        interim / "snapshots.parquet",
        """SELECT 1::BIGINT snapshot_id,1::BIGINT permaticker,'ABC'::VARCHAR ticker,
                  DATE '2020-01-01' "quarter",1::INTEGER quarter_trading_days,
                  DATE '2020-01-02' snapshot_date,'median'::VARCHAR snapshot_kind,
                  10.0::DOUBLE entry_closeadj""",
    )
    copy_query(
        raw / "SEP.parquet",
        """SELECT * FROM (VALUES
           ('ABC',DATE '2020-01-02',10.0),('ABC',DATE '2020-06-30',15.0))
           prices(ticker,date,closeadj)""",
    )
    copy_query(
        raw / "SFP.parquet",
        """SELECT * FROM (VALUES
           ('SPY',DATE '2020-01-02',100.0),('SPY',DATE '2025-01-02',150.0))
           prices(ticker,date,closeadj)""",
    )
    copy_query(
        raw / "ACTIONS.parquet",
        """SELECT DATE '2020-06-30' date,'acquisitionby'::VARCHAR "action",
                  'ABC'::VARCHAR ticker""",
    )

    build_labels(raw, interim)
    row = duckdb.sql(
        """SELECT fwd_1y_closeadj_avg,fwd_1y_closeadj_p2p,
                  fwd_1y_closeadj_min,fwd_1y_closeadj_max,
                  fwd_1y_cagr,delisted_in_window_1y
           FROM read_parquet(?)""",
        params=[str(interim / "labels.parquet")],
    ).fetchone()
    assert row[:4] == (15.0, 15.0, 15.0, 15.0)
    assert row[4] == pytest.approx(0.5)
    assert row[5] == "acquisitionby"
