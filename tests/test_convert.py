import zipfile
from pathlib import Path

import duckdb
import pytest

from ingest.convert import ConversionError, zip_to_parquet
from ingest.tables import TABLES

from conftest import make_export_zip


def test_tickers_zip_roundtrip(tickers_zip: Path, tmp_path: Path):
    out = tmp_path / "out" / "TICKERS.parquet"
    rows = zip_to_parquet(tickers_zip, TABLES["TICKERS"], out)
    assert rows == 4
    assert out.exists()

    con = duckdb.connect()
    rel = con.sql(f"SELECT * FROM read_parquet('{out}')")
    schema = dict(zip(rel.columns, [str(t) for t in rel.types]))
    # The ticker "TRUE" must survive as text, not a boolean.
    assert schema["ticker"] == "VARCHAR"
    assert schema["permaticker"] == "BIGINT"
    assert schema["isdelisted"] == "VARCHAR"
    assert schema["lastupdated"] == "DATE"
    tickers = {r[0] for r in con.sql(f"SELECT ticker FROM read_parquet('{out}')").fetchall()}
    assert "TRUE" in tickers

    # Sorted by (table, permaticker) per the spec.
    ordered = con.sql(
        f'SELECT "table", permaticker FROM read_parquet(\'{out}\')'
    ).fetchall()
    assert ordered == sorted(ordered)


def test_events_multicodes_preserved(events_zip: Path, tmp_path: Path):
    out = tmp_path / "EVENTS.parquet"
    rows = zip_to_parquet(events_zip, TABLES["EVENTS"], out)
    assert rows == 3
    codes = duckdb.sql(
        f"SELECT eventcodes FROM read_parquet('{out}') WHERE ticker = 'ENRNQ'"
    ).fetchone()[0]
    assert codes == "13,21,52"


def test_no_sort_keeps_file_valid(tickers_zip: Path, tmp_path: Path):
    out = tmp_path / "TICKERS.parquet"
    rows = zip_to_parquet(tickers_zip, TABLES["TICKERS"], out, sort=False)
    assert rows == 4


def test_zip_with_multiple_csvs_rejected(tmp_path: Path):
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as archive:
        archive.writestr("a.csv", "x\n1\n")
        archive.writestr("b.csv", "x\n2\n")
    with pytest.raises(ConversionError, match="exactly one CSV"):
        zip_to_parquet(bad, TABLES["EVENTS"], tmp_path / "out.parquet")


def test_output_written_atomically(tickers_zip: Path, tmp_path: Path):
    out = tmp_path / "TICKERS.parquet"
    zip_to_parquet(tickers_zip, TABLES["TICKERS"], out)
    assert not out.with_suffix(".parquet.tmp").exists()
    # No leftover extraction dirs.
    assert not list(tmp_path.glob(".extract_*"))


def test_numeric_looking_ticker_column(tmp_path: Path):
    # A file where every ticker looks numeric must still produce VARCHAR.
    csv = "date,ticker,eventcodes\n2020-01-01,123,55\n"
    zp = make_export_zip(tmp_path / "n.zip", csv)
    out = tmp_path / "n.parquet"
    zip_to_parquet(zp, TABLES["EVENTS"], out)
    rel = duckdb.sql(f"SELECT ticker, eventcodes FROM read_parquet('{out}')")
    assert [str(t) for t in rel.types] == ["VARCHAR", "VARCHAR"]
