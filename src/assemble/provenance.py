"""Build provenance for dataset manifests (decision 0021).

A dataset is a function of (code, raw snapshot, params). The params were
always in the manifest; this module records the other two plus a content
fingerprint of what was written, so two builds that share a version label
but differ can be told apart by diffing manifests:

- `raw_sources`: per raw table, the Sharadar snapshot it came from — copied
  from `data/raw/<TABLE>.meta.json` (written by `sharadar-ingest`). Tables
  without a meta file (e.g. hand-built test fixtures) map to null.
- `code`: the git commit of this checkout and whether the tree was dirty.
- `files`: sha256 + byte size of every file in the output directory.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

RAW_META_FIELDS = (
    "source_data_snapshot_time",
    "source_last_refreshed_time",
    "zip_sha256",
    "rows",
    "ingested_at",
)

_REPO_ROOT = Path(__file__).resolve().parents[2]


def raw_sources(raw_dir: Path) -> dict[str, dict | None]:
    """Per raw parquet in `raw_dir`: its ingest provenance, or None."""
    sources: dict[str, dict | None] = {}
    for parquet in sorted(raw_dir.glob("*.parquet")):
        meta_path = raw_dir / f"{parquet.stem}.meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            sources[parquet.stem] = {k: meta.get(k) for k in RAW_META_FIELDS}
        else:
            sources[parquet.stem] = None
    return sources


def raw_newer_than(raw_dir: Path, inputs: list[Path]) -> list[str]:
    """Raw tables modified after the oldest of `inputs` was written.

    Non-empty means the interim artifacts predate the current raw ingest,
    so `raw_sources` would not describe the data actually assembled."""
    oldest = min(p.stat().st_mtime for p in inputs)
    return sorted(
        p.stem for p in raw_dir.glob("*.parquet") if p.stat().st_mtime > oldest
    )


def code_version() -> dict[str, object]:
    """Git commit + dirty flag of this checkout (nulls outside a repo)."""

    def git(*args: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", "-C", str(_REPO_ROOT), *args],
                capture_output=True, text=True, check=True, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        return out.stdout.strip()

    commit = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=no")
    return {
        "git_commit": commit or None,
        "git_dirty": None if status is None else bool(status),
    }


def file_fingerprints(out_dir: Path) -> dict[str, dict[str, object]]:
    """sha256 + bytes of every regular file in `out_dir` (manifest excluded)."""
    prints = {}
    for path in sorted(out_dir.iterdir()):
        if not path.is_file() or path.name == "manifest.json":
            continue
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                digest.update(chunk)
        prints[path.name] = {
            "sha256": digest.hexdigest(),
            "bytes": path.stat().st_size,
        }
    return prints


def provenance(out_dir: Path, raw_dir: Path) -> dict[str, object]:
    """The manifest's provenance block for a freshly written `out_dir`."""
    code = code_version()
    if code["git_dirty"]:
        logger.warning(
            "building from a dirty working tree (commit %s); the manifest "
            "records git_dirty=true", code["git_commit"],
        )
    return {
        "raw_sources": raw_sources(raw_dir),
        "code": code,
        "files": file_fingerprints(out_dir),
    }
