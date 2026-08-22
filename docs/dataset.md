# Canonical dataset definitions (M5)

Produced by `sharadar-assemble` (`src/assemble/`), consuming
`data/interim/labels.parquet`, the nine family parquets under
`data/interim/features/`, and the split artifacts. Output is one
**versioned, immutable directory**:

```
data/datasets/dataset_vX.Y/
├── dataset.parquet       one row per snapshot: features × ranks × labels × weights
├── splits.parquet        verbatim copy of the split tags (docs/splits.md)
├── split_folds.parquet   verbatim copy of the frozen fold manifest
└── manifest.json         provenance: version, params, counts, column layout
```

Design decisions: ranks in [decisions/0008](decisions/0008-rank-representation.md),
assembly-stage composites in [decisions/0013](decisions/0013-assembly-stage-composites.md),
uniqueness weights in [decisions/0012](decisions/0012-uniqueness-weights.md).
An existing version directory is never overwritten (`--force` rebuilds it
explicitly; otherwise bump `--dataset-version`).

## `dataset.parquet` column groups, in order

| group | columns | source |
|---|---|---|
| key + entry metadata | `permaticker`, `ticker`, `quarter`, `quarter_trading_days`, `snapshot_kind`, `snapshot_date`, `entry_closeadj` | labels.parquet (docs/labels.md) |
| features | every registry feature, family build order, assembly-stage composites in place | family parquets + assembly (docs/features.md) |
| ranks | `{name}_rank` for every numeric feature | assembly (ADR 0008) |
| sector ranks | `{name}_secrank` for the allowlist | assembly (ADR 0008) |
| label matrix | the per-horizon `fwd_*` / `label_*` / `delisted_in_window_*` columns | labels.parquet (docs/labels.md) |
| weights | `sample_weight_{H}y` per horizon | assembly (ADR 0012) |

### Ranks (ADR 0008)

`percent_rank()` within **(calendar quarter, snapshot_kind)** over non-NULL
values; NULL raw ⇒ NULL rank; cross-sections with fewer than `--rank-guard`
(default 20) non-NULL values ⇒ NULL rank. `{name}_secrank` adds Sharadar
`sector` to the partition for the allowlisted features, same guard, NULL
sector ⇒ NULL. Ties share the lower percent rank.

### Assembly-stage composites (ADR 0013)

- `mohanram_g7` — sum of seven binary signals against `famaindustry`
  medians within (quarter, kind); medians need `--min-industry-peers`
  (default 5) non-NULL values; any NULL signal ⇒ NULL. Sits in the quality
  family's column block.
- `conservative_score` — `(1 − vol_36m_rank) + mom_12_2_rank +
  net_payout_yield_rank`, range [0, 3]; NULL if any input rank is NULL.
  Sits in the technical family's column block. Both composites are ranked
  like any numeric feature.

### Uniqueness weights (ADR 0012)

`sample_weight_{H}y` = exact day-granularity average uniqueness of the
row's nominal label window `[snapshot_date, snapshot_date + H]` against all
same-permaticker windows of that horizon, all three snapshot kinds pooled
(an isolated stock-quarter's three rows weigh 1/3 each). In (0, 1];
unnormalized; NULL exactly where the horizon's label is unobservable.
Downstream models pass it as a native sample weight; per-horizon sums (the
honest effective sample size, PLAN §7.2) are logged at assembly and stored
in the manifest.

## `manifest.json`

| field | meaning |
|---|---|
| `dataset_version`, `created_utc` | identity of the build |
| `horizons_years` | horizons carried by the label matrix |
| `params` | `rank_guard`, `min_industry_peers` |
| `rows`, `permatickers` | dataset size |
| `effective_rows` | Σ `sample_weight_{H}y` per horizon |
| `columns` | the full column layout by group, in order |
| `feature_versions` | per-feature `added`/`removed` version from the registry |
| `input_rows` | row counts of every input parquet at build time |

Downstream (`value-ml-models`) pins a `dataset_vX.Y`, selects training data
via `splits.parquet` roles (`docs/splits.md`), and must cite
`split_folds.parquet` in reports. Assembly validates every family parquet
against `src/features/registry.py` before joining and refuses misaligned
inputs, so a dataset directory is internally consistent by construction.

## The inference dataset (ADR 0014)

Produced by `sharadar-inference` (`src/inference/`, `make inference`) from
the ingest + identity artifacts only — no labels, features, or splits
stages required. One snapshot per in-universe stock at its **latest
available price**, for a trained model to score:

```
data/datasets/inference_{as_of}/
├── dataset.parquet       one row per tradable stock: features × ranks
└── manifest.json         provenance: as_of, params, counts, column layout
```

- `as_of` = last trading date in SEP on or before `--as-of` (default: the
  last date in SEP). Stocks whose most recent trade is within
  `--max-price-age-days` (default 5) trading days of `as_of` are included;
  `snapshot_date`/`entry_closeadj` are the stock's own last print.
- `snapshot_kind` = `'inference'` for every row; `quarter` is uniform (the
  calendar quarter of `as_of`), so the ADR 0008 rank pass ranks the whole
  inference cross-section as one partition. Same guards, same composites,
  same feature code as training — including the T1–T3 lags.
- Fundamentals as-of is **inclusive** (`datekey <= snapshot_date`): the
  conceptual entry is the next trading day, so a same-day filing is public
  before any actionable trade (ADR 0014; training keeps the strict rule).
- Columns are the training layout minus everything forward-looking: key +
  entry metadata (no `quarter_trading_days`), features, ranks, sector
  ranks — no label matrix, no split files, no `sample_weight_{H}y`. A
  model selects its feature/rank columns by name and scores directly.
- The manifest mirrors the training manifest with `dataset_kind:
  "inference"`, `as_of`, and `rows_with_stale_price` (rows whose last
  print predates `as_of`) instead of horizons/effective rows.

The inference cross-section is survivor-only by design (today's tradable
stocks); it must never be used for training or evaluation.
