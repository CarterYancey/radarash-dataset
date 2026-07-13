import json
from pathlib import Path

import pytest
import requests

from ingest.nasdaq import BulkExportClient, BulkExportError


class FakeResponse:
    def __init__(self, *, status_code=200, payload=None, content=b"", headers=None):
        self.status_code = status_code
        self._payload = payload
        self._content = content
        self.headers = headers or {}
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeSession:
    """Returns queued responses; records the requests it saw."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def export_payload(status, link="https://s3/export.zip"):
    return {
        "datatable_bulk_download": {
            "file": {
                "status": status,
                "link": link if status != "creating" else None,
                "data_snapshot_time": "2026-07-10 21:03:11 UTC",
            },
            "datatable": {"last_refreshed_time": "2026-07-12 01:00:00 UTC"},
        }
    }


def make_client(session, **kwargs):
    kwargs.setdefault("poll_interval", 0.0)
    return BulkExportClient("test-key", session=session, **kwargs)


def test_requires_api_key():
    with pytest.raises(BulkExportError, match="API key"):
        BulkExportClient("")


def test_export_status_parses_payload_and_sends_key():
    session = FakeSession([FakeResponse(payload=export_payload("fresh"))])
    status = make_client(session).export_status("SHARADAR/SF1")
    assert status.is_fresh
    assert status.link == "https://s3/export.zip"
    assert status.last_refreshed_time == "2026-07-12 01:00:00 UTC"
    url, kwargs = session.calls[0]
    assert url.endswith("/datatables/SHARADAR/SF1.json")
    assert kwargs["params"] == {"qopts.export": "true", "api_key": "test-key"}


def test_export_status_http_error():
    session = FakeSession([FakeResponse(status_code=403, payload={"quandl_error": {}})])
    with pytest.raises(BulkExportError, match="HTTP 403"):
        make_client(session).export_status("SHARADAR/SF1")


def test_wait_until_fresh_polls_through_creating():
    session = FakeSession(
        [
            FakeResponse(payload=export_payload("creating")),
            FakeResponse(payload=export_payload("regenerating")),
            FakeResponse(payload=export_payload("fresh")),
        ]
    )
    status = make_client(session).wait_until_fresh("SHARADAR/TICKERS")
    assert status.is_fresh
    assert len(session.calls) == 3


def test_wait_until_fresh_timeout_falls_back_to_stale_link():
    session = FakeSession([FakeResponse(payload=export_payload("regenerating"))])
    status = make_client(session, poll_timeout=0.0).wait_until_fresh("SHARADAR/SEP")
    assert status.status == "regenerating"
    assert status.link


def test_wait_until_fresh_timeout_without_link_raises():
    session = FakeSession([FakeResponse(payload=export_payload("creating"))])
    with pytest.raises(BulkExportError, match="not ready"):
        make_client(session, poll_timeout=0.0).wait_until_fresh("SHARADAR/SEP")


def test_download_streams_to_file(tmp_path: Path):
    body = b"zip-bytes" * 1000
    session = FakeSession([FakeResponse(content=body, headers={"Content-Length": str(len(body))})])
    dest = tmp_path / "dl" / "SF1.zip"
    make_client(session).download("https://s3/export.zip", dest)
    assert dest.read_bytes() == body
    assert not dest.with_suffix(".zip.part").exists()


def test_download_retries_then_succeeds(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("ingest.nasdaq.time.sleep", lambda s: None)
    body = b"payload"
    session = FakeSession(
        [
            requests.ConnectionError("reset"),
            FakeResponse(status_code=500),
            FakeResponse(content=body),
        ]
    )
    dest = tmp_path / "t.zip"
    make_client(session, download_retries=4).download("https://s3/x.zip", dest)
    assert dest.read_bytes() == body
    assert len(session.calls) == 3


def test_download_gives_up_after_retries(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("ingest.nasdaq.time.sleep", lambda s: None)
    session = FakeSession([requests.ConnectionError("reset")] * 3)
    with pytest.raises(BulkExportError, match="after retries"):
        make_client(session, download_retries=2).download("https://s3/x.zip", tmp_path / "t.zip")
