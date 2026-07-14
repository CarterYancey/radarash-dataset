# 0006 — Staleness: no feature-level cutoff; age is a feature, cutoffs are flags

Date: 2026-07-14
Status: proposed

## Context

TODO listed two related open questions: the fundamentals staleness cutoff
at snapshot time (6 vs. 12 months) and whether snapshots should require an
ARQ filing in the trailing 12 months (minimum-data filter). The concern was
that features computed from old filings are unreliable; the counter-concern
(features.md §F4.4) was that late filing is itself distress signal and a
hard cutoff would bias the label distribution. `sharadar-qa staleness` ran
against the full ingest (features.md §F11, `docs/research/reports/`).

## Decision

Measured on 515k median-kind snapshots: 95.1% have a filing ≤183 days old;
the 184–365d and >365d buckets are only 0.67% and 1.3% of rows — but carry
delist-within-1y rates of **24.8% and 29.4%** vs. 7.9% for fresh rows, with
median 1y forward CAGR ≈ −10% vs. +1.4%. Staleness is one of the strongest
distress signals available. Therefore:

1. **No feature-level staleness cutoff.** Features are always computed from
   the freshest filing with `datekey < snapshot_date`, however old it is.
   No row is dropped for having stale or missing fundamentals.
2. **`fundamentals_age_days` is a first-class feature** (raw + rank), so
   models see exactly what a cutoff would have hidden.
3. **Cutoffs become flag columns**, not filters: `has_filing_183d` and
   `has_filing_365d` are stored per row; any downstream consumer that wants
   a cutoff applies it as a filter with full knowledge of what it removes.
4. The 12-month bound survives only inside QA tier definitions
   (`sharadar-qa coverage`'s T-tier gating, per ADR 0004) as a coverage
   *measurement*, not as a dataset rule.

This also resolves the minimum-data-filter question by the same mechanism:
no ARQ-in-trailing-12-months requirement; the flags carry the information.

## Consequences

- The dataset keeps the 2% of rows with the highest distress signal —
  exactly the rows a deep-value model must learn to avoid or exploit; the
  label distribution stays unbiased by construction-time filtering.
- The >365d bucket's return distribution is extreme (median −7%, mean
  +230% — the delisting-lottery right tail); downstream models see it via
  the age feature rather than having it silently removed.
- No-filing snapshots (3.0%, mostly young pre-first-filing listings) keep
  all-NULL fundamentals features and NULL `fundamentals_age_days`; trees
  route on the missingness itself.
- Anyone comparing against a filtered baseline can reproduce any cutoff
  exactly from the stored flags — the decision is reversible downstream at
  zero recompute cost.
