"""Bulk download and ingestion of Sharadar tables from Nasdaq Data Link.

The ingest layer produces `data/raw/<TABLE>.parquet` — immutable, typed
parquet exports of the raw Sharadar tables — plus a JSON metadata sidecar
per table recording provenance (source refresh time, row count, checksum).
Everything downstream (identity, snapshots, features, labels) reads these
parquet files through DuckDB and never talks to the network.
"""
