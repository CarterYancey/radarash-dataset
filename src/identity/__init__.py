"""Identity layer: ticker↔permaticker mapping and universe construction.

Consumes `data/raw/TICKERS.parquet` (produced by `ingest`) and produces, under
`data/interim/`:

- ``ticker_permaticker.parquet`` — the canonical ticker↔permaticker mapping
  (first pipeline artifact per README §2); `permaticker` is the entity key,
  `ticker` is a join key only.
- ``ticker_reuse.parquet`` — tickers mapping to multiple permatickers, the
  raw material for verification task V2.
- ``universe.parquet`` — one row per permaticker with the README §3 inclusion
  flags and the final `in_universe` verdict.
- ``universe_counts_by_year.parquet`` + a plot — in-universe counts per year
  split by still-listed vs later-delisted (M1 exit artifact, feeds V3).
"""
