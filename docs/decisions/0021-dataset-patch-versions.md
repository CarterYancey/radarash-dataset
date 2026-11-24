# 0021 — Dataset patch versions and build provenance

Date: 2026-11-24
Status: accepted

## Context

`dataset_v1.4` was accidentally deleted and rebuilt with the same code
and the same version label. The rebuild came out different: between the
two builds, `sharadar-ingest` had replaced `data/raw/` with a newer
Sharadar snapshot (2026-11-21 instead of the late-September one). The new
data had more price history to complete forward labels, plus Sharadar's
revisions to fundamentals, ticker metadata, and `closeadj`. A downstream
experiment rerun on "v1.4" with the same seed and settings gave different
results, and the cause took a long time to find for two reasons:

1. **One label covered two different builds.** The version said what
   *code* built the dataset, not what *data* it was built from.
2. **The manifest couldn't show it.** It recorded params, counts and
   layout, but not the raw snapshot, the code commit, or a fingerprint
   of the output. Two "v1.4" manifests looked the same.

A dataset is a function of (code, raw snapshot, params). All three
belong in its identity.

Also, the version was effectively set by editing `DEFAULT_VERSION` in
source. `sharadar-assemble --dataset-version` existed, but `make` didn't
expose it.

## Decision

**Version scheme `X.Y[.Z]`.**

- `X.Y` is a code/schema release: features, labels, splits, ranks,
  weights, or default params changed. Bump `DEFAULT_VERSION` in
  `src/assemble/cli.py` in the same change. Registry `added_in_version`
  values use `X.Y`.
- `X.Y.Z` (Z ≥ 1) is a **patch**: the same `X.Y` code rebuilt on a
  different raw ingest, or a fix that leaves the column layout alone.
  `X.Y` with no third part is the first build (patch 0); existing
  directories `dataset_v1.0`…`dataset_v1.4` keep their names.
- A version label names exactly one build. Each rebuild gets the next
  free patch number. `--force` is for re-running a build that failed,
  not for replacing a published one.
- Pick the version at build time: `make all VERSION=1.4.1` or
  `make dataset VERSION=1.4.1`, which pass `--dataset-version`.
  Experimental builds can keep using a suffix (`1.4-guard20`).

**Provenance block in `manifest.json`** (`src/assemble/provenance.py`;
written by both `sharadar-assemble` and `sharadar-inference`):

- `raw_sources`: per raw table, `source_data_snapshot_time`,
  `source_last_refreshed_time`, `zip_sha256`, `rows`, `ingested_at`,
  copied from `data/raw/<TABLE>.meta.json`. Null for tables that have
  no meta file.
- `code`: `git_commit` and `git_dirty` (tracked files modified). A
  dirty build logs a warning.
- `files`: sha256 and byte size of every output file.

Assembly logs a warning when a raw parquet is newer than the oldest
interim input. That means someone re-ingested without rerunning
`make all`, so `raw_sources` wouldn't describe the assembled data.

## Consequences

- When the same version gives different results, diff the manifests'
  `provenance`. Downstream should record
  `provenance.files["dataset.parquet"].sha256` with every result
  (`docs/manual.md` §1), so it can tell whether two runs used the same
  bytes.
- Rebuilding a deleted version still won't reproduce it unless the old
  raw ingest still exists, because ingest overwrites `data/raw/`. The
  manifest now *detects* this but can't *prevent* it. Keeping dated
  copies of raw ingests is a separate, open decision (disk cost around
  2 GB per snapshot).
- Hashing adds a few seconds per build (about 2 GB of output).
- The `dataset_v1.4` that exists on 2026-11-24 is the rebuild on the
  2026-11-21 snapshot, not the original. Its manifest has no provenance
  block because it predates this decision.
