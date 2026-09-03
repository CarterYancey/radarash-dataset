# Dataset improvements for training outcomes (research workspace)

Context: downstream models trained on `dataset_v1.x` show better-than-random
precision but not the consistency needed to beat the market over the long
term. This workspace considers what the *dataset* can contribute: the five
levers proposed (more labels, more features, more samples, weight changes,
bug review), each examined against the code as it stands. Findings graduate
to ADRs + canonical docs per the repo practice; nothing here is design
canon until then.

Companion change made with this writeup: the label matrix gained
`label_{H}_cagr_ge_{15,20}` and `label_{H}_excess_ge_{5,10}` (docs/labels.md;
they appear in the next labels build / dataset version).

## 0. Summary and priorities

The label math was re-verified line-by-line and against the fixture tests
and is **correct** (§1.1). The highest-leverage dataset work, in order:

| # | Item | Cost | Why |
|---|---|---|---|
| 1 | Close verifications **V1 (datekey), V6 (SPY total-return), V4 (delisting prints)** | days | The only places left where the dataset could be *silently wrong* in a way that caps live performance (§1.6, §5) |
| 2 | **Valuation-vs-own-history features** ("cheaper than its past") | moderate | Directly targets the stated model weakness; nothing in the current set expresses it (§2.1–2.2) |
| 3 | **Path-dependent labels**: interim-low CAGR + max drawdown per horizon | moderate | The only label information that cannot be derived downstream from stored columns; encodes "got there without a catastrophic ride" (§1.5) |
| 4 | **Ohlson O-score + magic-formula composite + F-score components** | small | Registry gaps vs. PLAN §5; cheap wins (§2.4) |
| 5 | Trend family extensions (share count, margins, netinc sign) | small | Same machinery as ADR 0015 (§2.3) |
| 6 | Liquidity/investability flag column (open TODO question) | small | Precision on paper ≠ capturable returns; make the floor explicit (§6) |
| — | More snapshot kinds / snapshot frequency | — | **Not recommended now** — median already exists; extra rows add little independent information (§3) |
| — | Setting sample weights to 1 | — | **Not a dataset change** — already a downstream experiment; would not increase effective sample size (§4) |

## 1. Labels

### 1.1 Correctness review — verified

Re-derived by hand against `src/labels/{snapshots,paths,compute,delistings}.py`
and `tests/test_labels_cli.py`:

- Entry price = snapshot-date `closeadj`; terminal value = mean/min/max/last
  `closeadj` over the 21 trading days *ending at* the horizon end (last
  trading day ≤ `snapshot_date + H`); CAGR = `(end/entry)^(1/H) − 1` with
  the nominal-year exponent. Matches docs/labels.md exactly.
- Delisting handling: the ASOF forward-fill in `paths.py` carries the final
  print at 0% to the horizon (decision 0002), delistings never dropped, and
  the reason-priority mining works (fixture: `bankruptcyliquidation` beats
  `delisted`). Correct.
- Benchmark uses the identical entry/terminal conventions; absolute labels
  survive benchmark gaps (LEFT joins), only relative labels go NULL there.
- Observability: unobservable horizons are all-NULL, never dropped;
  `labels_wide` LEFT JOIN keeps snapshots whose every horizon is
  unobservable. Splits and weights key off the same marker consistently.
- Purge-bound consistency: the terminal window is trailing, so the nominal
  window `[snapshot_date, snapshot_date + H]` bounds label information from
  above — the split purge condition is exact-or-conservative. Confirmed.

The fixture tests pin all of this to hand-computed numbers (ZIG's three
entry prices, the delisting freeze, threshold inclusivity, terminal-price
re-derivability). **Conclusion: model underperformance is not a label-math
bug.** The remaining label-correctness risk is *data-level*, not code-level
— see §1.6.

### 1.2 Already derivable downstream — no rebuild needed

The dataset deliberately stores the continuous outcomes
(`fwd_{H}_cagr`, `fwd_{H}_cagr_p2p`, `fwd_{H}_excess_cagr`,
`fwd_{H}_min_cagr`/`max_cagr`, and the raw terminal prices) precisely so
thresholds can be re-derived without a rebuild. Anything of the form
"CAGR ≥ x", "excess ≥ x", or a **cross-sectional outcome rank** is a
one-liner in `value-ml-models` today:

```sql
-- era-neutral "top decile of the cohort" label, derivable from v1.x as-is
SELECT *,
       percent_rank() OVER (PARTITION BY quarter, snapshot_kind
                            ORDER BY fwd_3y_cagr) >= 0.9 AS label_3y_top_decile
FROM dataset WHERE fwd_3y_cagr IS NOT NULL
```

Era-ranked labels deserve a real experiment: `splits-diag` measured that
label base rates swing by era (quarter fixed effect up to 8.6% of label
variance), so absolute-threshold targets partly teach "which era is this".
A rank target has a constant base rate by construction and matches the
actual downstream objective (pick the best K of a cohort). If it earns its
keep, promote it to stored columns via an ADR; until then it costs nothing
to try.

### 1.3 Added with this change: tail rungs and excess rungs

- `label_{H}_cagr_ge_15` / `label_{H}_cagr_ge_20` — the mega-performer
  rungs requested. Note the class imbalance: at 5y, a sustained 20% CAGR is
  a small positive class; downstream should treat these as precision@K
  targets (or use `scale_pos_weight`), and per-fold base rates should be
  reported next to any precision number.
- `label_{H}_excess_ge_5` / `label_{H}_excess_ge_10` — "beat SPY by ≥5/≥10
  pts CAGR". Same "big win" idea but relative to the prevailing market, so
  the positive class doesn't collapse in bear eras and balloon in bull eras
  the way absolute rungs do. If only one new target gets modeling budget,
  make it these.

### 1.4 Why not a drawdown-*threshold* label yet

A `label_{H}_maxdd_le_30`-style binary needs the continuous drawdown first
(§1.5); once `fwd_{H}_max_drawdown` exists, thresholds are again
downstream-derivable. So the storable object is the continuous column, not
the binary.

### 1.5 Path-dependent labels — the real gap (needs stage-1 widening)

The one class of label information the dataset cannot currently express:
what happened *between* entry and horizon end. `fwd_{H}_min_cagr` is only
the terminal-month minimum — a stock that fell 80% in year 1 and recovered
looks identical to one that compounded smoothly. Proposed columns, in
increasing implementation cost:

1. `fwd_{H}_path_min_closeadj` / `fwd_{H}_path_min_cagr` — the lowest
   forward-filled close over the whole window vs. entry ("worst interim
   mark-to-market"). Identifies entries at risky valuations that
   *eventually* worked but were uncapturable in practice.
2. `fwd_{H}_max_drawdown` — max peak-to-trough over the forward path.
   Distinguishes "never underwater" compounders from round-trippers even
   when both end at the same CAGR.
3. **Triple-barrier labels** (PLAN §6, explicitly deferred) — once 1–2
   exist, the vol-scaled barrier machinery is the principled version.

PLAN §6 anticipated exactly this: stage 1 (`paths.py`) extracts only
terminal windows today and must widen to full paths "without touching the
label functions". Performance note for the implementation: a naive
snapshot×day join is ~4B rows (1.5M snapshots × up to 1260 forward days).
Don't materialize it. Compute per-stock daily running aggregates once
(`max(closeadj) OVER (…ROWS UNBOUNDED PRECEDING)`, running max-drawdown),
then evaluate each (snapshot, horizon) as a range query anchored on the
dense `ix` index — the path-min variant is a plain range-min and can be
done with a windowed `min` per snapshot over a lateral range join
restricted to the stock's own rows (O(stock-days × horizons) worst case;
prune by computing the 5y window once and deriving shorter horizons from
prefix structures). Prototype on the synthetic fixtures, then time on one
real year before committing. Delisting handling stays in stage 1: past the
final print the path is flat, so it contributes no new drawdown — that
falls out of the forward-fill for free.

### 1.6 Label-correctness risks that remain are data-level (do these first)

- **V6 (benchmark):** if SFP SPY `closeadj` is *not* total-return, every
  `beat_spy`/excess label is biased by SPY's ~1.5–2%/yr dividend yield —
  systematically mislabeling ~2%/yr of relative outcomes. One afternoon:
  compare SFP SPY closeadj growth vs. published SPY total-return over a few
  known windows.
- **V1 (datekey semantics):** PLAN §2 carries an unresolved note about
  observed discrepancies. If `datekey` is not reliably the public-availability
  date, features leak — which inflates backtest precision and produces
  exactly the symptom observed (good in-sample metrics, disappointing
  economics). Spot-check ~10 filings against EDGAR.
- **V4 (delisting prints):** decision 0002 carries positions at the final
  print; sample real bankruptcies to confirm final SEP prints reflect
  recoveries rather than stale halted quotes.

## 2. Features

### 2.1 "Discount relative to its own past" — the strongest addition

Nothing in the registry expresses "this stock is cheaper than *it* usually
is": valuation features are all point-in-time levels, and the rank pass
compares against the *cross-section*, not the stock's own history. For a
value thesis this is a first-class missing family. Design sketch
(new family `relvalue`, reusing the ADR 0015 history machinery):

- Extend `fund_history` buckets with the stock's own market price at each
  historical bucket: the last `closeadj`-consistent *unadjusted* close on
  or before `bucket reportperiod + ~45d` × that filing's
  `sharesbas × sharefactor` gives a point-in-time historical marketcap per
  bucket (same self-built convention as ADR 0007, no DAILY).
- Per bucket compute the historical ratio (start with `sales_yield` and
  `book_to_market` — the most stable denominators); emit per snapshot:
  - `{ratio}_vs_5y_median` — current ratio ÷ median of the trailing 20
    bucket values (>1 ⇒ cheaper than its own norm, for yield-oriented
    ratios);
  - `{ratio}_5y_pctile` — the current value's percent rank within its own
    trailing 20 observations (bounded, outlier-immune, NULL under the
    ADR 0015-style min-points rule).
- Point-in-time discipline is inherited: buckets already take the latest
  `datekey < snapshot_date` version of each period.

This family also composes with the ranks: `sales_yield_5y_pctile_rank`
answers "which stocks are most unusually cheap *for themselves* right now,
relative to the cross-section" — precisely the "distinguish cheap from
merely low-multiple" signal the models are missing.

### 2.2 Cheap price-only variants (do these regardless)

Price history needs no fundamentals matching, so these are near-free in the
technical family and carry much of the same signal:

- `dist_5y_high` — `entry_closeadj / max(closeadj, 1260d) − 1` (the 52-week
  version exists; the 5y version separates "off its all-time ramp" from
  "off a recent blip", i.e. the stock's own drawdown at entry).
- `price_vs_5y_avg` — entry vs. the trailing 1260d mean close (a
  slow-mean-reversion anchor).
- `mom_36_12` — long-term reversal (De Bondt–Thaler): 3y return excluding
  the last year; classic deep-value companion to `mom_12_2`.
- Optionally `max_ret_21d` (lottery/MAX factor) and a market beta — both
  well-documented cross-sectional predictors, both computable from `sep_ix`
  as-is.

### 2.3 Trend family extensions (same machinery as ADR 0015)

`SERIES` in `src/features/trend.py` is a dict — adding a series is one line
plus registry/docs rows. Highest-value additions:

- **Share count** (`sharesbas × sharefactor`): always positive, ideal for
  the log-slope fit; a 20q dilution trend is a value-trap discriminator the
  YoY `share_count_growth_1y` can't see.
- **Gross margin** and **debt** (`l_debt`, allow zeros via the up-frac/
  positive-frac forms): margin trajectory and deleveraging trajectory.
- **Net income**: sign-flips make log-slope inapplicable; use the
  `ocf_positive_frac`-style form (`ni_positive_frac_{w}q`) plus an
  `up_frac` on the raw series.

### 2.4 Standard formulas/scores — registry gaps vs. PLAN §5

- **Ohlson O-score** — promised in PLAN §5.2, never implemented (Altman Z,
  Z″, Zmijewski, Beneish, Piotroski, Mohanram all exist). All inputs are
  already in `fund_base` (`l_assets`, `l_liabilities`, `l_workingcapital`,
  `l_assetsc/l_liabilitiesc`, `f_netinc`, `f_ncfo`, `f1_netinc`); use
  `ln(assets)` in place of the GNP-deflated size term (note the deviation
  in docs/features.md, as done for other adaptations).
- **Magic-formula composite** — PLAN §5.1 names it; the components
  (`earnings_yield`/`ebit_to_ev`, `roc_greenblatt`) exist but the rank-sum
  composite was never built. It's a two-line assembly-stage composite
  exactly like `conservative_score` (ADR 0013 pattern:
  `ebit_to_ev_rank + roc_greenblatt_rank`, then ranked).
- **Piotroski components as flags** — the model sees only the 0–9 sum;
  exposing the nine signals as flag columns lets trees find that e.g. the
  equity-issuance signal matters more than the margin signal. Cheap, and
  the sub-expressions already exist in `quality.py`.

### 2.5 Market-regime features — keep deferred

Still the open question from PLAN §5.6/TODO. The hazard stands: under
temporal splits they are near-date-identifiers (the era-identifiability
concern `splits-diag` flagged from the *label* side). If pursued, only with
the pre-registered with/without ablation across regimes — after the
leakage-gap experiment establishes the measurement baseline.

### 2.6 What not to add

More correlated valuation ratios (P/E and E/P and EV/E …) add collinearity,
not signal — the yield-orientation convention already picked the usable
form of each. Feature count is not the constraint; the constraint is
independent information per era (§7.1's effective-sample-size argument),
which is why §2.1's *orthogonal* family beats ten more level ratios.

## 3. More samples — correction and options

**The median sample already exists.** Snapshots have been
low/**median**/high since the first labels commit (decision 0001,
`SNAPSHOT_KINDS` in `src/labels/snapshots.py`); `dataset_v1.x` carries
three rows per stock-quarter, the splits use all three kinds for training
and median-only for test, and the uniqueness weights pool the three kinds
(ADR 0012). If the downstream training pipeline is filtering to low/high
somewhere, that's a `value-ml-models` bug worth checking — but the dataset
side is done.

On adding *more* rows (fourth kind, monthly snapshots — the open TODO
question): the `splits-diag` numbers argue against expecting much. The
within-(stock, quarter) entry-price gradient explains only 3–11% of label
variance, and same-stock serial label correlation at 5y is 0.82 — extra
rows from the same stock and era are mostly redundant, the uniqueness
weights would (correctly) shrink them, and effective sample size is set by
the time dimension (PLAN §7.1). Monthly snapshots triple build cost and
overlap for a modest ESS gain. Verdict: spend the effort on §1/§2 instead;
revisit snapshot frequency only if a trained model demonstrably starves at
the current row count (learning curves flat vs. rows, not vs. features).

## 4. Sample weights

Setting all weights to 1 does **not** increase effective sample size — it
increases *nominal* sample size by re-counting the same forward windows.
The information content of 12 overlapping 3y windows is ~1 window; weighting
them 1.0 each makes the loss function believe dense eras and long horizons
harder than the data supports, which typically *worsens* generalization.
The 0.82 serial correlation at 5y is the measured justification for the
weights.

That said, the de Prado weight is a heuristic, and the right exponent is an
empirical question — and it is **already a downstream hyperparameter, not a
dataset change**: the stored column is unnormalized, so `value-ml-models`
can sweep `w^α` for α ∈ {0, 0.5, 1} (α = 0 is "all weights 1") per horizon
inside walk-forward today. Recommendation: register that sweep as an
experiment next to the leakage-gap one; ship nothing here.

Two wrinkles found during review (small, worth recording):

1. **Unobservable windows still count in `c(t)`** (`assemble/weights.py`
   builds windows from all of `labels_src`): a recent row whose horizon is
   observable gets extra concurrency from unobservable siblings that can't
   themselves be trained on. Effect: recent observable rows are slightly
   over-downweighted, only near the data edge. Fix if desired: filter
   `weight_windows` per horizon to `delisted_in_window_{H} IS NOT NULL`
   (weights would change bit-for-bit → dataset version bump + ADR 0012
   amendment).
2. **Median-only training** (if anyone trains that way downstream): the
   pooled weights then sum to ~1/3 of the "right" per-quarter mass.
   Harmless for scale-invariant objectives, but worth a note in
   docs/manual.md §5 if median-only training becomes a practice.

## 5. Bugs & weaknesses found in the review

No correctness bugs in label math, split tagging, purge/embargo arithmetic,
weight integration, or the rank pass (all re-derived by hand; the
boundary-integral weight computation checks out on worked examples). Items
found, by severity:

1. **Open verifications V1/V6/V4** — the only channels through which the
   dataset could still be silently wrong (§1.6). V1 in particular matches
   the observed symptom profile of leak-inflated backtests.
2. **Unobservable-window concurrency** in weights (§4.1). Small,
   edge-of-data only.
3. **Classification is current-state** (known, research §F8.3): today's
   sector labels applied retroactively are a mild lookahead *and* a mild
   entity fingerprint; `siccode` is the era-stable fallback. Accepted v1
   caveat — but note the interaction: `mohanram_g7` and all `_secrank`
   columns inherit it.
4. **No min-obs guard on `dollar_volume_3m`/`amihud_12m`** — a stock with
   two prints in the quarter gets a "liquidity" estimate from them. NULL
   below ~10 obs would be cleaner (registry null-rule change, cheap).
5. **Shares between filings**: marketcap uses T0-filing shares at the
   snapshot close (ADR 0007, validated to <0.1% vs DAILY); buybacks between
   filings are invisible. Known and accepted; recorded here for
   completeness.
6. **`quarter_trading_days` has no floor**: a stock that traded 3 days in a
   quarter still emits three (nearly identical) snapshots. Downweighted by
   0012, and the column lets downstream filter; consider whether a
   1-print quarter should emit snapshots at all next time snapshots change.

## 6. Where the gap most plausibly lives (beyond the dataset)

Worth stating so dataset work is aimed correctly:

- **Investability.** A total-market universe is microcap-dominated
  (manual §8); high paper precision concentrated in names with $50k/day
  volume does not beat the market in dollars. The liquidity-floor *flag*
  question in TODO is worth resolving now, and downstream evaluation should
  report precision@K under an investability filter
  (`dollar_volume_3m`, `log_marketcap`) as the headline number, not the
  unfiltered one.
- **Era base rates.** Absolute-CAGR targets entangle stock selection with
  market timing; the new excess rungs and the derivable rank labels (§1.2)
  are the mitigation. If precision is "inconsistent" across folds, check
  whether the inconsistency tracks the fold-year base rate before blaming
  the features.
- **Effective sample size.** Σ`sample_weight` per era (manifest
  `effective_rows`) is the honest denominator; at 5y the dataset is a small
  dataset wearing a big row count (PLAN §7.1), and no feature engineering
  changes that. Expect model-selection confidence to degrade with horizon
  (PLAN §7.5) — favor the 1y–3y models for evidence of progress.
- **Run the registered experiments** (leakage-gap, era-identifiability —
  manual §7): they directly diagnose whether current validation numbers
  are trustworthy, which determines whether "not good enough" means the
  signal isn't there or the measurement flattered earlier iterations.
