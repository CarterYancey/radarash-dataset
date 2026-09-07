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
├── rank_audit.parquet    quarter-key audit of every rank column (ADR 0016)
└── manifest.json         provenance: version, params, counts, column layout
```

Design decisions: ranks in [decisions/0008](decisions/0008-rank-representation.md)
with the per-feature policy and audit of [decisions/0016](decisions/0016-rank-quarter-keys.md),
assembly-stage composites in [decisions/0013](decisions/0013-assembly-stage-composites.md),
uniqueness weights in [decisions/0012](decisions/0012-uniqueness-weights.md).
An existing version directory is never overwritten (`--force` rebuilds it
explicitly; otherwise bump `--dataset-version`).

## `dataset.parquet` column groups, in order

| group | columns | source |
|---|---|---|
| key + entry metadata | `permaticker`, `ticker`, `quarter`, `quarter_trading_days`, `snapshot_kind`, `snapshot_date`, `entry_closeadj` | labels.parquet (docs/labels.md) |
| features | every registry feature, family build order, assembly-stage composites in place | family parquets + assembly (docs/features.md) |
| ranks | `{name}_rank` for every numeric feature whose rank policy is not `none` | assembly (ADR 0008, 0016) |
| sector ranks | `{name}_secrank` for the allowlist | assembly (ADR 0008, 0016) |
| label matrix | the per-horizon `fwd_*` / `label_*` / `delisted_in_window_*` columns | labels.parquet (docs/labels.md) |
| weights | `sample_weight_{H}y` per horizon | assembly (ADR 0012) |

### Ranks (ADR 0008, per-feature policy ADR 0016)

`percent_rank()` within **(calendar quarter, snapshot_kind)** over non-NULL
values; NULL raw ⇒ NULL rank; cross-sections with fewer than `--rank-guard`
(default 20) non-NULL values ⇒ NULL rank. `{name}_secrank` adds Sharadar
`sector` to the partition for the allowlisted features, same guard, NULL
sector ⇒ NULL. Ties share the lower percent rank.

A tied group's percent rank is the share of the quarter's cross-section
below it — a quarter-specific constant, i.e. a calendar-quarter key for a
tree model (research/rank-quarter-keys.md). Each feature therefore carries
a **rank policy** in the registry (`manifest.json["rank_policy"]`,
docs/features.md notes):

| policy | columns emitted | rule |
|---|---|---|
| `full` | `_rank` (+ `_secrank` if allowlisted) | the percent rank above; continuous features |
| `pinned` (mass at raw *v*, rank *r*) | same | rows at exactly *v* rank *r* in every quarter; the rest are percent-ranked within their side of the pin, below onto [0, *r*], above onto [*r*, 1] — the mass's rank is a fixed constant, not the quarter's share below it |
| `none` | no rank columns | integer-valued composites, counts and shares (`piotroski_f`, `mohanram_g7`, `fundamentals_age_days`, `fund_history_quarters`, `div_*_10y`, `*_up_frac_*`, `ocf_positive_frac_*`): the raw score is already cross-sectionally comparable |

Pins in v1.2 (mass at raw 0 unless stated): rank 0 for `dividend_yield`,
`rnd_to_assets`, `capex_to_assets`, `debt_to_equity`, `sales_yield`,
`asset_turnover`; rank 0.5 for the signed `net_payout_yield`,
`ext_financing_to_assets`, `share_count_growth_1y`, `gp_to_assets`,
`asset_turnover_delta_1y`, `gross_margin_delta_1y`, `gross_margin_delta_2y`,
`ni_change_scaled`, `ret_1m`; rank 1 for `dist_52w_high` (≤ 0, zero = at
the 52-week high); mass at raw **1**: `gross_margin` (rank 1 — no cost of
revenue reported), `gmi` and `ev_to_marketcap` (rank 0.5).

### Rank audit (ADR 0016)

After `dataset.parquet` is written, every rank and sector-rank column is
measured per snapshot kind on the parquet and the table is written to
`rank_audit.parquet` (`rank_column`, `snapshot_kind`, `n_rows`, `quarters`,
`distinct_values`, `distinct_quarter_value_pairs`, `tie_mass`, `keyed_mass`,
`max_key_share`, `key_quarter`, `key_rank_value`, `key_raw_value`).
`tie_mass` = share of rows whose rank value is shared
with another row of the same (quarter, kind); `keyed_mass` = share of rows
in tie groups whose value occurs in exactly one quarter; `max_key_share` =
the largest such keyed group as a share of its cross-section, and the
`key_*` columns locate it (its quarter, the rank value it shares, and the
raw feature value behind it — the raw value decides the registry fix). The
build **fails and removes the directory** when any `max_key_share` exceeds
`--max-key-share` (default 0.02), naming each column with its worst group,
and keeps the audit table as `data/interim/qa/rank_audit_v{version}.{parquet,csv}`;
`--allow-rank-keys` publishes anyway and lists them in
`manifest.json["rank_audit"]["flagged"]`.
The gate is `max_key_share`, not `tie_mass`: fine-grained integer columns
tie nearly every row without emitting a resolvable constant, while a
pinned mass is tied in every quarter but never keyed.

### Assembly-stage composites (ADR 0013)

- `mohanram_g7` — sum of seven binary signals against `famaindustry`
  medians within (quarter, kind); medians need `--min-industry-peers`
  (default 5) non-NULL values; any NULL signal ⇒ NULL. Sits in the quality
  family's column block.
- `conservative_score` — `(1 − vol_36m_rank) + mom_12_2_rank +
  net_payout_yield_rank` (the last pinned at 0 → 0.5, ADR 0016), range
  [0, 3]; NULL if any input rank is NULL. Sits in the technical family's
  column block and is ranked (`full`); `mohanram_g7` is an integer score and
  is not ranked (ADR 0016).

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
| `params` | `rank_guard`, `min_industry_peers`, `max_key_share`, `allow_rank_keys` |
| `rows`, `permatickers` | dataset size |
| `effective_rows` | Σ `sample_weight_{H}y` per horizon |
| `columns` | the full column layout by group, in order |
| `rank_policy` | per ranked feature: `{"rank": "full"}` or `{"rank": "pinned", "pin_value": v, "pin_rank": r}` (ADR 0016); unranked numerics are absent |
| `rank_audit` | `max_key_share_threshold`, `flagged` (rank column → worst `max_key_share` over kinds, empty on a clean build), `columns` (per rank column: worst `tie_mass`, `keyed_mass`, `max_key_share` over kinds) |
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
  model selects its feature/rank columns by name and scores directly. The
  rank policy (ADR 0016) is the training one verbatim; there is no rank
  audit — a single-partition cross-section has no quarter to key.
- The manifest mirrors the training manifest (`rank_policy` included) with
  `dataset_kind: "inference"`, `as_of`, and `rows_with_stale_price` (rows
  whose last print predates `as_of`) instead of horizons/effective rows.

The inference cross-section is survivor-only by design (today's tradable
stocks); it must never be used for training or evaluation.
