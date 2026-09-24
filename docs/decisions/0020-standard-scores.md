# 0020 — Standard scores: Ohlson O-score, magic-formula composite, Piotroski signal flags

Date: 2026-09-24
Status: accepted (amends 0003: the Ohlson composite is no longer deferred)

## Context

`docs/research/dataset-improvements.md` §2.4 lists three registry gaps
against PLAN §5, all cheap because their inputs are already stored:

- **Ohlson O-score** — PLAN §5.2 promises it; ADR 0003 deferred the
  composite because its size term wants GNP-deflated assets (an external
  macro series). All nine components are solvency-family columns.
- **Magic formula** — PLAN §5.1 names it; both components (`ebit_to_ev`,
  `roc_greenblatt`) exist, the rank-sum never did.
- **Piotroski components** — the model sees only the 0–9 sum
  (`piotroski_f`), so it cannot learn that one signal (say, equity
  issuance) matters more than another (say, margin).

## Decision

1. **`ohlson_o`** (solvency, T1): Ohlson (1980) model 1,

   ```
   O = −1.32 − 0.407·ln(assets/10⁶) + 6.03·TL/TA − 1.43·WC/TA
       + 0.0757·CL/CA − 1.72·[TL > TA] − 2.37·NI/TA − 1.83·FFO/TL
       + 0.285·[NI < 0 two years] − 0.521·CHIN
   ```

   from the stored components (`liabilities_to_assets`, `wc_to_assets`,
   `cl_to_ca`, `liab_gt_assets`, `roa`, `ffo_to_liabilities`,
   `two_year_loss`, `ni_change_scaled`). Higher = more distress. NULL if
   any component is NULL (classified-balance-sheet ⌂ gap inherited).
   **Deviation:** the size term is nominal `ln(total assets in $M)`, not
   deflated by the GNP price level. Within a quarter this is a constant
   shift for every firm, so ranks are unaffected; the raw score drifts
   ≈ 0.407 × inflation ≈ +0.01/year across eras — small next to the
   cross-sectional spread, and `log_assets` already carries the same
   nominal drift. FFO is proxied by CFO as in `ffo_to_liabilities`. The
   logistic transform `1/(1+e^−O)` is monotone and not stored.

2. **`magic_formula_score`** (valuation, T0, assembly-stage):
   `ebit_to_ev_rank + roc_greenblatt_rank` — Greenblatt's rank-sum in the
   dataset's orientation (higher = better), range [0, 2], NULL if either
   rank is NULL. Built exactly like `conservative_score` (ADR 0013): from
   the pass-1 rank columns, then ranked itself (`full`). Assembly's second
   rank pass now takes a table of rank-sum composites
   (`assemble.wide.RANK_COMPOSITES`). Greenblatt's exclusions (financials,
   utilities, a size floor) are left to downstream filters.

3. **Nine Piotroski flags** (quality), the exact sub-expressions summed by
   `piotroski_f`, in Piotroski's order: `piotroski_roa_positive`,
   `_cfo_positive`, `_roa_up`, `_cfo_gt_ni`, `_leverage_down`,
   `_liquidity_up`, `_no_issuance`, `_margin_up`, `_turnover_up`. Flags
   are never ranked (ADR 0008). A signal whose inputs are missing is
   **NULL, not False** — so a young firm shows its current-filing signals
   (T0) while the YoY ones (T1) are NULL, whereas `piotroski_f` stays NULL
   unless all nine are known. Missing stays signal, not "failed".

## Consequences

- Dataset v1.4; 11 new columns (+ `ohlson_o_rank`,
  `magic_formula_score_rank`). No existing column changes.
- `piotroski_f` and the flags are redundant by construction (the sum is a
  function of the flags when all are known); trees tolerate this, linear
  models should pick one representation.
- Tests: `tests/test_features_cli.py` pins ACME's O-score and flag vector
  by hand and NEG's NULL pattern (current-filing flags set, YoY flags and
  O-score NULL); `tests/test_assemble_cli.py` pins the magic-formula
  rank-sum and its rank.
