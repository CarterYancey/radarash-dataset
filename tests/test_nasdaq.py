import hashlib

import pytest

from ingest.nasdaq import BulkExportError, ExportInfo, download_export, wait_for_export


class Response:
    def __init__(self, payload=None, chunks=()):
        self.payload = payload
        self.chunks = chunks

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload

    def iter_content(self, chunk_size):
        return iter(self.chunks)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return next(self.responses)


def payload(status, link=None):
    return {"datatable_bulk_download": {"file": {"status": status, "link": link}}}


def test_wait_for_export_polls_regenerating_status():
    session = Session([Response(payload("regenerating")), Response(payload("fresh", "https://file"))])
    sleeps = []
    result = wait_for_export("SHARADAR/SEP", "secret", session=session, sleep=sleeps.append)
    assert result.link == "https://file"
    assert sleeps == [30]
    assert session.calls[0][1]["params"]["api_key"] == "secret"


def test_wait_for_export_rejects_unknown_status():
    with pytest.raises(BulkExportError, match="Unexpected"):
        wait_for_export("SHARADAR/SEP", "secret", session=Session([Response(payload("failed"))]))


def test_download_export_streams_and_hashes(tmp_path):
    session = Session([Response(chunks=[b"abc", b"def"])])
    destination = tmp_path / "table.zip"
    digest = download_export(ExportInfo("https://file", "fresh"), destination, session=session)
    assert destination.read_bytes() == b"abcdef"
    assert digest == hashlib.sha256(b"abcdef").hexdigest()
