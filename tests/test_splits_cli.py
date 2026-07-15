"""End-to-end tests for the splits pipeline on a hand-checkable world.

Reuses the labels-world fixtures (test_labels_cli): weekday calendar
2015-01-01 .. 2021-12-31, GROW (300001) alive throughout, DEAD (300002)
delists 2016-06-30, ZIG (300003) trades one week in 2015-Q1, BANK excluded.

Splits run with --embargo-days 30 --holdout-years 1 --min-train-years 2 so
the tiny world produces a checkable calendar. Last observable snapshot year
per horizon: 1y->2020, 2y->2019, 3y->2018, 5y->2016 (calendar ends
2021-12-31), giving holdout folds at those years and walk-forward folds
only for 1y (first test year = 2015 + 2 + H): 2018 and 2019.

Hand-derived counts lean on the world's snapshot-date structure: GROW grows
monotonically, so each quarter's low/high land on the first/last trading
day and the median lands mid-quarter (mid-November in Q4 — always inside a
train region, never inside a 30-day embargo band ending Dec 31). DEAD's
constant price collapses all three kinds onto the quarter's first trading
day. The only snapshot ever caught by an embargo band is a GROW Q4 high.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pytest

from identity import cli as identity_cli
from ingest.convert import csv_to_parquet
from ingest.tables import TABLES
from labels import cli as labels_cli
from splits import cli as splits_cli

from test_labels_cli import ACTIONS_CSV, TICKERS_CSV, build_sep_csv, build_sfp_csv

FAR_FUTURE = date(9999, 12, 31)

SPLIT_ARGS = [
    "--embargo-days", "30",
    "--holdout-years", "1",
    "--min-train-years", "2",
]


@pytest.fixture(scope="module")
def splits_world(tmp_path_factory) -> Path:
    """Data dir with identity + labels + splits already run."""
    data_dir = tmp_path_factory.mktemp("splits_world")
    raw = data_dir / "raw"
    for name, csv_text in (
        ("TICKERS", TICKERS_CSV),
        ("SEP", build_sep_csv()),
        ("SFP", build_sfp_csv()),
        ("ACTIONS", ACTIONS_CSV),
    ):
        csv_path = data_dir / f"{name}_fixture.csv"
        csv_path.write_text(csv_text)
        csv_to_parquet(csv_path, TABLES[name], raw / f"{name}.parquet")

    assert identity_cli.main(["--data-dir", str(data_dir)]) == 0
    assert labels_cli.main(["--data-dir", str(data_dir)]) == 0
    assert splits_cli.main(["--data-dir", str(data_dir), *SPLIT_ARGS]) == 0
    return data_dir


def query(data_dir: Path, table: str, sql: str):
    path = data_dir / "interim" / f"{table}.parquet"
    return duckdb.sql(sql.format(t=f"'{path}'")).fetchall()


def one_row(data_dir: Path, table: str, sql: str):
    rows = query(data_dir, table, sql)
    assert len(rows) == 1, rows
    return rows[0]


def test_outputs_exist(splits_world):
    for name in ("splits.parquet", "split_folds.parquet"):
        assert (splits_world / "interim" / name).exists()


def test_fold_manifest(splits_world):
    rows = query(
        splits_world,
        "split_folds",
        """
        SELECT scheme, fold, horizon_years, test_start, test_end,
               n_train, n_test, n_purged, n_embargoed
        FROM {t} ORDER BY scheme, horizon_years, fold
        """,
    )
    # Row counts hand-derived from the world's 105 snapshots (GROW 84,
    # DEAD 18, ZIG 3). Example, walkforward 2018 @1y: train = snapshots
    # dated < 2016-12-02 (GROW 2015 + Q1-Q3 2016 + Q4 low/median = 23,
    # DEAD 18, ZIG 3), test = GROW's four 2018 medians, purged = GROW's
    # twelve 2017 snapshots, embargoed = GROW's 2016-12-30 Q4 high.
    assert rows == [
        ("holdout", 2020, 1, date(2020, 1, 1), FAR_FUTURE, 68, 4, 12, 1),
        ("holdout", 2019, 2, date(2019, 1, 1), FAR_FUTURE, 44, 4, 24, 1),
        ("holdout", 2018, 3, date(2018, 1, 1), FAR_FUTURE, 0, 4, 57, 0),
        ("holdout", 2016, 5, date(2016, 1, 1), FAR_FUTURE, 0, 6, 27, 0),
        ("walkforward", 2018, 1, date(2018, 1, 1), date(2019, 1, 1), 44, 4, 12, 1),
        ("walkforward", 2019, 1, date(2019, 1, 1), date(2020, 1, 1), 56, 4, 12, 1),
    ]


def test_test_rows_are_median_only_and_observable(splits_world):
    (bad_kind,) = one_row(
        splits_world,
        "splits",
        "SELECT count(*) FROM {t} WHERE role = 'test' AND snapshot_kind <> 'median'",
    )
    assert bad_kind == 0

    # Every test row must carry an observable label at its horizon.
    splits_path = splits_world / "interim" / "splits.parquet"
    labels_path = splits_world / "interim" / "labels.parquet"
    for h in (1, 2, 3, 5):
        (unobservable,) = duckdb.sql(
            f"""
            SELECT count(*)
            FROM '{splits_path}' s
            JOIN '{labels_path}' l
                USING (permaticker, snapshot_date, snapshot_kind)
            WHERE s.role IN ('test', 'train') AND s.horizon_years = {h}
              AND l.delisted_in_window_{h}y IS NULL
            """
        ).fetchall()[0]
        assert unobservable == 0, f"horizon {h}"


def test_role_conditions_hold_everywhere(splits_world):
    # Re-derive every role from the manifest boundaries; zero disagreements.
    splits_path = splits_world / "interim" / "splits.parquet"
    folds_path = splits_world / "interim" / "split_folds.parquet"
    (violations,) = duckdb.sql(
        f"""
        SELECT count(*)
        FROM '{splits_path}' s
        JOIN '{folds_path}' f USING (scheme, fold, horizon_years)
        WHERE s.role <> CASE
            WHEN s.snapshot_date < f.test_start THEN CASE
                WHEN s.snapshot_date + to_years(s.horizon_years)
                     + to_days(f.embargo_days) < f.test_start THEN 'train'
                WHEN s.snapshot_date + to_years(s.horizon_years)
                     < f.test_start THEN 'embargoed'
                ELSE 'purged'
            END
            ELSE 'test'
        END
        """
    ).fetchall()[0]
    assert violations == 0


def test_walkforward_2018_1y_roles(splits_world):
    # Test rows: exactly GROW's four 2018 median snapshots.
    rows = query(
        splits_world,
        "splits",
        """
        SELECT DISTINCT permaticker, snapshot_kind, year(snapshot_date)
        FROM {t} WHERE scheme = 'walkforward' AND fold = 2018
          AND horizon_years = 1 AND role = 'test'
        """,
    )
    assert rows == [(300001, "median", 2018)]

    # The embargo band [2016-12-02, 2017-01-01) catches exactly one
    # snapshot: GROW's Q4-2016 high on the last trading day of the year.
    row = one_row(
        splits_world,
        "splits",
        """
        SELECT permaticker, snapshot_date, snapshot_kind
        FROM {t} WHERE scheme = 'walkforward' AND fold = 2018
          AND horizon_years = 1 AND role = 'embargoed'
        """,
    )
    assert row == (300001, date(2016, 12, 30), "high")

    # Purged: GROW's twelve 2017 snapshots, whose 1y windows reach 2018.
    rows = query(
        splits_world,
        "splits",
        """
        SELECT min(year(snapshot_date)), max(year(snapshot_date)), count(*)
        FROM {t} WHERE scheme = 'walkforward' AND fold = 2018
          AND horizon_years = 1 AND role = 'purged'
        """,
    )
    assert rows == [(2017, 2017, 12)]


def test_delisted_stocks_stay_in_training(splits_world):
    # DEAD delisted in 2016 — all 18 of its snapshots (3 kinds x 6
    # quarters) must train in the walkforward-2018 1y fold. Dropping them
    # would reintroduce survivorship bias.
    row = one_row(
        splits_world,
        "splits",
        """
        SELECT count(*), count(DISTINCT snapshot_kind)
        FROM {t} WHERE scheme = 'walkforward' AND fold = 2018
          AND horizon_years = 1 AND role = 'train' AND permaticker = 300002
        """,
    )
    assert row == (18, 3)

    # ...and a stock that delists *inside* the forward window is still a
    # test row: DEAD's 2016 Q1/Q2 medians in the 5y holdout.
    rows = query(
        splits_world,
        "splits",
        """
        SELECT snapshot_date FROM {t}
        WHERE scheme = 'holdout' AND horizon_years = 5
          AND role = 'test' AND permaticker = 300002
        ORDER BY snapshot_date
        """,
    )
    assert rows == [(date(2016, 1, 1),), (date(2016, 4, 1),)]


def test_holdout_1y_excludes_unobservable_recent_rows(splits_world):
    # GROW's 2021 snapshots sit inside the holdout test period but their 1y
    # windows end past the calendar: no tag at all (absence = out of fold).
    (tagged,) = one_row(
        splits_world,
        "splits",
        """
        SELECT count(*) FROM {t}
        WHERE scheme = 'holdout' AND horizon_years = 1
          AND year(snapshot_date) = 2021
        """,
    )
    assert tagged == 0


def test_low_high_never_test_but_do_train(splits_world):
    # Low/high rows are training-only (PLAN §4): present among train rows,
    # absent from every test set.
    row = one_row(
        splits_world,
        "splits",
        """
        SELECT count(*) FILTER (role = 'train' AND snapshot_kind IN ('low', 'high')),
               count(*) FILTER (role = 'test' AND snapshot_kind IN ('low', 'high'))
        FROM {t}
        """,
    )
    assert row[0] > 0
    assert row[1] == 0


def test_missing_inputs(tmp_path):
    assert splits_cli.main(["--data-dir", str(tmp_path)]) == 2


def test_unknown_horizon_exits_2(splits_world):
    # labels.parquet has no 4y columns; the CLI must name the fix.
    assert (
        splits_cli.main(["--data-dir", str(splits_world), "--horizons", "4"]) == 2
    )
