# Feature-set research

Status: planning baseline, 2026-07-13. Discussion here does not approve a
feature. Accepted policies are in ADRs; implementable definitions live in
[the canonical registry](../features.md).

## Executive conclusions

1. Build a broad but curated library, not every mechanically possible ratio or
   window. For v1, target roughly **80–150 economically distinct base numeric
   columns**, before rank mirrors and provenance. This is a planning range, not
   a quota.
2. Compute features from project point-in-time fundamentals and market data. Do
   not buy precomputed composite scores for the production pipeline.
3. Store meaningful components of published scores. Add a small number of
   exact, documented composites as reference features. Do not create a custom
   learned score in dataset v1.
4. Use one feature table for every label horizon. Encode justified current,
   1-year, 3-year, and selected 5-year histories; do not make definitions depend
   on label horizon.
5. Backward-looking history does not require extra purging. It creates warm-up
   and missingness; forward label overlap determines purge/embargo boundaries.
6. Include a compact technical family: momentum, reversal, volatility,
   drawdown, high proximity, size, and liquidity—not a large indicator zoo.

## What “enough features” means

“Include everything relevant” is unsafe if it means every field crossed with
every denominator, transform, and lookback. That multiplies redundant
hypotheses, missingness, maintenance, and selection overfit. The practical
constraint is the number of independent eras and regimes, not raw row count.

A candidate enters the registry only with:

- an economic hypothesis and original or authoritative evidence;
- an exact point-in-time formula and input lineage;
- a justified history window rather than all available windows;
- defined denominator, sign, null, infinity, and unit behavior;
- known sector/accounting limitations;
- a coverage, hand-calculation, and sensitivity-check plan;
- a reason it is not merely a duplicate.

The 80–150 target leaves room for breadth while remaining reviewable. Ranked
versions are not new economic hypotheses. Never fill the target with arbitrary
variants.

## Composite formulas

### Piotroski F-score

Piotroski combines nine binary signals covering profitability,
leverage/liquidity, and operating efficiency: ROA, change in ROA, cash flow
from operations, accrual quality, change in margin, change in turnover, change
in leverage, change in liquidity, and equity issuance. The paper does not claim
these are optimal and also examines individual signals. It was designed for
high-book-to-market firms, not as a universal continuous quality measure.
[Piotroski (2000)](https://econpapers.repec.org/article/blajoares/v_3a38_3ay_3a2000_3ai_3a_3ap_3a1-41.htm)

Recommendation: calculate all nine components, retain continuous inputs where
meaningful, and optionally calculate the exact 0–9 score as a reference. Nine
components are not excessive. They preserve magnitude and expose missingness.

### Beneish M-score

The original eight-variable model uses DSRI, GMI, AQI, SGI, DEPI, SGAI, LVGI,
and TATA; most are current-to-prior-year indices. It was developed as a
manipulation screen, and unusual business conditions can produce signals. It
should not be relabeled generic “quality.” [Beneish
(1999)](https://www.calctopia.com/papers/beneish1999.pdf)

Recommendation: include interpretable indices and accrual input after coverage
testing. Store the score only if every input and coefficient convention is
reproduced exactly. Any missing input makes the composite null.

### Other published scores

- **Ohlson O-score:** the conditional-logit bankruptcy model uses nine
  variables and emphasizes information timeliness. Historical coefficients,
  GNP scaling, and its bankruptcy setting make the composite less portable
  than its leverage, liquidity, profitability, and loss-history inputs.
  [Ohlson (1980)](https://econpapers.repec.org/article/blajoares/v_3a18_3ay_3a1980_3ai_3a1_3ap_3a109-131.htm)
- **Zmijewski score:** preserve profitability, leverage, and liquidity inputs;
  treat the legacy probit as a reference, not a timeless probability. The paper
  focuses on sampling and estimation bias in distress models. [Zmijewski
  (1984)](https://www.jstor.org/stable/2490859)
- **Mohanram G-score:** profitability, cash flow, stability, and
  R&D/capital/advertising intensity are candidates, but the score was designed
  for low-book-to-market growth stocks. [Mohanram](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=403180)
- **Sloan accruals:** include accrual and cash-versus-accrual earnings
  components. Their different persistence is precisely what an opaque score
  conceals. [Sloan (1996)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2598)
- **Novy-Marx gross profitability:** gross profits/assets is compact,
  well-motivated, and complementary to book-to-market. [Novy-Marx
  (2013)](https://www.nber.org/papers/w15940)

### Vendor versus self-calculation

GuruFocus publishes current and historical F-score data, but public material
does not establish restatement-vintage semantics, dead-security coverage,
identity mapping, or the reproducible point-in-time contract needed here. Its
values may support spot checks, not production. [GuruFocus](https://www.gurufocus.com/term/fscore)

Institutional vendors do document point-in-time fundamentals: FactSet offers
active/inactive North American firms from February 1999; S&P describes
Compustat point-in-time history from 1987 and Capital IQ as-reported history
from 1993; LSEG advertises U.S. history back to 1989.
[FactSet](https://www.factset.com/marketplace/catalog/product/factset-fundamentals-point-in-time),
[S&P Global](https://www.spglobal.com/market-intelligence/en/solutions/products/fundamental-data),
[LSEG](https://www.lseg.com/en/data-analytics/financial-data/company-data/fundamentals-data/point-in-time-fundamentals)

Those sources could support future validation, but now add licensing, entity,
and definition reconciliation without solving a theory problem. For v1,
calculate from Sharadar SF1 ARQ/ART and audit `datekey`. Nasdaq describes
Sharadar as company-filing data with over twenty years of history. [Nasdaq Data
Link](https://www.nasdaq.com/solutions/data/nasdaq-data-link)

## History depth

History is part of a feature's economic definition:

| Window | Intended use | Policy |
|---|---|---|
| Current / TTM | valuation, balance-sheet state, profitability | baseline |
| 1 year / prior fiscal year | published YoY signals and changes | baseline |
| 3 years | trend and stability with useful early-era coverage | selective |
| 5 years | durable growth/stability hypotheses | selective; never global requirement |
| Daily 1, 6, 12 months | reversal, momentum, risk, liquidity | compact technical family |

Published formulas retain their original window. Other multi-year features
should usually expose slope, CAGR, variability, or positive-year count rather
than every lag. Crossing every metric with 1/3/5-year windows adds correlated
columns without independent hypotheses.

All label horizons consume the same snapshot feature row. Downstream models may
select different subsets, but changing a label horizon must not change feature
semantics. Pre-training-period observations may support a training feature if
they were public before that row's snapshot.

Long history creates warm-up, early-era nulls, and serial dependence. It does
**not** create lookahead or extend the purge window. Keep insufficient-history
values null rather than dropping universe rows. Fit imputation, scaling,
selection, and learned combinations within training folds. Forward labels
still determine purging and embargo.

## Proposed v1 families

- **Valuation:** book, earnings, sales, OCF, FCF, EBITDA, and EBIT yields;
  enterprise-value variants; shareholder yield.
- **Profitability/efficiency:** gross profit/assets, ROA, guarded ROE, ROIC,
  margins, asset and capital turnover.
- **Accruals/quality:** total and working-capital accruals, cash conversion,
  Sloan and Beneish components.
- **Growth/stability:** sales, gross profit, operating income, earnings, cash
  flow, and asset growth; 3-year trend/variability; selected 5-year stability.
- **Solvency/distress:** leverage, liquidity, working capital, interest
  coverage, loss history, Ohlson/Zmijewski/Altman components.
- **Capital allocation/investment:** asset growth, capex and R&D intensity, net
  debt/equity issuance, repurchases, dividends, retained earnings.
- **Published references:** Piotroski first; others only after exact-input,
  coverage, and domain checks.
- **Technical/liquidity:** 1-month reversal, 6–1 and 12–1 momentum, 12-month
  volatility/downside volatility, maximum drawdown, 52-week-high distance, log
  market cap, dollar volume, turnover, and continuity. [Jegadeesh and Titman
  (1993)](https://doi.org/10.1111/j.1540-6261.1993.tb04702.x)
- **Context:** sector/industry and snapshot metadata. Market-wide regime
  features remain optional because they can behave as date fingerprints.

## Representation and numerical rules

Plan to store raw values and, when meaningful, snapshot-date percentile ranks.
Sector-relative ranks are candidates, not defaults. Prefer yields over
large-magnitude price multiples when they express the same hypothesis. Never
store infinity. Zero and negative denominators need feature-specific rules;
never replace them automatically with epsilon. Missing inputs remain null
unless zero is an economic fact in the source.

Winsorization must not overwrite raw values. If research supports clipping,
emit a named transform with fixed rules or do it fold-locally downstream.

## Validation gate before implementation

1. Inventory exact SF1/DAILY/SEP fields, units, dimensions, and availability.
2. Verify representative `datekey` values against filing dates.
3. Hand-calculate normal, loss-making, negative-equity, acquisition, and sparse
   history cases.
4. Measure coverage by year, sector, market-cap tier, and listing status.
5. Inspect denominator failures, outliers, and alternate definitions.
6. Quantify redundancy without consulting the sealed holdout.
7. Approve exact definitions in the registry, then implement.

## Implementation architecture (design only)

Features and labels are independently versioned products joined to a stable
snapshot spine. A dataset manifest identifies:

```text
snapshot_spec + universe_spec + feature_set_id + label_set_id + split_spec
```

Each family should be a deterministic DuckDB transform emitting keys
`(permaticker, snapshot_date, snapshot_kind)` plus lineage. The registry owns
stable IDs, formulas, dependencies, lookbacks, applicability, and versions.
Family outputs can be cached as Parquet and assembled by registry selection.
Changing labels must not recompute features, and vice versa.

Avoid an unrestricted formula language. Metadata configures selection and
validation; reviewed SQL/Python modules implement formulas. Learned composites
belong in the model repository or a future fold-aware stage, because fitting
them globally leaks validation and test information.

## Remaining evidence work

These policies are decision-ready; individual formulas are not. Exact SF1
mapping, denominator conventions, coverage results, and hand checks remain the
gate between the proposed registry and feature code.
