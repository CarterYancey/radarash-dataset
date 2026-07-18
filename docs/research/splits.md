# Splits research workspace (pre-M5)

Working document for the split-methodology questions raised against PLAN §7.
Findings and run results accumulate **here** — not in README/PLAN/CLAUDE.
Settled questions graduate to ADRs; the debate's resolution is
[decision 0010](../decisions/0010-split-scheme-diagnostics.md) (accepted),
which turned the remaining disagreements into measurements.

Status 2026-07-18: diagnostics run against real data
(`docs/research/reports/splits_diag.md` + CSVs); findings recorded below.
The M5 tagging (`make splits`, decision 0011) emits the diagnostic-only
`entity_holdout` / `random_kfold` schemes alongside `holdout`/`walkforward`,
and `dataset_v1.0` has shipped, so the leakage-gap experiment below is
unblocked in `value-ml-models` (see `docs/manual.md` §7).

## The debate, compressed

Challenge to §7: the low/median/high snapshots already vary entry price;
memorization is partly the model's job to resist; cross-sectional overlap
(AAPL-2015 ↔ MSFT-2015) seems weak since features carry no dates/tickers
("given two samples it should be impossible to tell which comes first");
purging is expensive, especially at 5y; proposal — fix a permanent
ticker-split validation set and compare splitting strategies empirically.

Held (from the challenge): the purge cost must be quantified, not accepted
qualitatively; empirical comparison beats more theory; a ticker holdout is
worth tagging.

Rejected (with the §7.1/0010 reasoning): era identifiability is testable
and probably real (technicals are cross-sectionally correlated within a
date, raw levels drift, sector mix is era-varying, and label base rates
swing by era while labels are never ranked); leaky validation corrupts the
model selection that was supposed to supply the training-time mitigation;
and a ticker-split **arbiter** rewards exactly the temporal leakage under
debate — the sealed arbiter must be temporal because deployment is.

## Walk-forward mechanics FAQ

Follow-up question after 0010: doesn't per-horizon purging risk a model
trained on a scattered, non-adjacent grab-bag of years (e.g. "1997 and
2003"), making it sensitive to which eras happen to get drawn? No — this
misreads the fold shape. Full mechanics, diagram, and the k-fold analogy
are in PLAN §7.2 ("Walk-forward fold shape"); short version:

- Every fold's training set is a single **contiguous prefix** of history
  (like `sklearn.model_selection.TimeSeriesSplit`, generalized with a
  per-horizon purge width instead of `TimeSeriesSplit`'s fixed `gap`).
  Purging only removes the `horizon + embargo`-wide strip immediately
  before that fold's test boundary — it never touches the interior of the
  prefix, which is what "boundary-local" means.
- A row purged from one fold is not purged from the project: it was a test
  row in an earlier fold and becomes an ordinary training row again once
  later folds' boundaries pass it. Across the full walk-forward sequence,
  nearly every row trains in most folds.
- Walk-forward folds exist to pick the model configuration (features,
  hyperparameters) via honest, non-leaky measurement. The model that
  actually ships is refit on all eligible data up to the present — the
  purge/embargo/holdout discipline constrains measurement, not what the
  deployed model learns from.
- The apparent "cost" of purging at long horizons is partly not purging at
  all: a horizon-H label doesn't exist for snapshots newer than
  `last_price_date − H`, so some of what looks like purge cost is
  unavoidable label-observability lag. `purge_cost` (below) separates the
  two by reporting actual eligible/purged counts rather than a
  back-of-envelope width.

## Questions → where they get answered

| # | Question | Diagnostic (report section) |
|---|---|---|
| Q1 | Which features change with price; how many are constant through a quarter? | `feature_intraquarter` (+ `filing_straddle` for the only way "constant" features move) |
| Q2 | How much within-quarter variance do features and labels actually show? | `feature_intraquarter` rel. ranges; `label_variance_decomposition` (within-(stock, quarter) share); `label_kind_flip` (does the gradient flip binary labels?) |
| Q2b | How big are the §7.1 overlap channels? | `label_serial_correlation` (serial); `quarter_fe_share` (cross-sectional) |
| Q3 | How unique are rows — is "AAPL-2015 neighborhood" memorization possible? | `twin_relations` + `twin_label_corr` (nearest-neighbor vs. random-pair label correlation) |
| Q4 | What does purging cost, per horizon and boundary? | `purge_cost` (unweighted; uniqueness-weighted ESS added once M5 defines `sample_weight`) |
| Q5 | How much does any of it move a trained model's score? | **Leakage-gap experiment** in `value-ml-models` (below), not this repo |

Run: `make features && uv run sharadar-qa splits-diag` (knobs:
`--embargo-days`, `--test-starts`, `--twin-sample`). Committable output:
`docs/research/reports/splits_diag.md` + CSVs.

## Registered downstream experiment (value-ml-models)

After `dataset_v1.0`: train identical models under `random_kfold`,
`entity_holdout`, and purged `walkforward` tags; evaluate each the same way.
The score gaps are the measured leakage — random-vs-purged bounds the total
overlap leakage; entity-vs-purged isolates whether firm identity adds
anything beyond it. Diagnostic only: neither scheme is ever used for model
selection or reported performance (0010), and the sealed temporal holdout
is not consumed by this experiment. A useful side diagnostic once models
exist: predict the calendar year from features alone (raw vs. rank sets) —
if that classifier beats chance comfortably, "you can't tell what date a
sample comes from" is settled negatively.

## Findings (real-data run 2026-07-18)

Source: `reports/splits_diag.md` + CSVs, from the first full real-data
build (515,731 stock-quarters). Verdict up front: **nothing overturns the
§7 design** — the temporal purged/embargoed scheme stays the arbiter, and
every quantity the debate said to measure came back on the side 0010 bet on.

- **Q1 — feature movement matches the predicted split exactly.**
  Price-touching features (technical, valuation yields, market-scaled
  solvency) differ across the three kinds in ~99% of stock-quarters;
  fundamental-only features (growth, quality, profitability) differ in
  ~74–75% — indistinguishable from the 72.4% of quarters that straddle a
  filing (`datekey` between two kinds' snapshot dates). Fundamentals move
  within a quarter only via filings, as designed.
- **Q2 — the entry-price gradient is real but modest.** Binary labels flip
  between the low and high kinds in 26–29% of groups at 1y, falling to
  12–15% at 5y; the within-(stock, quarter) share of all-kinds label
  variance is 3–11%. The low/median/high snapshots are a genuine
  margin-of-safety signal, not label noise — but they don't substitute for
  temporal discipline.
- **Q2b — the overlap channels the challenge doubted are measurable.**
  Serial: same-stock median-kind label correlation at lag 4 quarters is
  −0.00 (1y), 0.44 (2y), 0.68 (3y), **0.82 (5y)** — long-horizon rows are
  massively serially redundant, which is what purging (and the 0012
  uniqueness weights) price. Cross-sectional: the calendar-quarter fixed
  effect explains 0.3% (1y) to 8.6% (2y) of median-row label variance —
  small but nonzero; era information is in the labels.
- **Q3 — twins exist and their labels agree.** 54.5% of nearest neighbors
  in quarter-ranked feature space are the same stock within a year (plus
  1.6% same-quarter peers), and nearest-pair label correlation is 0.40–0.73
  vs. ≈0 for random pairs. Approximate memorization has something concrete
  to recall — the §7.4 concern is not hypothetical, and the
  `entity_holdout` diagnostic has a real target.
- **Q4 — purge cost is bounded and mostly short-horizon-cheap.** At the
  three most recent boundaries, purging removes 3.2–3.9% of the training
  pool at 1y, ~7% at 2y, ~10–11% at 3y, and 16.9–17.9% at 5y. The 5y cost
  is material but far from crippling — and per the §7.2 mechanics, purged
  rows are boundary-local, not lost to the project.
- **1y labels are heavy-tailed**: all-kinds 1y label variance (280) is
  outlier-dominated (2y–5y CAGRs are well-behaved). Noted in the manual
  (`docs/manual.md` §8) as a downstream modeling caveat.

**Q5 (does any of this move a trained model's score?)** remains the
registered leakage-gap experiment in `value-ml-models` — unblocked now
that `dataset_v1.0` carries the diagnostic tags.
