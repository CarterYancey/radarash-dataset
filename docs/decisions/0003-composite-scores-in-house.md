# 0003 — Composite scores: compute in-house; store components and composites

Date: 2026-07-13
Status: accepted

## Context

The feature set includes published composite formulas (Piotroski F, Altman
Z-family, Beneish M, Zmijewski, Mohanram G, Magic formula, Conservative
formula). Four sourcing options were on the table: (a) buy pre-computed
scores from a vendor (GuruFocus etc.); (b) compute the published formulas
ourselves from SF1; (c) store only the underlying components as features;
(d) fit a custom re-weighted score. Research notes:
`docs/research/features.md` §F2.

## Decision

**Compute everything in-house from SF1 as-reported data (ARQ/ART). Store
both the components (primary features) and the canonical published
composites (one SQL expression each). No vendor score data. No custom
fitted score in the dataset.**

- Components are first-class features: composites discard magnitude
  (binary signals) and carry weights fit on decades-old samples; tree
  models relearn thresholds and interactions from raw ratios.
- Canonical composites are stored anyway: near-zero cost over the
  components, interpretable baselines ("did the model beat plain
  F-score?"), and cross-checks against published distributions in tests.
- Vendor scores are rejected because they are computed from standardized,
  *restated* financials — a lookahead violation of the point-in-time
  invariant — and add a second identity system, unverifiable delisted-stock
  coverage, and licensing burden, while being *less* auditable than our own
  arithmetic (which gets hand-checked fixture tests).
- A custom re-weighted score is model training, not dataset construction;
  it belongs in `value-ml-models`, computed from the stored components,
  respecting the splits. Baking one into the dataset would leak model
  fitting into data construction.

Variant choices bundled here: Altman **Z''** is the featured distress
composite for the mixed universe (classic Z also stored for literature
comparability); the **Ohlson O composite is deferred** (its size term needs
a GNP-deflator series; components are all stored) with Zmijewski + Z''
covering the single-number distress need; Mohanram G ships as a **7-signal
variant** (SF1 has no advertising-expense field).

## Consequences

- Every score's inputs are unit-testable against hand-checked filings, in
  the repo's existing synthetic-fixture style; published base-rate
  distributions become test assertions.
- ~30 shared component columns serve multiple composites (ΔROA feeds
  F-score, profitability trends, and O-components), bounding feature-count
  growth.
- We accept documented deviations where SF1 lacks a field (G-score
  advertising signal; Sloan accruals via the cash-flow method; O-score FFO
  proxied by `ncfo`), recorded per-feature in the registry.
- No external data contract, no restatement-audit of a third party.
