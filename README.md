# sharadar-dataset

Point-in-time, survivorship-bias-free dataset construction for fundamentals-based
stock classification models.

This repo is responsible for everything **up to and including** the production of a
model-agnostic training dataset. Model training, evaluation, and portfolio
construction live in a separate repo (`value-ml-models`) that consumes the output
of this one.

---

## 1. Objective

Produce a wide, versioned dataset of the form:

```
(permaticker, snapshot_date, feature_1 ... feature_N, label_1 ... label_M, split_tag)
```

where:

- Every **feature** reflects only information publicly available on or before
  `snapshot_date` (strict point-in-time discipline).
- Every **label** is a forward-looking outcome computed from total returns
  (split- and dividend-adjusted), defined for *every* snapshot in the universe —
  including stocks that delist during the forward window.
- The dataset supports multiple downstream models (decision trees first,
  gradient-boosted trees later) without modification.

## 2. Data source

All data comes from **Sharadar via Nasdaq Data Link**:

| Table | Contents | Role |
|---|---|---|
| `SF1` | Fundamentals (quarterly/annual/TTM, multiple dimensions) | Features |
| `SEP` | Equity prices, daily, incl. `closeadj` | Labels, price-based features |
| `SFP` | Fund prices (SPY etc.) | Benchmark labels |
| `TICKERS` | Metadata: permaticker, category, sector/industry, isdelisted, SIC, FF industry | Universe definition, identifier mapping |
| `ACTIONS` / `EVENTS` | Corporate actions, delisting events | Delisting-return conventions |
| `DAILY` | Daily-computed metrics (marketcap, ev, pe, pb, ps) | Convenience features |

### Point-in-time rules (critical)

- Use **as-reported dimensions** (`ARQ` / `ART`) from SF1. Never use `MRQ`/`MRT`/`MRY`
  for features — they incorporate restatements (lookahead).
- The event date for a fundamentals row is **`datekey`** (the SEC filing date),
  *not* `reportperiod` (fiscal period end) and *not* `calendardate` (normalized
  quarter end). A fundamentals row becomes usable **the first trading day strictly
  after `datekey`**. [NOTE: I may have found some discrepancies in the data to contradict this; need to confirm]
- `calendardate` may be used only for cross-sectional alignment/grouping, never as
  an availability date.
- Prices for labels come from `SEP.closeadj` (total-return adjusted).
  Benchmark from `SFP` (SPY adjusted close) unless we later construct a custom
  universe benchmark.

### Identifier discipline

- The canonical entity key is **`permaticker`** (from `TICKERS`). `ticker` is a
  join key only.
- Build and persist a `ticker ↔ permaticker` mapping table (with date validity if
  needed) as the first artifact of the pipeline. All SF1/SEP rows must be resolved
  to a permaticker before any other processing.

## 3. Universe

- `TICKERS.category` in {`Domestic Common Stock`, `Domestic Common Stock Primary Class`}.
- **Include** delisted stocks (`isdelisted = Y`). This is the whole point of using Sharadar for avoiding survivorship bias.
- **Include** REITs.
- **Exclude** banks and insurance companies in v1 (identify via Sharadar
  sector/industry and/or SIC codes 6000–6499). Rationale: many core features
  (Altman-Z components, EV ratios, working-capital metrics) are undefined for
  financials; a sector column does not fix null/garbage features. Revisit as a
  dedicated model later.
- Exclude ADRs, ETFs, funds, warrants, preferreds (falls out of the category filter,
  but verify).
- Minimum-data filters (TBD, see Open Questions): e.g., require a price on the
  snapshot date and at least one ARQ filing in the trailing 12 months.

## 4. Snapshots

- Snapshot frequency: **quarterly** (calendar quarter ends) as the default.
  A snapshot row for (permaticker, date) uses the most recent ARQ/ART row whose
  `datekey` < snapshot date, subject to a staleness cutoff (e.g., discard if the
  latest filing is > 12 months old).
- Snapshots are generated for every in-universe stock alive on the snapshot date,
  regardless of what happens afterward.
- **Snapshot dates (decided, see `docs/decisions/0001`):** each (stock, quarter)
  emits **three snapshots**, taken on the dates the adjusted close touched its
  intra-quarter **low**, **median**, and **high** (median = discrete quantile, so
  always an observed price; earliest date on ties). Same fundamentals, three
  entry valuations, correspondingly different labels — this teaches the
  margin-of-safety gradient ("this balance sheet at 0.8× book met the criteria;
  at 1.3× it didn't") directly. Rows are flagged
  (`snapshot_kind ∈ {low, median, high}`), receive uniqueness weights like any
  other overlapping rows, and the low/high rows are **never used in
  validation/test** — a real portfolio enters at one price, and evaluating on
  multiple entries would double-count and flatter precision estimates
  (enforced by the splits module).

## 5. Features

Categories (initial set; final list maintained in `docs/features.md`):

1. **Valuation:** P/B, P/S, P/E, EV/EBITDA, EV/EBIT, earnings yield, FCF yield. Piotroski F-score, Magic formula, Conservative formula, etc.
2. **Solvency / distress (Altman-Z-style, Ohlson O-score, etc):** working capital / assets,
   retained earnings / assets, EBIT / assets, market equity / total liabilities,
   sales / assets; debt/equity, interest coverage, current ratio.
3. **Earnings quality (M-score-style):** DSRI, GMI, AQI, SGI, DEPI, SGAI, LVGI, TATA
   (computed from consecutive ARQ rows of the same permaticker).
4. **Profitability & growth:** ROE, ROA, ROIC, gross margin, margin trends,
   revenue/EPS growth (YoY from ARQ history).
5. **Technical (small set):** trailing 6m/12m total return, 12m volatility,
   distance from 52-week high, market cap (log).
6. **Market-regime (candidate, see Open Questions):** snapshot-date market
   conditions — e.g., S&P 500 P/S or P/E, trailing market return/volatility.
   Consistent with the project thesis (deep value *relative to the prevailing
   regime*), but note the hazard: under temporal splits these are near
   date-identifiers, letting trees memorize eras in-sample. Include only with a
   with/without ablation in walk-forward validation; value must be demonstrated
   across multiple regimes.
7. **Classification columns:** Sharadar sector, industry, Fama-French industry.

**Feature representation:** every numeric feature is stored twice —
raw value AND **cross-sectional rank (percentile) within snapshot date**
(and optionally within sector). Rank features are the primary model inputs;
raw values are retained for analysis. Rationale: raw ratio thresholds are not
stationary across valuation regimes; ranks are stationary by construction and
neutralize outliers/units.

Missing values are preserved as nulls (trees handle them; do not impute silently).
Track per-feature null rates by sector as a data-quality report.

## 6. Labels

All labels are computed from total returns using `closeadj`, with the
**terminal-month-average convention**: the end price for a horizon-H label is the
mean adjusted close over the 21 trading days centered on (or ending at)
`snapshot_date + H`. This damps endpoint noise. Point-to-point labels are also
stored for comparison.

Label matrix (each cell is a binary label; also store the underlying continuous
CAGR so thresholds can be re-derived without recomputation):

| Horizon | Absolute thresholds | Relative |
|---|---|---|
| 1y | ≥ 0%, ≥ 5%, ≥ 8%, ≥ 10% CAGR | beat SPY total return |
| 2y | same | same |
| 3y | same | same |
| 5y | same | same |

Additional stored columns per (snapshot, horizon):

- `fwd_{H}_cagr` — continuous, terminal-month-average convention
- `fwd_{H}_cagr_p2p` — point-to-point: CAGR from the single adjusted close on the
  snapshot date to the single adjusted close exactly H later, no smoothing. Kept as
  a control: the label-flip rate between this and the smoothed convention, per
  (horizon, threshold), measures how much of the "ground truth" is endpoint noise.
  A high flip rate near a threshold also bounds how small a model-performance
  difference can be before it's indistinguishable from labeling noise.
- `fwd_{H}_min_cagr` / `fwd_{H}_max_cagr` — min/max price over the terminal month
  (pessimistic/optimistic band; cheap to compute, defer judgment on usefulness)
- `fwd_{H}_closeadj_{avg,p2p,min,max}` — the raw terminal `closeadj` values behind
  the four CAGRs above, so any CAGR can be re-derived (or the convention changed)
  straight from prices
- `fwd_{H}_spy_cagr` — the benchmark's CAGR over the same window, same convention
- `fwd_{H}_excess_cagr` — vs. SPY total return (`fwd_{H}_cagr − fwd_{H}_spy_cagr`)
- `delisted_in_window_{H}` (varchar) — `'false'` if the stock still traded at the
  horizon end, otherwise the delist reason itself (no separate reason column);
  NULL when the horizon is not yet observable.

**Delisting convention (decided, see `docs/decisions/0002`):** if a stock
delists during the forward window, the label MUST still be computed. For all
delist reasons alike, the position is carried at the **final adjusted trading
value** (last `closeadj`), compounding at **0%** from the delisting to the
horizon end. No −100% override for bankruptcies — the final print already
reflects the market's recovery estimate (V4 audits this).

Dropping delisted-in-window rows is forbidden: it reintroduces survivorship bias
in the labels even though the underlying data is survivorship-free.

**Triple-barrier labels** (de Prado, *AFML* ch. 3) are path-dependent labels:
place an upper barrier (profit target), a lower barrier (stop-loss), and a
vertical barrier (the time horizon); the label is decided by whichever barrier the
daily price path touches first. They encode "reached the outcome without a
catastrophic drawdown," which endpoint labels cannot express. They are explicitly
**out of scope for v1** (they add barrier-width hyperparameters, ideally
volatility-scaled, and require full path scans), but the label module must be
built in two stages so they can be added later without rewrites:

1. **Path extraction:** for each (permaticker, snapshot_date, horizon), produce the
   forward daily adjusted-price path, with all delisting handling applied here and
   only here.
2. **Label functions:** endpoint CAGR, terminal-month average, min/max, and (later)
   triple-barrier are each pure functions over that path object.

## 7. Train / validation / test splits

This is the highest-risk part of the project. Get it wrong and every downstream
metric is fiction. The reasoning is spelled out here so the rules aren't cargo
cult.

### 7.1 Why rows are not independent

**Serial overlap (same stock, nearby snapshots).** With quarterly snapshots and a
3y horizon, the 2015-03-31 snapshot's label window (2015-03→2018-03) shares 33 of
36 months with the 2015-06-30 snapshot's window. The rows are not *duplicates* —
price-based features move intra-quarter, and because entry price enters the return
calculation, labels near a threshold can genuinely differ between snapshots. But
they are *highly correlated*: the dominant variance of a 3y return is the shared
forward path, not the entry-price difference. Correlated features paired with
correlated labels is the memorization channel — a model can recognize the
"AAPL-2015 neighborhood" from any of the sibling rows and recall the mostly-shared
outcome. Leakage requires correlation, not identity.

**Cross-sectional overlap (different stocks, same date).** All stocks snapshotted
on the same date have labels driven substantially by the same market path. A good
2016–2018 shifts *every* 2015 snapshot toward positive labels together. Rows from
different companies are not independent when their windows coincide.

**Consequence.** Under a random split, nearly every test row has a highly
correlated sibling in train (same stock ± one quarter, or a same-date peer).
Approximate memorization scores brilliantly; validation metrics become
meaningless. This also means the **effective sample size is set by the time
dimension, not the row count**: with ~28 years of data (1998→present) there are
only ~9 non-overlapping 3y windows and ~5 non-overlapping 5y windows. This is a
small dataset wearing a big dataset's row count. Cross-sectional dependence also
caps evaluation confidence for concentrated portfolios: if the top-K picks in a
cohort share a factor tilt and a forward window, precision@K on them carries the
statistical weight of far fewer than K independent bets.

### 7.2 Mechanics

**Temporal split.** Test periods are strictly later than training data.
Necessary, not sufficient.

**Purging.** Remove from training any snapshot whose label window overlaps the
test period — such a row "knows" test-period outcomes through its label.
Eligibility rule: `snapshot_date + horizon < test_start`. Purging burns `horizon`
worth of the most recent (most relevant) training data, and burns 5× more for the
5y model than the 1y model. Therefore **eligibility is tagged per horizon**; a
single shared cutoff either leaks (long horizons) or wastes data (short ones).

**Embargo.** After purging, an additional buffer (default 1 month, parameterized)
between the last training influence and test start. Purging handles leakage
through the label arithmetic; embargo handles residual leakage through serial
correlation in features and returns that doesn't end cleanly at a window
boundary. Cheap insurance; de Prado's guidance is a small fraction of the sample
period suffices.

Full training-eligibility condition per (row, horizon, test period):

```
snapshot_date + horizon + embargo < test_start
```

**Within-train overlap vs. cross-boundary overlap.** The rules above police the
train/test *boundary* only. Overlapping rows **within the training set are kept**
— purging is a boundary-local cost, not a global one, and across walk-forward
folds nearly every row trains in some fold. Density within training is instead
handled by **uniqueness weighting** (de Prado, *AFML* ch. 4): each row carries a
per-horizon `sample_weight` column ≈ the average uniqueness of its label (a row
whose window overlaps 11 same-stock siblings weighs ~1/12 of an isolated row).
Downstream models pass it as a native sample weight. This keeps all data while
preventing dense periods and long horizons from being overrepresented, and the
summed weights give an honest effective-sample-size estimate per era as a
byproduct (published in the QA report).

### 7.3 Split schemes (tagged in the dataset, consumed downstream)

1. **`holdout`** — final sealed test period: the most recent usable years, per
   horizon. Evaluated once per project phase by downstream code; never used for
   model selection. Non-negotiable.
2. **`walkforward`** — expanding-window folds for model selection: train on all
   eligible data up to T (purged + embargoed), validate on the period after T,
   advance T, aggregate. Directly simulates deployment; the primary honest
   performance estimate.
3. **`cpcv`** *(reserved, v2)* — Combinatorial Purged Cross-Validation (de Prado
   ch. 12): partition time into blocks, form many purged train/test combinations,
   yielding many backtest paths instead of one. Its value is variance estimation —
   one walk-forward path is a single draw of history. The tagging schema
   `(scheme, fold, horizon) → {train | test | purged | embargoed}` must not
   preclude it, but no v1 implementation.

### 7.4 What splitting by ticker does NOT solve

Entity-disjoint splits (AAPL in train, MSFT in test) do not fix leakage, because
the dependence is temporal: MSFT-2015 in test shares its market path with
AAPL-2015 in train. Entity splits are at most a supplementary diagnostic for
firm-identity memorization, never a substitute for temporal purging. The same
permaticker in both train and test is acceptable *provided* windows are purged.

### 7.5 Consequences accepted up front

Per-horizon purging + a sealed holdout means the 5y model trains on meaningfully
older data and is evaluated on very few independent windows. Its results are
inherently low-confidence regardless of engineering quality. Model-selection
confidence is strongest at 1y and degrades with horizon. Document this in every
report rather than pooling it away.

### 7.6 Required reading before implementing `src/splits/`

- López de Prado, *Advances in Financial Machine Learning*: ch. 7 (purged k-fold
  and embargo — exact overlap conditions), ch. 11–12 (backtest dangers, CPCV).
- Bailey, Borwein, López de Prado, Zhu, "The Probability of Backtest
  Overfitting" — why the count of configurations tried must be recorded
  (enforced as an invariant in `value-ml-models`).

Notes from the reading go in `docs/decisions/` before the module is written.

## 8. Architecture

Deliberately simple. Do not build a database service.

```
sharadar-dataset/
├── data/
│   ├── raw/          # bulk parquet exports from Data Link, immutable
│   ├── interim/      # permaticker-resolved, cleaned tables
│   └── datasets/     # versioned final datasets: dataset_vX.Y.parquet
├── src/
│   ├── ingest/       # bulk download + refresh from Nasdaq Data Link
│   ├── identity/     # ticker↔permaticker resolution, universe construction
│   ├── snapshots/    # snapshot generation, as-of joins
│   ├── features/     # feature computation (one module per feature family)
│   ├── labels/       # forward-return + delisting-aware label computation
│   ├── splits/       # purged/embargoed split tagging
│   └── qa/           # data-quality reports, survivorship audits
├── docs/
│   ├── features.md   # canonical feature registry
│   ├── labels.md     # canonical label definitions & conventions
│   └── decisions/    # ADR-style records of resolved Open Questions
└── tests/
```

- Storage: **parquet** everywhere; query with **DuckDB** (as-of joins between
  `datekey` and daily prices are its bread and butter). Full SF1 is a few GB,
  SEP ~10–20 GB — laptop-scale.
- The dataset is fully reproducible from `data/raw/` by a single command
  (`make dataset` or equivalent). No hand-edited intermediates.
- Dataset versions are immutable and named; downstream repo pins a version.

## 9. Verification tasks (do these before trusting anything)

These are the empirical checks behind the design assumptions. Each produces a
short writeup in `docs/decisions/`.

- [ ] **V1 — datekey semantics.** For ~10 known filings, confirm ARQ `datekey`
      matches the actual SEC filing date (check EDGAR) and that ARQ values match
      the original (pre-restatement) filing. Confirm `calendardate` vs.
      `reportperiod` behavior for off-cycle fiscal years.
- [ ] **V2 — ticker reuse.** Find tickers in `TICKERS` mapping to multiple
      permatickers. Determine how SF1/SEP rows disambiguate (or don't). Define the
      resolution rule and test it.
- [ ] **V3 — survivorship depth.** Count in-universe stocks per year 1998→present,
      split by alive/delisted-later. Compare delisting counts around 2000–2002 and
      2008–2009 against published delisting statistics. Decide the earliest year
      the data is trustworthy (expect ~1998 hard floor; possibly later).
- [ ] **V4 — delisting returns.** Sample bankruptcies; inspect final SEP prices vs.
      known recoveries. Confirm ACTIONS/EVENTS give usable delist reasons. Lock the
      delisting-return convention.
- [ ] **V5 — financials identification.** Verify sector/SIC filters cleanly
      separate banks/insurers; check feature null rates by sector to confirm the
      exclusion decision (and confirm REIT features are usable).
- [ ] **V6 — benchmark.** Confirm SFP SPY adjusted close is total-return.

## 10. Open questions (decide, then record in docs/decisions/)

- [x] Acquisition delisting convention: **0%** from the final adjusted value,
      all delist reasons alike → `docs/decisions/0002`.
- [ ] Staleness cutoff for fundamentals at snapshot time (6 vs. 12 months).
- [ ] Minimum liquidity/market-cap floor? (Microcaps dominate a total-market
      universe and may not be investable; consider a `min_marketcap` flag column
      rather than exclusion, so downstream can choose.)
- [ ] Rank features within-date only, or within-date-and-sector?
- [ ] Snapshot frequency: quarterly vs. monthly (monthly triples data volume and
      overlap; quarterly is the default until shown insufficient).
- [ ] Min/max terminal-price labels: keep, or drop after sensitivity analysis?
- [x] Price-sensitivity augmentation (§4): adopted in v1 as the three
      low/median/high touch-date snapshots → `docs/decisions/0001`.
- [ ] Market-regime features (§5.6): include in v1 feature set (with ablation
      requirement) or defer?
- [ ] Uniqueness-weight definition details: exact overlap counting for the
      `sample_weight` column (de Prado ch. 4), and whether augmented rows share a
      weight pool with their base row.

## 11. Milestones

1. **M1 — Ingestion & identity.** Bulk download raw tables; permaticker mapping;
   universe table. Exit: universe counts per year plotted; V2, V3 done.
2. **M2 — Point-in-time verified.** V1 done; as-of join machinery working and
   tested against hand-checked examples.
3. **M3 — Labels.** Forward returns with delisting handling; V4, V6 done.
4. **M4 — Features.** Feature families implemented with per-family tests and
   null-rate reports; V5 done.
5. **M5 — Splits & assembly.** Purged/embargoed split tagging; `dataset_v1.0`
   produced end-to-end by one command; QA report published.

## 12. Non-goals (this repo)

- Model training, hyperparameter search, calibration → `value-ml-models`.
- Portfolio construction / backtesting → `value-ml-models`.
- Real-time / live data serving.
- A general-purpose data platform. This is a batch pipeline with a single output.

## 13. Getting started

Dependencies are managed with [uv](https://docs.astral.sh/uv/):

```bash
uv sync            # create .venv and install dependencies
make test          # run the test suite
```

### Ingesting the raw tables (M1)

Set your Nasdaq Data Link API key, then bulk-download everything:

```bash
export NASDAQ_DATA_LINK_API_KEY=...
make ingest                          # all seven tables
make ingest TABLES="TICKERS SEP"     # or a subset
```

or call the CLI directly for the full option set (`--force`, `--keep-zip`,
`--no-sort`, `--memory-limit`, ...):

```bash
uv run sharadar-ingest --help
```

For each table this requests a bulk export from Nasdaq Data Link, polls until
it is fresh, downloads the zipped CSV to `data/raw/.staging/`, and converts it
with DuckDB to `data/raw/<TABLE>.parquet` (ZSTD-compressed, explicitly typed,
sorted for downstream joins) plus a `data/raw/<TABLE>.meta.json` provenance
sidecar (source snapshot time, row count, zip sha256). Existing tables are
skipped unless `--force` is given; interrupt and re-run to resume.

Note on disk: SEP's CSV is temporarily extracted next to the output before
conversion, so budget roughly zip + CSV + parquet (~40–50 GB free) for the
initial full run.

Query the result with DuckDB:

```python
import duckdb
duckdb.sql("SELECT count(*) FROM 'data/raw/TICKERS.parquet'")
```

### Identity artifacts (M1)

Once `TICKERS` is ingested:

```bash
make identity        # or: uv run sharadar-identity --help
```

builds, under `data/interim/`:

- `ticker_permaticker.parquet` — the canonical ticker↔permaticker mapping
  (§2), one row per permaticker with its price-coverage window; tickers used
  by more than one permaticker are flagged.
- `ticker_reuse.parquet` — only the reused-ticker rows: the raw material for
  verification task V2.
- `universe.parquet` — one row per permaticker with the §3 rules expressed as
  flag columns (`is_common_stock`, `is_financial_sic`, `is_financial_sector`,
  `siccode_missing`) plus the final `in_universe` verdict, so exclusions stay
  auditable (V3, V5) rather than silently dropped.
- `universe_counts_by_year.parquet` / `.csv` and
  `reports/universe_counts_by_year.png` — in-universe securities per year,
  split still-listed vs. later-delisted (the M1 exit plot, input to V3).

### Snapshots & labels (M3)

Once `SEP`, `SFP`, and `ACTIONS` are ingested and the identity artifacts exist:

```bash
make labels          # or: uv run sharadar-labels --help
```

builds, under `data/interim/`:

- `snapshots.parquet` — three snapshots per (permaticker, quarter), taken on
  the intra-quarter low/median/high touch dates (§4, `docs/decisions/0001`).
- `labels.parquet` — one row per snapshot: the full §6 label matrix per
  horizon (terminal-month-average and point-to-point CAGR, min/max band,
  SPY excess, binary thresholds, `delisted_in_window_{H}`), with the
  delisting convention of `docs/decisions/0002` applied.

Column-level definitions live in `docs/labels.md`.
