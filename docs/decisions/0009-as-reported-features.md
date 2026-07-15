# 0009 — Features stay as-reported; restated data is a downstream diagnostic only

Date: 2026-07-15
Status: accepted

## Context

PLAN §2 forbids the restated SF1 dimensions (`MRQ`/`MRT`/`MRY`) for
features on leakage grounds. A deeper challenge was raised after M4: the
real-world causal determinant of long-term success is what a company
*actually had*, not what it reported. If the goal is to learn the
relationship between true financial health and long-term outcomes — and to
detect the winners with high precision — shouldn't features come from the
fixed (restated) financials rather than the as-reported ones?

## Decision

**Features remain ARQ/ART exclusively. Restated dimensions may be used
only as a diagnostic ablation in `value-ml-models`, never in a shipped
dataset version.** Three reasons, beyond the mechanical leakage rule:

1. **Deployment consistency.** At prediction time only as-reported data
   exists — the restated version of the current quarter arrives months or
   years later, if ever. A model trained on restated inputs learns a
   mapping from variables it will never observe at inference. Features
   from as-reported data with labels from actual outcomes (total returns
   already measure "what actually happened") *is* the deployable causal
   question: given what is knowable, what predicts long-term success.
2. **Restatement timing embeds the label.** Restatements are not random
   corrections: they cluster in fraud, distress, and bankruptcy, and they
   post-date — often are *caused by* — the bad outcome. Enron's restated
   financials look damning precisely because the collapse forced them.
   Training on restated features injects the outcome into the inputs on
   exactly the high-stakes rows, inflating precision estimates where the
   model most needs to be honest.
3. **The reported-vs-actual gap is itself the signal.** The divergence
   between what a company reported and what it had is earnings
   manipulation — the thing the quality family (accruals_to_assets,
   Beneish M and its indices, F-score) exists to detect from the knowable
   side. Feeding the model post-hoc truth would remove the very problem
   the deep-value thesis needs it to learn to solve.

## Consequences

- The production dataset is unchanged; this ADR records the rationale so
  the question isn't relitigated from memory.
- A **diagnostic ablation is registered for `value-ml-models`**: train a
  restated-feature (MR*) variant under the *same* purged/embargoed splits
  and compare walk-forward metrics against the as-reported model. The gap
  quantifies what reporting distortion costs — an upper bound on the value
  of better forensic features — without contaminating the production
  dataset. Diagnostic only; its outputs never ship.
- Interpreting that ablation needs care: part of any MR* advantage is
  leakage (reason 2), not information — the comparison bounds, it does not
  attribute.
