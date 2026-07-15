# 0008 — Rank representation: percent_rank within (quarter, snapshot_kind)

Date: 2026-07-14
Status: accepted

## Context

PLAN §5 stores every numeric feature twice — raw and cross-sectional rank —
with the cross-section originally phrased as "within snapshot date." But
decision 0001 makes snapshot dates intra-quarter *touch dates*, scattered
per stock across the quarter, so the cross-section at any exact date is a
thin, kind-biased slice (features.md §F7). TODO also asked whether ranks
should additionally be computed within sector. Coverage data (features.md
§F10) sized the sector cross-sections.

## Decision

1. **Rank scope is (calendar quarter, snapshot_kind).** Each row's rank
   features are `percent_rank()` over all in-universe rows of the same
   quarter and the same kind — everyone compared at *their* low/median/high.
   Fundamentals are quarter-shared so this is exact for them; price-based
   features are asynchronous by up to ~13 weeks, accepted (the alternative
   — a full-universe feature recompute at every touch date — is a ~60×
   compute blowup; a fixed quarter-end reference cross-section leaks other
   firms' post-snapshot fundamentals and was rejected on PIT grounds).
2. **Mechanics:** ranks are computed at assembly time (they need the full
   cross-section, so they cannot live in per-family modules); NULL raw ⇒
   NULL rank; a cross-section with fewer than **20** non-null values ⇒ NULL
   rank (thin-slice guard). Column naming: `{feature}_rank`.
3. **Sector-relative ranks for an allowlist only**, named
   `{feature}_secrank`, scoped (quarter, kind, Sharadar sector): the
   valuation yields, `gp_to_assets`, `accruals_to_assets`, and the margin
   levels — the features with documented industry structure. Coverage data
   supports this: the smallest real sector cross-section is ~60 rows/quarter
   (residual Financial Services), above the guard; the "(none)" sector
   (~700 rows all-time) falls below it and gets NULL sector-ranks. No
   blanket ×3 column blowup; Mohanram G already carries industry-relative
   signals separately.
4. **Raw values stay untouched** — no winsorization/clipping (ranks are the
   outlier defense; raw is for analysis and re-derivation). Composites are
   ranked like any other numeric feature; boolean flags and classification
   columns are not ranked.

## Consequences

- Ranks are stationary across valuation regimes by construction and
  comparable across the three snapshot kinds without mixing them.
- Assembly owns a registry-driven rank pass; adding/removing a feature's
  rank or sector-rank is a registry flag, not code.
- The margin-of-safety gradient stays visible: a stock's low-kind rank on
  price-derived features can differ from its high-kind rank, by design.
- Accepted caveat: early-quarter snapshots are ranked against numbers from
  peers' filings that may post-date them slightly (via the peers' own
  snapshot rows). This is cross-*sectional* context, not information about
  the ranked stock's future; the model consumes ranks only as relative
  position, matching how the strategy would rank a live cross-section at
  deployment.

## Clarification (2026-07-15)

"Fundamentals are quarter-shared so this is exact for them" (Decision §1)
describes the common case, not a mechanic. Resolution is strictly per
`snapshot_date` (decision 0001: no special casing per kind), so a filing
whose `datekey` lands between two same-quarter kinds' snapshot dates puts
those kinds on different filings — and a (quarter, kind) rank cross-section
can therefore mix filing vintages across firms. This is the same
cross-sectional-context situation as the accepted caveat above: PIT-safe
for the ranked firm, matching a live deployment cross-section. Pinned by
the straddle test in tests/test_features_cli.py.
