import duckdb

from identity import cli


def test_cli_end_to_end(identity_tickers_parquet, tmp_path):
    # The fixture already placed TICKERS.parquet under tmp_path/raw/.
    data_dir = identity_tickers_parquet.parent.parent
    assert cli.main(["--data-dir", str(data_dir)]) == 0

    interim = data_dir / "interim"
    for name in (
        "ticker_permaticker.parquet",
        "ticker_reuse.parquet",
        "universe.parquet",
        "universe_counts_by_year.parquet",
        "universe_counts_by_year.csv",
    ):
        assert (interim / name).exists(), name
    assert (interim / "reports" / "universe_counts_by_year.png").stat().st_size > 10_000

    in_universe = duckdb.sql(
        f"SELECT count(*) FROM '{interim / 'universe.parquet'}' WHERE in_universe"
    ).fetchone()[0]
    assert in_universe == 10


def test_cli_start_year(identity_tickers_parquet):
    data_dir = identity_tickers_parquet.parent.parent
    assert cli.main(["--data-dir", str(data_dir), "--start-year", "2005"]) == 0
    first = duckdb.sql(
        f"SELECT min(year) FROM '{data_dir / 'interim' / 'universe_counts_by_year.parquet'}'"
    ).fetchone()[0]
    assert first == 2005


def test_cli_missing_tickers_parquet(tmp_path):
    assert cli.main(["--data-dir", str(tmp_path)]) == 2
