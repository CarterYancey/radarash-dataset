import json
import shutil
from pathlib import Path

import duckdb

from ingest import download as download_mod
from ingest.nasdaq import ExportStatus

from conftest import EVENTS_CSV, TICKERS_CSV, make_export_zip


class FakeClient:
    """Stands in for BulkExportClient: 'downloads' pre-built fixture zips."""

    def __init__(self, zips_by_table: dict[str, Path]):
        self.zips = zips_by_table

    def wait_until_fresh(self, table: str) -> ExportStatus:
        return ExportStatus(
            table=table,
            status="fresh",
            link=f"https://s3/{table}.zip",
            data_snapshot_time="2026-07-10 21:03:11 UTC",
            last_refreshed_time="2026-07-12 01:00:00 UTC",
        )

    def download(self, url: str, dest: Path) -> Path:
        table = url.rsplit("/", 2)[-1].removesuffix(".zip")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(self.zips[table], dest)
        return dest


def install_fake_client(monkeypatch, tmp_path) -> FakeClient:
    fake = FakeClient(
        {
            "TICKERS": make_export_zip(tmp_path / "fixtures" / "TICKERS.zip", TICKERS_CSV),
            "EVENTS": make_export_zip(tmp_path / "fixtures" / "EVENTS.zip", EVENTS_CSV),
        }
    )
    monkeypatch.setattr(download_mod, "BulkExportClient", lambda *a, **k: fake)
    return fake


def run_cli(tmp_path, *extra_args) -> int:
    data_dir = tmp_path / "data"
    argv = [
        "--tables", "TICKERS", "EVENTS",
        "--data-dir", str(data_dir),
        "--api-key", "test-key",
        *extra_args,
    ]
    return download_mod.main(argv)


def test_cli_end_to_end(tmp_path, monkeypatch):
    install_fake_client(monkeypatch, tmp_path)
    assert run_cli(tmp_path) == 0

    raw = tmp_path / "data" / "raw"
    for table, expected_rows in (("TICKERS", 4), ("EVENTS", 3)):
        parquet = raw / f"{table}.parquet"
        assert duckdb.sql(f"SELECT count(*) FROM read_parquet('{parquet}')").fetchone()[0] == expected_rows
        meta = json.loads((raw / f"{table}.meta.json").read_text())
        assert meta["table"] == f"SHARADAR/{table}"
        assert meta["rows"] == expected_rows
        assert meta["source_status"] == "fresh"
        assert len(meta["zip_sha256"]) == 64
    # Staging zips removed by default.
    assert not list((raw / ".staging").glob("*.zip"))


def test_cli_skips_existing_unless_forced(tmp_path, monkeypatch):
    install_fake_client(monkeypatch, tmp_path)
    assert run_cli(tmp_path) == 0
    raw = tmp_path / "data" / "raw"
    before = (raw / "TICKERS.parquet").stat().st_mtime_ns

    assert run_cli(tmp_path) == 0
    assert (raw / "TICKERS.parquet").stat().st_mtime_ns == before

    assert run_cli(tmp_path, "--force") == 0
    assert (raw / "TICKERS.parquet").stat().st_mtime_ns != before


def test_cli_keep_zip(tmp_path, monkeypatch):
    install_fake_client(monkeypatch, tmp_path)
    assert run_cli(tmp_path, "--keep-zip") == 0
    staging = tmp_path / "data" / "raw" / ".staging"
    assert {p.name for p in staging.glob("*.zip")} == {"TICKERS.zip", "EVENTS.zip"}


def test_cli_unknown_table_is_usage_error(tmp_path):
    assert download_mod.main(["--tables", "BOGUS", "--api-key", "k"]) == 2


def test_cli_missing_api_key(tmp_path, monkeypatch):
    monkeypatch.delenv("NASDAQ_DATA_LINK_API_KEY", raising=False)
    assert download_mod.main(["--tables", "TICKERS", "--data-dir", str(tmp_path)]) == 2


def test_cli_continues_after_table_failure(tmp_path, monkeypatch):
    fake = install_fake_client(monkeypatch, tmp_path)
    del fake.zips["TICKERS"]  # TICKERS download will blow up
    assert run_cli(tmp_path) == 1
    # EVENTS still ingested despite the earlier failure.
    assert (tmp_path / "data" / "raw" / "EVENTS.parquet").exists()
