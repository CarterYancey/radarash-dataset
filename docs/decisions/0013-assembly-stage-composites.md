# 0013 — Assembly-stage composites: Mohanram G7 mechanics + conservative score

Date: 2026-07-18
Status: accepted

## Context

Two registry columns are assembly-stage (decision 0003, docs/features.md):
`mohanram_g7` needs an industry cross-section that per-family modules never
see, and `conservative_score` is a rank-sum over ranks that only exist at
assembly (decision 0008). Implementing assembly (M5) forced their exact
mechanics, and exposed that four of Mohanram's per-firm signal inputs were
not yet stored by any family — assembly joins family parquets and must not
re-derive fundamentals (research §F8.2), so the inputs have to live in a
family.

## Decision

### Mohanram G7 (quality family, tier T3)

Four new **quality-family component features** feed it (components are
primary, composites near-free over them — the decision-0003 philosophy):

| column | tier | definition |
|---|---|---|
| `rnd_to_assets` | T0 | `coalesce(rnd, 0) / assets_q` — unreported R&D counts as zero (Mohanram's convention; the only registry feature with an explicit fill, documented here and in the registry) |
| `capex_to_assets` | T0 | `−capex / assets_q` (SF1 cash-flow sign convention, like `dividend_yield`) |
| `roa_variability_3y` | T3 | sample stddev of the four annual ROA observations `{roa, roa₋₁, roa₋₂, roa₋₃}`; NULL unless all four exist |
| `revenue_growth_variability_3y` | T3 | sample stddev of the three YoY revenue growth observations `{rev/rev₋₁, rev₋₁/rev₋₂, rev₋₂/rev₋₃} − 1`; NULL unless all three exist (each NULL when its denominator ≤ 0) |

Annual (not quarterly) variability is a documented deviation from Mohanram
2005 (16 quarters): ADR 0004 caps fundamental depth at T3, and the lag
machinery is reportperiod-matched annual pairs.

`mohanram_g7` = the sum of seven binary signals, evaluated at assembly
within the **(calendar quarter, snapshot_kind, `famaindustry`)**
cross-section (same quarter/kind scoping as decision 0008's ranks; industry
medians include the firm itself):

1. `roa` > industry median
2. `cfo_to_assets` > industry median
3. `cfo_to_assets > roa` (accruals signal — firm-level, no median)
4. `roa_variability_3y` < industry median
5. `revenue_growth_variability_3y` < industry median
6. `rnd_to_assets` > industry median
7. `capex_to_assets` > industry median

The eighth published signal (advertising intensity) has no SF1 field
(research §F1) — hence G7, not G8. A median is NULL unless its industry
cross-section has at least **5** non-null values (`--min-industry-peers`;
a median over one or two firms makes the comparisons degenerate). Composite
null rule as everywhere: any NULL signal (missing input, NULL
`famaindustry`, or a guarded-out median) ⇒ NULL `mohanram_g7`.

### Conservative score (technical family, tier P36)

Blitz & van Vliet's rank-sum over the three stored components, using the
decision-0008 rank columns themselves (percent_rank within quarter × kind,
thin-slice guard included):

```
conservative_score = (1 − vol_36m_rank) + mom_12_2_rank + net_payout_yield_rank
```

Range [0, 3]; low volatility, high momentum, high net payout are all
"good". NULL if any of the three ranks is NULL. It is then ranked like any
numeric feature (`conservative_score_rank`), as is `mohanram_g7`.

## Consequences

- The quality family gains four independently useful features (R&D and
  capex intensity, earnings and growth stability — all with literature
  support) and the composite stays auditable from stored columns.
- `src/features/` grows two ART fields (`rnd`, `capex`) and deeper lag
  columns (`netinc` at lags 2–3, `assets` at lags 2–3); docs/features.md
  and `registry.py` updated together as required.
- `mohanram_g7` coverage is bounded by T3 chain survival *and* the
  industry-peer guard; expect NULLs for young firms and thin industries —
  measure in the post-build coverage report rather than relaxing the guard
  blind.
- Both composites are recomputed at every assembly; changing a component
  definition re-derives them with no separate migration.
