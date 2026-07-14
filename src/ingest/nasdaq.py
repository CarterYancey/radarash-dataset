"""Minimal client for Nasdaq Data Link datatable bulk exports.

The bulk-export flow (documented at
https://docs.data.nasdaq.com/docs/large-datasets) is:

1. ``GET /datatables/{code}.json?qopts.export=true`` — asks the server to
   (re)generate a zipped CSV export of the whole table and reports its status.
2. Poll the same endpoint until ``status`` is ``fresh``.
3. Download the zip from the returned S3 ``link``.

Implemented directly over ``requests`` (rather than the `nasdaq-data-link`
package) so we control polling, retries, and logging, and can test the flow
against a fake session.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

BASE_URL = "https://data.nasdaq.com/api/v3/datatables"
API_KEY_ENV_VAR = "NASDAQ_DATA_LINK_API_KEY"

STATUS_FRESH = "fresh"
_DOWNLOAD_CHUNK_BYTES = 4 * 1024 * 1024
_REQUEST_TIMEOUT_SECONDS = 120


class BulkExportError(RuntimeError):
    """A bulk-export API call failed or returned an unusable payload."""


@dataclass(frozen=True)
class ExportStatus:
    """One poll of the export endpoint for a table."""

    table: str
    status: str
    link: str | None
    data_snapshot_time: str | None
    last_refreshed_time: str | None

    @property
    def is_fresh(self) -> bool:
        return self.status == STATUS_FRESH and bool(self.link)


class BulkExportClient:
    def __init__(
        self,
        api_key: str,
        *,
        session: requests.Session | None = None,
        poll_interval: float = 30.0,
        poll_timeout: float = 3600.0,
        download_retries: int = 4,
    ) -> None:
        if not api_key:
            raise BulkExportError(
                f"missing Nasdaq Data Link API key (set {API_KEY_ENV_VAR})"
            )
        self._api_key = api_key
        self._session = session or requests.Session()
        self._poll_interval = poll_interval
        self._poll_timeout = poll_timeout
        self._download_retries = download_retries

    def export_status(self, table: str) -> ExportStatus:
        """Request/refresh the bulk export for `table` and report its status."""
        url = f"{BASE_URL}/{table}.json"
        response = self._session.get(
            url,
            params={"qopts.export": "true", "api_key": self._api_key},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code != 200:
            raise BulkExportError(
                f"export request for {table} failed with HTTP "
                f"{response.status_code}: {response.text[:500]}"
            )
        payload: dict[str, Any] = response.json()
        try:
            bulk = payload["datatable_bulk_download"]
            file_info = bulk["file"]
        except (KeyError, TypeError) as exc:
            raise BulkExportError(
                f"unexpected export payload for {table}: {payload!r:.500}"
            ) from exc
        datatable_info = bulk.get("datatable") or {}
        return ExportStatus(
            table=table,
            status=file_info.get("status", "unknown"),
            link=file_info.get("link"),
            data_snapshot_time=file_info.get("data_snapshot_time"),
            last_refreshed_time=datatable_info.get("last_refreshed_time"),
        )

    def wait_until_fresh(self, table: str) -> ExportStatus:
        """Poll until the export is fresh.

        If the timeout elapses but the server offers a link to an older
        snapshot (status ``regenerating``), return that with a warning rather
        than failing — a slightly stale bulk file is still a valid raw export.
        """
        deadline = time.monotonic() + self._poll_timeout
        status = self.export_status(table)
        while not status.is_fresh:
            if time.monotonic() >= deadline:
                if status.link:
                    logger.warning(
                        "%s: export still %r after %.0fs; using existing "
                        "snapshot from %s",
                        table,
                        status.status,
                        self._poll_timeout,
                        status.data_snapshot_time,
                    )
                    return status
                raise BulkExportError(
                    f"export for {table} not ready after "
                    f"{self._poll_timeout:.0f}s (status={status.status!r})"
                )
            logger.info(
                "%s: export status %r; polling again in %.0fs",
                table,
                status.status,
                self._poll_interval,
            )
            time.sleep(self._poll_interval)
            status = self.export_status(table)
        return status

    def download(self, url: str, dest: Path) -> Path:
        """Stream `url` to `dest`, retrying with exponential backoff."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        last_error: Exception | None = None
        for attempt in range(self._download_retries + 1):
            if attempt:
                backoff = 2.0**attempt
                logger.warning(
                    "download failed (%s); retry %d/%d in %.0fs",
                    last_error,
                    attempt,
                    self._download_retries,
                    backoff,
                )
                time.sleep(backoff)
            try:
                self._download_once(url, dest)
                return dest
            except (requests.RequestException, OSError) as exc:
                last_error = exc
        raise BulkExportError(f"download failed after retries: {last_error}")

    def _download_once(self, url: str, dest: Path) -> None:
        partial = dest.with_suffix(dest.suffix + ".part")
        with self._session.get(
            url, stream=True, timeout=_REQUEST_TIMEOUT_SECONDS
        ) as response:
            response.raise_for_status()
            total = response.headers.get("Content-Length")
            logger.info(
                "downloading %s (%s) -> %s",
                url.split("?")[0],
                f"{int(total) / 1e9:.2f} GB" if total else "size unknown",
                dest,
            )
            with partial.open("wb") as fh:
                for chunk in response.iter_content(chunk_size=_DOWNLOAD_CHUNK_BYTES):
                    fh.write(chunk)
        partial.replace(dest)
