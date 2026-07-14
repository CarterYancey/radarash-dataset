"""Testable client for Nasdaq Data Link bulk table exports."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

API_ROOT = "https://data.nasdaq.com/api/v3/datatables"


class BulkExportError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExportInfo:
    link: str
    status: str
    data_snapshot_time: str | None = None
    last_refreshed_time: str | None = None


def _parse_export(payload: dict[str, Any]) -> ExportInfo:
    try:
        item = payload["datatable_bulk_download"]["file"]
        status = str(item["status"])
    except (KeyError, TypeError) as error:
        message = payload.get("quandl_error", {}).get("message", "Malformed bulk-export response")
        raise BulkExportError(message) from error
    return ExportInfo(
        str(item.get("link") or ""),
        status,
        item.get("data_snapshot_time"),
        item.get("last_refreshed_time"),
    )


def wait_for_export(
    table_code: str,
    api_key: str,
    *,
    poll_seconds: float = 30,
    timeout_seconds: float = 7200,
    session: requests.Session | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ExportInfo:
    client = session or requests.Session()
    endpoint = f"{API_ROOT}/{table_code}.json"
    started = time.monotonic()
    while True:
        response = client.get(
            endpoint,
            params={"api_key": api_key, "qopts.export": "true"},
            timeout=60,
        )
        response.raise_for_status()
        info = _parse_export(response.json())
        if info.status == "fresh" and info.link:
            return info
        if info.status not in {"creating", "regenerating"}:
            raise BulkExportError(f"Unexpected export status for {table_code}: {info.status!r}")
        if time.monotonic() - started >= timeout_seconds:
            raise TimeoutError(f"Timed out waiting for {table_code} bulk export ({info.status})")
        sleep(poll_seconds)


def download_export(
    info: ExportInfo,
    destination: Path,
    *,
    session: requests.Session | None = None,
) -> str:
    client = session or requests.Session()
    digest = hashlib.sha256()
    with client.get(info.link, stream=True, timeout=(30, 600)) as response:
        response.raise_for_status()
        with destination.open("wb") as output:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    digest.update(chunk)
                    output.write(chunk)
    if destination.stat().st_size == 0:
        raise BulkExportError("Nasdaq returned an empty bulk-export file")
    return digest.hexdigest()
