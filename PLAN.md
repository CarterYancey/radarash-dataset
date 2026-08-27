# Design plan — dataset construction

The conceptual and theoretical design of this pipeline: what the dataset is,
why each rule exists, and the reasoning behind the parts that are easy to get
subtly wrong. Practical matters live elsewhere: [README.md](README.md) for
architecture and how to run, [TODO.md](TODO.md) for the task register,
[docs/decisions/](docs/decisions/) for resolved design questions,
[docs/research/](docs/research/) for research workspaces (feature-set
research ahead of M4 lives there).

Section numbers §1–§7 are stable and cited from code docstrings — do not
renumber.

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

All data comes from **Sharadar via Nasdaq Data Link** (table roles in
README.md §Data source).

### Point-in-time rules (critical)

- Use **as-reported dimensions** (`ARQ` / `ART`) from SF1. Never use `MRQ`/`MRT`/`MRY`
  for features — they incorporate restatements (lookahead; the
  deployment-consistency and restatement-timing rationale is decision 0009).
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
- Minimum-data filters (TBD, see TODO.md): e.g., require a price on the
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

Categories (initial set; research workspace in `docs/research/features.md`,
final registry in `docs/features.md`):

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
6. **Market-regime (candidate, see TODO.md):** snapshot-date market
   conditions — e.g., S&P 500 P/S or P/E, trailing market return/volatility.
   Consistent with the project thesis (deep value *relative to the prevailing
   regime*), but note the hazard: under temporal splits these are near
   date-identifiers, letting trees memorize eras in-sample. Include only with a
   with/without ablation in walk-forward validation; value must be demonstrated
   across multiple regimes.
7. **Classification columns:** Sharadar sector, industry, Fama-French industry.
   TICKERS metadata is current-state, not historical — reclassified firms get
   today's label retroactively; accepted v1 caveat with `siccode` as the
   era-stable fallback (edges spelled out in docs/features.md §Classification).

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
| 1y | ≥ 0%, ≥ 5%, ≥ 8%, ≥ 10%, ≥ 15%, ≥ 20% CAGR | beat SPY; beat SPY by ≥ 5 / ≥ 10 pts CAGR |
| 2y | same | same |
| 3y | same | same |
| 5y | same | same |

The 15/20 rungs target the right tail (compounders/mega-performers); the
excess-CAGR rungs express the same "big win" idea relative to the prevailing
market, so their base rates swing less across valuation eras than the
absolute rungs do.

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

The implemented column-level definitions live in `docs/labels.md`.

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

**Walk-forward fold shape ("boundary-local" made concrete).** Each fold is a
purged, embargoed analogue of one split in scikit-learn's `TimeSeriesSplit`
(a k-fold variant that only ever tests on data later than what it trained
on): the training set is a single **contiguous prefix** of history, purging
strips a `horizon + embargo`-wide slice immediately before the test period,
and the interior of that prefix is untouched. Example: 3y horizon, 1-month
embargo, test year 2015 —

```
1998 ═══════ train (contiguous) ═══════ 2011-12-01 ░ purged/embargoed ░ 2015-01-01 ── test ── 2016-01-01
```

Advance the boundary a year and the next fold trains on 1998→2012-12,
purges 2012-12→2016, tests on 2016 — the training prefix grows, the purge
strip slides with it. Two things follow directly from this shape:

- **A purged row is only purged locally.** The 2013-Q2 snapshot is inside
  the purge strip for the 2015 and 2016 folds (its label window reaches
  into both test periods) but was itself a *test* row in the 2013 fold and
  becomes an ordinary *training* row from the 2017 fold on. Roll the full
  walk-forward sequence and nearly every row trains in most folds and tests
  in exactly one — nothing is discarded from the project, only withheld
  from the specific folds whose test period its label overlaps.
- **No fold ever trains on scattered non-adjacent years.** Every training
  set is one unbroken prefix; only where the prefix ends changes across
  folds. A model is never fit on, say, 1998+2003+2011 in isolation — the
  "sensitive to which two eras happen to get drawn" scenario doesn't occur
  under this scheme (it *would* under a random or blocked-non-contiguous
  split, which is exactly why walk-forward is the default rather than
  those).

Walk-forward folds pick the model configuration (features, hyperparameters);
the shipped/deployed model is then refit on *all* eligible data up to the
present (constrained only by the horizon's own label-observability floor,
not by any test boundary) — the purge/embargo/holdout discipline constrains
what's used for *measurement*, not what the final model may learn from.

Per-horizon accounting differs from a naive `horizon + embargo` reading: a
horizon-H label doesn't exist at all for snapshots newer than
`last_price_date − H` (no H forward years of price yet), so part of the
apparent "loss" at long horizons is unavoidable label-observability, not
purging. The `purge_cost` table in `sharadar-qa splits-diag` (§7.7) reports
the actual eligible/purged row counts per horizon and boundary rather than
this back-of-envelope width, so the 5y cost is priced, not assumed.

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
4. **`entity_holdout`** *(diagnostic-only, decision 0010)* — a fixed set of
   permatickers held out across all time. Never an arbiter: it shares every
   era with the training data, so a temporally-leaky model scores *better*
   on it, not worse (§7.4). Tagged so downstream can measure firm-identity
   memorization and its side of the leakage-gap experiment (§7.7).
5. **`random_kfold`** *(diagnostic-only, decision 0010)* — a uniform random
   row partition, deliberately leaky. Exists purely as the baseline of the
   leakage-gap experiment (§7.7): the score gap between this and purged
   walk-forward *is* the measured size of the overlap leakage.

Schemes 4–5 must never be used for model selection or reported as
performance; the sealed `holdout` (temporal) remains the only arbiter,
because whatever one believes about overlap leakage, deployment is always
on dates later than all training data — "later data" is the one test whose
meaning doesn't depend on the outcome of that debate.

### 7.4 What splitting by ticker does NOT solve

Entity-disjoint splits (AAPL in train, MSFT in test) do not fix leakage, because
the dependence is temporal: MSFT-2015 in test shares its market path with
AAPL-2015 in train. Entity splits are at most a supplementary diagnostic for
firm-identity memorization, never a substitute for temporal purging. The same
permaticker in both train and test is acceptable *provided* windows are purged.
The `entity_holdout` scheme (§7.3) exists to run exactly this diagnostic —
not to replace temporal splits.

### 7.5 Consequences accepted up front

Per-horizon purging + a sealed holdout means the 5y model trains on meaningfully
older data and is evaluated on very few independent windows. Its results are
inherently low-confidence regardless of engineering quality. Model-selection
confidence is strongest at 1y and degrades with horizon. Document this in every
report rather than pooling it away.

### 7.6 Required reading before implementing `src/splits/`

- López de Prado, *Advances in Financial Machine Learning* (Wiley, 2018,
  ISBN 978-1119482086): ch. 4 (sample uniqueness/weighting — why within-train
  overlap is weighted, not purged), ch. 7 (purged k-fold and embargo — exact
  overlap conditions), ch. 11–12 (backtest dangers, CPCV).
- Bailey, Borwein, López de Prado, Zhu, "The Probability of Backtest
  Overfitting" (*Journal of Computational Finance*, 2017; SSRN 2326253) — why
  the count of configurations tried must be recorded (enforced as an
  invariant in `value-ml-models`).
- Bailey, Borwein, López de Prado, Zhu, "Pseudo-Mathematics and Financial
  Charlatanism" (*Notices of the AMS*, May 2014) — the short version of the
  overfitting-by-reuse argument; motivates why the sealed holdout in §7.3
  is spent at most once per project phase.
- scikit-learn `TimeSeriesSplit` docs — a minimal reference implementation of
  the expanding-window fold shape §7.2 elaborates on (its `gap` parameter is
  a crude fixed-width purge; contrast with per-horizon purging here, which a
  single shared gap cannot express — see §7.2's eligibility rule).

Notes from the reading go in `docs/decisions/` before the module is written.

### 7.7 Empirical diagnostics — measure the overlap, don't just assert it

The §7.1 dependence claims and the §7.2 purge cost are empirical quantities,
and they were challenged (is the entry-price gradient enough variation? is
cross-sectional overlap real? what does purging actually cost per horizon?).
Decision 0010 resolves the challenge by making it falsifiable rather than
rhetorical, in two parts:

1. **`sharadar-qa splits-diag`** (data-gated report; workspace
   `docs/research/splits.md`): per-feature intra-quarter variation across
   snapshot kinds and filing-straddle counts; label variance decomposition
   (entry-price-gradient share vs. calendar-quarter fixed effect), same-stock
   serial label correlation by lag, and low/high label flip rates; a
   nearest-neighbor "twin test" for row uniqueness; and a purge-cost table
   pricing `snapshot_date + horizon + embargo < test_start` per boundary.
2. **The leakage-gap experiment** (registered for `value-ml-models`, after
   `dataset_v1.0`): train identical models under `random_kfold`,
   `entity_holdout`, and purged `walkforward`; the score gaps *are* the
   measured leakage. If the gaps come out negligible, the methodology can be
   relaxed with evidence; if large, the §7 rules stand with evidence. Either
   way the sealed temporal holdout stays sealed while the question is open.

## 8. Non-goals (this repo)

- Model training, hyperparameter search, calibration → `value-ml-models`.
- Portfolio construction / backtesting → `value-ml-models`.
- Real-time / live data serving.
- A general-purpose data platform. This is a batch pipeline with a single output.
