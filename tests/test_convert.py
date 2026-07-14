import csv
import zipfile

import duckdb
import pytest

from ingest.convert import zip_to_parquet


def make_export(tmp_path, rows):
    csv_path = tmp_path / "SHARADAR_TICKERS.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=["table", "permaticker", "ticker", "lastpricedate"])
        writer.writeheader()
        writer.writerows(rows)
    zip_path = tmp_path / "export.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(csv_path, csv_path.name)
    return zip_path


def test_zip_to_parquet_is_sorted_typed_and_queryable(tmp_path):
    archive = make_export(
        tmp_path,
        [
            {"table": "SEP", "permaticker": "20", "ticker": "B", "lastpricedate": "2020-01-02"},
            {"table": "SEP", "permaticker": "10", "ticker": "A", "lastpricedate": "2020-01-01"},
        ],
    )
    output = tmp_path / "TICKERS.parquet"

    stats = zip_to_parquet(archive, output, ("table", "permaticker"))

    assert stats.rows == 2
    assert stats.columns == ("table", "permaticker", "ticker", "lastpricedate")
    result = duckdb.sql(
        "SELECT permaticker, ticker, typeof(lastpricedate) "
        'FROM read_parquet(?) ORDER BY "table", permaticker',
        params=[str(output)],
    ).fetchall()
    assert result == [(10, "A", "DATE"), (20, "B", "DATE")]


def test_zip_rejects_nested_member(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../table.csv", "ticker,date\nA,2020-01-01\n")
    with pytest.raises(ValueError, match="Unsafe"):
        zip_to_parquet(archive, tmp_path / "out.parquet")
