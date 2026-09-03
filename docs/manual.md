# Dataset user manual (for `value-ml-models`)

How to consume a `data/datasets/dataset_vX.Y/` directory honestly. This is
the contract between this repo and the downstream modeling repo: follow it
and your validation metrics mean what they claim; break it and you quietly
reintroduce the survivorship bias and leakage this pipeline exists to remove.

Canonical column-level definitions live in [dataset.md](dataset.md),
[labels.md](labels.md), [splits.md](splits.md), and [features.md](features.md);
this manual tells you how to *use* them together. Design rationale: PLAN.md.

## 1. What you get

One versioned, immutable directory:

```
dataset_v1.2/
├── dataset.parquet       one row per snapshot: key, features, ranks, labels, weights
├── splits.parquet        role tags per (scheme, fold, horizon, snapshot)
├── split_folds.parquet   frozen fold manifest (boundaries + role counts)
├── rank_audit.parquet    per rank column × kind: tie mass, quarter-key share (§3)
└── manifest.json         provenance: version, params, counts, column layout, rank policy
```

Pin the version. Never edit files inside it; if something is wrong or
missing, file it against `sharadar-dataset` and consume the next version.
`manifest.json` records everything needed to cite the build: row counts,
per-horizon effective sample sizes, parameters, and the full column layout.

## 2. The row grain

One row per **(permaticker, snapshot_date, snapshot_kind)** — three
snapshots per stock-quarter, taken on the dates the adjusted close touched
the quarter's `low`, `median`, and `high` (decision 0001).

- `permaticker` is the entity key. `ticker` is display metadata — tickers
  get reused across companies; never join or group on it.
- The three kinds are an entry-price gradient for **training**. Evaluation
  uses the median kind only (see §4) — a real portfolio enters at one price.

## 3. Columns

`manifest.json["columns"]` lists every column by group, in order:

| group | contents |
|---|---|
| `key_meta` | `permaticker`, `ticker`, `quarter`, `quarter_trading_days`, `snapshot_kind`, `snapshot_date`, `entry_closeadj` |
| `features` | every registry feature ([features.md](features.md)), family build order, composites in place |
| `ranks` | `{name}_rank` — percent rank within (calendar quarter, snapshot_kind), under the feature's rank policy (below) |
| `sector_ranks` | `{name}_secrank` — same, additionally partitioned by sector (allowlist only) |
| `labels` | per horizon H ∈ {1y, 2y, 3y, 5y}: `fwd_{H}_*` continuous outcomes, `label_{H}_*` binaries, `delisted_in_window_{H}` |
| `sample_weights` | `sample_weight_{H}y` uniqueness weights |

Use the manifest to select feature columns — don't pattern-match names:

```python
import json

DATASET = "data/datasets/dataset_v1.2"
cols = json.load(open(f"{DATASET}/manifest.json"))["columns"]
feature_cols = cols["features"] + cols["ranks"] + cols["sector_ranks"]
```

### Ranks: what a rank value means (v1.2, decision 0016)

A within-quarter percent rank of a *tied* group equals the share of the
quarter's cross-section below it — a constant that identifies the quarter.
On `dataset_v1.0` a tree model dated rows to the year with 0.95 accuracy
from the rank columns alone, 0.92 from four of them
(`research/rank-quarter-keys.md`). From v1.2 every feature carries a rank
policy, published in `manifest.json["rank_policy"]`:

- **Integer scores, counts and shares have no rank column** —
  `piotroski_f`, `mohanram_g7`, `fundamentals_age_days`,
  `fund_history_quarters`, the `div_*_10y` counters, `*_up_frac_*`,
  `ocf_positive_frac_*`. Use the raw column; it is already comparable
  across quarters. Do not rank them yourself within quarter — you would
  rebuild the key.
- **Zero-pinned ranks** (`{"rank": "pinned_zero", "zero_rank": z}`): exact
  zeros rank *z* in every quarter; non-zero values are percent-ranked
  within their sign class, negatives onto [0, z] and positives onto
  [z, 1]. So `dividend_yield_rank = 0` means "no dividend, or the
  smallest yield among payers", `dividend_yield_rank = 0.8` means "top
  fifth of *payers*"; `net_payout_yield_rank` is 0.5 at zero, below for
  net issuers, above for net payers; `dist_52w_high_rank = 1` means "at
  its 52-week high".
- **Full ranks** are the decision-0008 percent rank, unchanged.

`rank_audit.parquet` (summarised in `manifest.json["rank_audit"]`) reports
per rank column and kind the tie mass and the largest quarter-specific tied
group (`max_key_share`); a shipped version has an empty
`rank_audit.flagged` unless upstream published under `--allow-rank-keys`,
in which case exclude the listed columns from rank-fed models.

**v1.1 → v1.2 is a breaking boundary**: 24 rank columns disappear and ten
change semantics. Do not compare rank-fed results across it; bump
`min_dataset_version` on rank-fed configs. Raw columns and flags are
unchanged.

Every feature is point-in-time: it reflects only information publicly
available on or before `snapshot_date`. Do not "enrich" rows by joining
anything computed from raw Sharadar tables unless you replicate that
discipline — the easy joins (e.g. on `calendardate`) leak the future.

### Labels

Targets to choose from, per horizon (full definitions: [labels.md](labels.md)):

- **Binary**: `label_{H}_cagr_ge_{0,5,8,10,15,20}` (inclusive thresholds),
  `label_{H}_beat_spy`, and `label_{H}_excess_ge_{5,10}` (beat SPY by ≥ 5 /
  ≥ 10 pts CAGR — base rates are less era-dependent than the absolute
  rungs; the 15/20/excess rungs first appear in datasets built after v1.1).
- **Continuous**: `fwd_{H}_cagr` (terminal-month-average convention),
  `fwd_{H}_cagr_p2p`, `fwd_{H}_excess_cagr`, min/max variants. Custom
  thresholds can be re-derived from these without touching prices.
- `delisted_in_window_{H}`: `'false'`, or the delist reason. A non-`'false'`
  value is a **labeled row like any other** (final price carried at 0% —
  decision 0002). Filtering these rows out reintroduces survivorship bias
  and is the single worst thing you can do with this dataset.
- **NULL in every label column of a horizon = unobservable** (the window
  extends past the data). Such rows are excluded from test sets by the
  split tags already; for training, they simply have no target.

## 4. Splits: the honesty contract

`splits.parquet` has one row per (scheme, fold, horizon_years, snapshot)
that participates in a fold, with a `role`. **Absence means out of fold.**
Tags never filter: `dataset.parquet` keeps every row regardless.

Rules — these are the invariants downstream code must enforce:

1. **Train only on `role = 'train'`** for your (scheme, fold, horizon).
   `purged` and `embargoed` rows are the rows a naive temporal split would
   have leaked; they are tagged so the cost is measurable, not so you can
   use them.
2. **Model selection** (features, hyperparameters, thresholds) happens on
   the expanding **`walkforward`** folds (`fold` = test year).
3. **`holdout` is sealed**: one fold covering the final years. Evaluate on
   it once per project phase, after all selection is frozen. Results seen
   there must never flow back into selection — a consumed holdout cannot be
   re-sealed.
4. **Test rows are median-kind only** and label-observable, already
   enforced by the tags. Never evaluate on `low`/`high` rows.
5. **`entity_holdout` and `random_kfold` are diagnostic-only** (decision
   0010): they exist for the registered leakage-gap experiment (§7) and
   must never be used for model selection or reported performance —
   `random_kfold` is deliberately leaky.
6. **Cite `split_folds.parquet` in every report.** The manifest is the
   frozen fold definition; PBO / trial-count accounting depends on folds
   not being quietly redefined.
7. The model that ships is refit on all currently-eligible data — the
   purge/embargo/holdout discipline constrains *measurement*, not what the
   deployed model may learn from.

Selecting a training set:

```python
import duckdb

train = duckdb.sql(f"""
    SELECT d.*
    FROM '{DATASET}/dataset.parquet' d
    JOIN '{DATASET}/splits.parquet' s
      USING (permaticker, snapshot_date, snapshot_kind)
    WHERE s.scheme = 'walkforward'
      AND s.horizon_years = 3
      AND s.fold = 2018
      AND s.role = 'train'
""").df()
```

Swap `role = 'test'` for the same (scheme, fold, horizon) to get the
matching evaluation rows.

## 5. Sample weights

Snapshot label windows overlap heavily within a stock (quarterly snapshots,
multi-year horizons), so rows are far from independent — at 5y the serial
label correlation at lag 4 quarters is ~0.82 (splits diagnostics report).
`sample_weight_{H}y` (decision 0012) is the exact average-uniqueness
correction: in (0, 1], NULL exactly where the horizon's label is
unobservable, unnormalized.

Pass it as a native sample weight for the horizon you are predicting:

```python
import lightgbm as lgb

X = train[feature_cols]                    # NaNs are meaningful — see §6
y = train["label_3y_beat_spy"]
w = train["sample_weight_3y"]
model = lgb.LGBMClassifier().fit(X, y, sample_weight=w)
```

When reporting dataset sizes, report the **effective** sample size
Σ `sample_weight_{H}y` (per-horizon sums are in
`manifest.json["effective_rows"]`), not the raw row count.

## 6. Missing values

NULL means *not knowable or not defined at that snapshot* — never
zero-filled, never imputed upstream. Sources include: no filing yet
(`has_filing_*` flags), burn-in for lagged features (a P36 feature needs
36 months of history — decision 0004), REIT-style unclassified balance
sheets (`workingcapital` inputs ~84% NULL for REITs by construction),
rank guard (cross-sections with < 20 non-NULL values rank as NULL).

Prefer models with native missing-value handling (gradient-boosted trees).
If you impute, do it inside the training fold only, and say so in the
report — imputation fitted on all rows is itself leakage.

## 7. Registered experiments

These were deliberately deferred to `value-ml-models` and are part of its
task list:

- **Leakage-gap experiment** (decision 0010; workspace
  `research/splits.md`): train identical models under `random_kfold`,
  `entity_holdout`, and purged `walkforward` tags; the score gaps measure
  overlap leakage and firm-identity memorization. Diagnostic only.
- **Era-identifiability probe** (same workspace): predict the calendar year
  from features alone (raw vs. rank sets); beating chance settles "you
  can't tell what date a sample comes from" negatively. Run on v1.0, it
  found the rank-column quarter key that decision 0016 removes; it is now
  the **acceptance test for every new dataset version**: a `ranks`-only
  probe under `entity_holdout` should land near the raw-feature level, not
  0.9. Run it on receipt (`scripts/run_diagnostic.py era-probe`) before
  the leakage-gap experiment, whose rank-model arm is only meaningful once
  it passes.
- **Restated-variant ablation** (decision 0009): as-reported features are
  canonical; a restated-dimension variant may be trained as a diagnostic
  under the same purged splits, never shipped.

## 8. Caveats worth knowing (from the QA reports)

From the committed reports under `research/reports/`:

- **Early years are thin.** Pre-2000 coverage is burn-in territory: 1997–99
  have depressed filing coverage and the P36/history-gated features are
  NULL until enough history accumulates. Fold calendars already reflect
  this (`--min-train-years`), but be careful with any analysis that treats
  1997–1999 cross-sections as representative. The V3 survivorship-depth
  verification (earliest trustworthy year) is still open upstream.
- **1y outcomes are heavy-tailed** (all-kinds 1y label variance is
  dominated by a few extreme returns). Winsorize or use the binary labels
  when a squared-error objective would chase outliers.
- **Staleness is a feature, not a filter** (decision 0006):
  `fundamentals_age_days` (raw days, unranked since v1.2) and the
  `has_filing_*`/freshness flags are columns; stale rows have distinctly
  worse outcomes (staleness report), so let the model see the flags rather
  than dropping rows.
- **Microcaps dominate the universe** and may not be investable. There is
  deliberately no liquidity floor; use `log_marketcap`,
  `dollar_volume_3m`, `amihud_12m` to build one downstream if the use case
  needs it — and report it as part of the model definition.

## 9. Scoring the latest cross-section (inference dataset)

To run a trained model on *today's* (or the latest ingested) stocks,
consume a `data/datasets/inference_{as_of}/` directory (`make inference`
upstream; ADR 0014, [dataset.md](dataset.md) §inference) instead of
hand-building features:

- `dataset.parquet` carries the same `features`/`ranks`/`sector_ranks`
  columns as training, computed by the same code — select them from its
  `manifest.json["columns"]` exactly as in §3. There are no labels, splits,
  or sample weights, and `key_meta` has no `quarter_trading_days`.
- One row per currently-tradable stock, `snapshot_kind = 'inference'`,
  ranks pooled over the whole cross-section (one partition). Same-day
  filings are included: the earliest actionable entry is the trading day
  *after* `as_of`, so nothing in the row postdates what a live run would
  know (and `fundamentals_age_days` can be 0).
- Check `manifest.json["as_of"]` and `rows_with_stale_price` before
  trusting a run — a stale ingest silently means a stale cross-section.
- Never train or evaluate on an inference directory: it is survivor-only
  by construction. Model quality claims come from `dataset_vX.Y` splits.
