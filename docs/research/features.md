# Feature-set research workspace (pre-M4)

Working document for the research and planning phase of the feature set.
Findings, source notes, and candidate definitions accumulate **here** — not
in README/PLAN/CLAUDE. When a question is settled it graduates:

```
findings here → ADR in docs/decisions/ → canonical registry docs/features.md
             → implementation in src/features/ (one module per family)
```

Starting scope is PLAN.md §5 (seven families + the rank-representation rule).
Nothing below is decided until it has an ADR.

## Research questions

### Cross-family (answer once, apply everywhere)

- [ ] **SF1 field inventory.** Which SF1 columns does each formula need, at
      which dimension (ARQ vs. ART), and what are their null rates by year and
      sector? (Feeds V5; determines what is computable at all.)
- [ ] **History depth.** Several families need N consecutive ARQ rows of the
      same permaticker (M-score: 2, trends: 4–8). How much of the universe
      survives each requirement, per year? Where do fiscal-year changes and
      amended filings break "consecutive"?
- [ ] **Staleness interaction.** How does the fundamentals staleness cutoff
      (TODO.md open question, 6 vs. 12 months) interact with per-family
      availability — e.g. late filers are disproportionately distressed, which
      is exactly the signal some families target. Does a cutoff bias the label
      distribution?
- [ ] **Rank representation details.** Within-date only or within-date-and-
      sector (TODO.md)? Percentile method for ties/small cross-sections; do
      ranks get recomputed per snapshot_kind or per (date)? (The three
      same-quarter kinds share fundamentals but not prices.)
- [ ] **Winsorization/clipping of raw values** — or rely on ranks entirely and
      store raw untouched?
- [ ] **Negative-denominator semantics.** P/E with negative earnings, EV/EBITDA
      with negative EBITDA, etc.: NULL, signed convention, or separate flag
      column? Must be one consistent rule across families.
- [ ] **Point-in-time market inputs.** Valuation ratios need price/market cap
      *on the snapshot date*: from SEP × shares outstanding, or Sharadar DAILY
      (marketcap, ev, pe, pb, ps)? Verify DAILY is point-in-time safe and
      consistent with our entry prices.

### Per family (PLAN.md §5 numbering)

1. **Valuation** — exact formula variants (trailing vs. TTM inputs); FCF
   definition from SF1; composite scores (Piotroski F, Magic formula,
   Conservative formula) — components, and whether composites add value over
   their components for tree models.
2. **Solvency/distress** — Altman-Z variant for a mixed universe (original is
   manufacturing-only; Z'' exists for non-manufacturers); Ohlson O-score
   coefficient re-use vs. raw components only (components likely preferable:
   let the trees learn the weights).
3. **Earnings quality (M-score)** — Beneish component definitions from ARQ
   pairs; sensitivity to fiscal-quarter alignment (`calendardate` grouping
   allowed for cross-sectional alignment only).
4. **Profitability & growth** — ROIC denominator convention; margin-trend
   window lengths; YoY vs. sequential growth; small-denominator explosions.
5. **Technical** — total-return windows from `closeadj`; volatility estimator
   (close-to-close σ vs. others); 52-week-high distance uses adjusted or raw
   high?
6. **Market-regime (candidate)** — construction of snapshot-date market P/S /
   P/E from our own universe vs. external index data; the ablation protocol
   that gates inclusion (design it *now* so the dataset carries what the
   ablation needs).
7. **Classification columns** — Sharadar sector/industry stability over time
   (do they get restated?); Fama-French industry mapping source (SIC→FF48).

## Reading list / sources

- [ ] Piotroski (2000), *Value Investing: The Use of Historical Financial
      Statement Information…* — F-score components.
- [ ] Altman (1968) + Altman (1983/2000 revisions) — Z, Z', Z'' variants.
- [ ] Ohlson (1980) — O-score.
- [ ] Beneish (1999) — M-score components (DSRI…TATA).
- [ ] Greenblatt, *The Little Book That Beats the Market* — Magic formula.
- [ ] Blitz & van Vliet — Conservative formula.
- [ ] Sharadar SF1 documentation — field definitions, dimensions, restatement
      semantics (pairs with V1).
- [ ] Fama-French industry classification mappings (SIC → FF12/FF48).

## Findings

*(Append dated notes per topic as research happens. Keep raw notes here;
distill conclusions into the ADR when a question closes.)*

## Exit criteria (research phase → M4 implementation)

- [ ] Every cross-family question above has an ADR or an explicit deferral.
- [ ] `docs/features.md` drafted: the canonical registry — one row per
      feature: name, family, formula, SF1/SEP inputs, history requirement,
      null policy, raw+rank column names.
- [ ] Per-family null-rate/coverage report runnable against real data (feeds
      V5 and the M4 exit criteria).
- [ ] Implementation order for `src/features/` decided (suggest: valuation →
      profitability → solvency → quality → technical → classification, with
      regime last behind its ablation gate).
