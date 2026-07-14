from pathlib import Path

import duckdb
import pytest

from identity.mapping import build_mapping_view, write_mapping_tables
from identity.report import (
    YearCount,
    build_counts_view,
    plot_universe_counts,
    write_counts_tables,
)
from identity.source import create_tickers_view
from identity.universe import build_universe_view, write_universe_table


@pytest.fixture
def con(identity_tickers_parquet: Path):
    connection = duckdb.connect()
    create_tickers_view(connection, identity_tickers_parquet)
    yield connection
    connection.close()


def universe_row(con, ticker) -> dict:
    cursor = con.execute("SELECT * FROM universe WHERE ticker = ?", [ticker])
    columns = [d[0] for d in cursor.description]
    return dict(zip(columns, cursor.fetchone()))


class TestSource:
    def test_one_row_per_permaticker(self, con):
        n, distinct = con.execute(
            "SELECT count(*), count(DISTINCT permaticker) FROM tickers_deduped"
        ).fetchone()
        assert n == distinct == 14  # 16 CSV rows minus the SF1 row and the DUP dupe

    def test_sf1_row_ignored(self, con):
        name = con.execute(
            "SELECT name FROM tickers_deduped WHERE ticker = 'AAPL'"
        ).fetchone()[0]
        assert name == "Apple Inc"

    def test_latest_lastupdated_wins(self, con):
        name = con.execute(
            "SELECT name FROM tickers_deduped WHERE ticker = 'DUP'"
        ).fetchone()[0]
        assert name == "Dup Industries v2"


class TestMapping:
    @pytest.fixture(autouse=True)
    def _views(self, con):
        build_mapping_view(con)

    def test_reuse_flagged(self, con):
        rows = con.execute(
            "SELECT permaticker, ticker_is_reused FROM mapping WHERE ticker = 'XYZ' ORDER BY 1"
        ).fetchall()
        assert rows == [(200100, True), (200101, True)]

    def test_unique_ticker_not_flagged(self, con):
        assert con.execute(
            "SELECT ticker_is_reused FROM mapping WHERE ticker = 'AAPL'"
        ).fetchone() == (False,)

    def test_written_tables(self, con, tmp_path):
        counts = write_mapping_tables(con, tmp_path / "interim")
        assert counts == {"mapping_rows": 14, "reused_ticker_rows": 2}
        reuse = duckdb.sql(
            f"SELECT DISTINCT ticker FROM '{tmp_path / 'interim' / 'ticker_reuse.parquet'}'"
        ).fetchall()
        assert reuse == [("XYZ",)]


class TestUniverse:
    @pytest.fixture(autouse=True)
    def _views(self, con):
        build_universe_view(con)

    def test_in_universe_membership(self, con):
        included = {
            r[0]
            for r in con.execute(
                "SELECT ticker FROM universe WHERE in_universe"
            ).fetchall()
        }
        assert included == {
            "AAPL", "WCOEQ", "O", "GOOGL", "XYZ", "NOSIC", "NOFP", "FINTECH", "DUP",
        }

    def test_bank_excluded_by_sic(self, con):
        row = universe_row(con, "BAC")
        assert row["is_common_stock"] and row["is_financial_sic"] and not row["in_universe"]

    def test_reit_kept(self, con):
        row = universe_row(con, "O")
        assert row["siccode"] == 6798 and not row["is_financial_sic"] and row["in_universe"]

    def test_non_common_categories_excluded(self, con):
        for ticker in ("SPY", "BABA", "GOOG"):
            row = universe_row(con, ticker)
            assert not row["is_common_stock"] and not row["in_universe"], ticker

    def test_missing_sic_kept_and_flagged(self, con):
        row = universe_row(con, "NOSIC")
        assert row["in_universe"] and row["siccode_missing"]

    def test_financial_sector_nonfinancial_sic_kept(self, con):
        row = universe_row(con, "FINTECH")
        assert row["in_universe"] and row["is_financial_sector"] and not row["is_financial_sic"]

    def test_summary_counts(self, con, tmp_path):
        counts = write_universe_table(con, tmp_path / "interim")
        assert counts == {
            "universe_rows": 14,
            "in_universe": 10,  # 9 tickers, XYZ counted for both permatickers
            "in_universe_delisted": 4,  # WCOEQ, XYZ(old), NOSIC, NOFP
            "excluded_financials": 1,  # BAC
            "in_universe_missing_sic": 1,  # NOSIC
            "in_universe_financial_sector": 1,  # FINTECH
        }


class TestCounts:
    @pytest.fixture(autouse=True)
    def _views(self, con):
        build_universe_view(con)
        build_counts_view(con)

    def counts_by_year(self, con) -> dict[int, tuple[int, int]]:
        return {
            year: (still, delisted)
            for year, still, delisted, _total in con.execute(
                "SELECT * FROM universe_counts"
            ).fetchall()
        }

    def test_year_range_starts_at_earliest_first_price(self, con):
        years = self.counts_by_year(con)
        assert min(years) == 1994  # Realty Income's firstpricedate

    def test_known_years(self, con):
        years = self.counts_by_year(con)
        # 2000: AAPL, O alive; WCOEQ, XYZ(old) later delisted.
        assert years[2000] == (2, 2)
        # 2005: AAPL, O, GOOGL, XYZ(new) — nothing delisted-later active.
        assert years[2005] == (4, 0)
        # 2012: same four alive plus NOSIC (delisted 2015).
        assert years[2012] == (4, 1)

    def test_alive_stock_without_lastpricedate_counts_today(self, con):
        # FINTECH has no lastpricedate but isdelisted=N: active through today.
        years = self.counts_by_year(con)
        current_year = max(years)
        assert current_year >= 2026
        assert years[current_year][0] >= 6  # AAPL, O, GOOGL, XYZ, FINTECH, DUP

    def test_unplaceable_rows_skipped(self, con):
        # NOFP (no firstpricedate) must not appear in any year: totals across
        # a year it "existed" per lastupdated stay unaffected.
        total_delisted = sum(d for _s, d in self.counts_by_year(con).values())
        # WCOEQ 5 years (1998-2002) + XYZ old 3 (1999-2001) + NOSIC 6 (2010-2015)
        assert total_delisted == 14

    def test_start_year_clamp(self, con):
        build_counts_view(con, start_year=2000)
        first = con.execute("SELECT min(year) FROM universe_counts").fetchone()[0]
        assert first == 2000

    def test_write_and_plot(self, con, tmp_path):
        counts = write_counts_tables(con, tmp_path / "interim")
        assert (tmp_path / "interim" / "universe_counts_by_year.parquet").exists()
        csv_text = (tmp_path / "interim" / "universe_counts_by_year.csv").read_text()
        assert csv_text.startswith("year,still_listed,later_delisted,total")
        png = plot_universe_counts(counts, tmp_path / "reports" / "counts.png")
        assert png.stat().st_size > 10_000


def test_plot_rejects_empty():
    with pytest.raises(ValueError, match="no universe counts"):
        plot_universe_counts([], Path("/nonexistent/x.png"))


def test_yearcount_total():
    assert YearCount(2000, 3, 2).total == 5
