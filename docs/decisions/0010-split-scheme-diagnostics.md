# 0010 — Split-scheme debate: temporal seal stays the arbiter; measure the leakage instead of arguing it

Date: 2026-07-17
Status: accepted

## Context

The PLAN §7 splitting methodology (temporal splits + per-horizon purging +
embargo) was challenged on several grounds:

- The three low/median/high snapshots already vary entry price within a
  quarter, and most price-touching features move with them — so maybe the
  sibling rows are less redundant than §7.1 claims, and approximate
  memorization is a smaller risk.
- Memorization is also mitigated at training time (regularization, tree
  depth), not only by the split.
- The cross-sectional overlap argument seemed weak: AAPL-2015 features have
  no obvious reason to be correlated with MSFT-2015 features, and with no
  date or ticker columns in the feature set, "there is no way to tell what
  date a sample comes from" — so a random or ticker split should be fine,
  and a **permanent ticker-split validation set** was proposed as the fixed
  yardstick for comparing splitting strategies empirically.
- Purging burns a lot of data (5× more at the 5y horizon), which both
  shrinks samples and could make results sensitive to which eras remain.

Counter-arguments raised in review:

- *Era identifiability is an empirical claim, not a given.* Technical
  features (trailing returns, volatility, distance-from-high) are strongly
  cross-sectionally correlated within a date; raw valuation levels drift
  with regimes (the §5 rationale for ranks); sector composition is
  era-varying; and labels are **not** ranked — absolute-CAGR base rates
  swing hugely by era. Weak era signal in features × strong era signal in
  labels = credit for recalled era outcomes under any split that shares
  eras across the boundary.
- *Purging is about metric honesty, not about preventing memorization.*
  Regularization strength is chosen by validation score; a leaky validation
  metric systematically selects the leakier configuration. The mitigation
  the challenge points to is itself powered by the thing being challenged.
- *A ticker-split yardstick begs the question.* A held-out ticker's rows
  share every era with training data, so a splitting strategy that exploits
  temporal leakage scores **better** on it. One cannot adjudicate whether
  temporal leakage matters using a temporally-leaky arbiter. The temporal
  holdout is the one test set whose meaning does not depend on the outcome
  of this debate, because deployment is unconditionally temporal: the model
  will only ever be used on dates later than all its training data.
- The "trained on 1997 and 2003" fear misreads the mechanics: walk-forward
  trains on contiguous expanding windows; purging is boundary-local, and
  across folds nearly every row trains in some fold. The permanent loss is
  the newest `horizon + embargo` years relative to the sealed holdout —
  real, per-horizon, and quantifiable.

## Decision

1. **The sealed temporal `holdout` remains the only arbiter.** Nothing about
   model selection or reported performance changes.
2. **Two diagnostic-only schemes are added to the §7.3 tagging:**
   `entity_holdout` (the proposed ticker split, kept as the §7.4
   firm-identity-memorization diagnostic) and `random_kfold` (deliberately
   leaky baseline). Both are tagged in the dataset, and both are forbidden
   for model selection or reported performance.
3. **The disagreement becomes an experiment.** `value-ml-models` trains
   identical models under `random_kfold`, `entity_holdout`, and purged
   `walkforward`; the score gaps are the measured size of the leakage. If
   negligible, the methodology gets relaxed with evidence; if large, it
   stands with evidence.
4. **The empirical questions get a data-gated report**, `sharadar-qa
   splits-diag` (PLAN §7.7, workspace `docs/research/splits.md`): which
   features actually move intra-quarter (and the filing-straddle rate); how
   label variance decomposes into the entry-price gradient vs. the
   calendar-quarter fixed effect; same-stock serial label correlation by
   lag; low/high label flip rates per threshold; a nearest-neighbor twin
   test for row uniqueness; and a purge-cost table per horizon and
   boundary (unweighted counts now, uniqueness-weighted effective sample
   sizes once M5 defines `sample_weight`).

## Consequences

- M5 tagging schema gains two schemes; the assembly work must emit them
  alongside `holdout`/`walkforward` (the `(scheme, fold, horizon)` schema
  already accommodates this).
- The purge-cost worry stops being qualitative: the report prices it per
  horizon and boundary before any splitting code is trusted.
- The leakage question has a terminal state: after the gap experiment runs,
  either the §7 rules relax or they stop being contested — both outcomes
  documented, neither achieved by burning the sealed holdout.
- Diagnostics run on real data after `make features`; results land in
  `docs/research/splits.md` and `docs/research/reports/splits_diag.md`.
