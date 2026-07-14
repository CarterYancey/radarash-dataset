# Dataset design and research plan

This document holds conceptual and theoretical planning. It explains why the
pipeline is designed as it is and how unresolved research should be evaluated.
Concrete work belongs in [TODO.md](TODO.md); accepted answers belong in
`docs/decisions/`.

## Dataset objective

Produce a wide, versioned table:

```text
(permaticker, snapshot_date, features..., labels..., split_tags...)
```

It should support tree-based classification and ranking models without encoding
one model's training choices into the data. Raw values, ranks, continuous
outcomes, binary labels, and split metadata remain available for downstream
experiments.

The principal risks are not computational. They are:

1. feature lookahead from restated or not-yet-filed fundamentals;
2. survivorship bias in universe membership and forward outcomes;
3. ticker identity errors;
4. temporal leakage from overlapping label windows;
5. unstable or economically meaningless feature definitions;
6. overstated sample size caused by correlated securities and windows.

## Point-in-time information model

### Fundamentals

SF1 ARQ and ART are the allowed as-reported dimensions. MRQ, MRT, and MRY can
incorporate later restatements and are excluded from model features.

`datekey` is the provisional availability date because it represents the SEC
filing date. A filing becomes usable on the first trading day strictly after
`datekey`. `reportperiod` describes the fiscal period and `calendardate`
supports alignment; neither determines availability.

Every fundamentals join should expose enough lineage to audit:

- source dimension;
- report period;
- filing date;
- snapshot date;
- age at snapshot;
- selected source row.

A staleness cutoff prevents very old filings from masquerading as current
information. The cutoff must be selected through coverage analysis and recorded
as a decision rather than hidden inside a query.

### Prices and daily metrics

SEP and DAILY values are usable only on or after their observation dates.
Features using the snapshot day's closing price assume the decision is made
after that close; if a different execution assumption is adopted later, all
price-derived features and labels must move together.

## Entity and universe model

`permaticker` is permanent identity. Exact current ticker mappings are used
only to resolve source rows. Ambiguous or unmatched symbols remain explicit
audit records.

The baseline universe consists of domestic common stock and domestic common
stock primary classes, including delisted securities and REITs. Banks and
insurers are excluded because the first feature families rely on industrial
balance-sheet relationships that are not comparable for financial firms.

Universe filters should remain structural. Investability choices such as
liquidity or market-cap floors are better represented as columns so downstream
experiments can select thresholds without reconstructing the source universe.

## Snapshot and label model

Each stock-quarter contributes low, observed discrete-median, and high adjusted
close snapshots. These rows deliberately expose entry-price sensitivity while
holding the quarter's available fundamentals largely constant.

Labels retain continuous CAGRs and derived binary thresholds at 1, 2, 3, and 5
years. The primary endpoint averages the final 21 trading observations to reduce
single-day endpoint noise; point-to-point and terminal min/max variants measure
sensitivity to that choice.

Delisted rows are never removed. Their final positive adjusted close is carried
unchanged through the horizon. The model therefore retains the entry-to-final
price outcome and assumes zero return after the final trading date. See
`docs/labels.md` and the corresponding decision record for the exact contract.

## Feature research program

Feature development begins with research, not formula transcription. Every
candidate must establish economic meaning, point-in-time computability,
cross-sectional comparability, source coverage, and numerical behavior.

Research and source evidence live in `docs/research/features.md`; the sole
canonical registry is `docs/features.md`. A formula is not implementation-ready
until its registry status is accepted and any material convention has a
decision record. ADRs 0004–0006 resolve scope, composite-score, history, and
versioning policy.

### Evaluation criteria

For each feature, determine:

1. **Economic hypothesis** — what condition or behavior should the value
   represent, and why might it predict the chosen outcomes?
2. **Formula** — exact numerator, denominator, sign, units, period basis, and
   annualization.
3. **Availability** — required source rows and the latest date each input became
   public.
4. **Comparability** — sectors, accounting regimes, or business models for which
   the calculation is invalid or structurally different.
5. **History requirement** — current filing only, year-over-year comparison,
   trailing series, or daily window.
6. **Numerical policy** — null, zero, negative denominator, infinity, extreme
   values, and whether transformations are monotonic.
7. **Coverage** — availability by year, sector, snapshot kind, and market-cap
   tier.
8. **Stability** — sensitivity to alternate definitions and restatements.
9. **Redundancy** — correlation and conceptual overlap with accepted features.
10. **Validation evidence** — hand calculations, literature, source-field
    documentation, and empirical checks.

### Candidate families

These are research areas, not an approved feature list. The maintained list and
review status are in `docs/features.md`:

- valuation: earnings, book, sales, cash-flow, and enterprise-value yields;
- solvency and distress: working capital, retained earnings, leverage,
  interest coverage, Altman- and Ohlson-style components;
- earnings quality: accruals and Beneish-style changes;
- profitability: margins, returns on assets/equity/invested capital;
- growth and trend: year-over-year changes and multi-period consistency;
- capital allocation: issuance, repurchases, dividends, and reinvestment;
- operating efficiency: turnover and working-capital relationships;
- technical context: trailing return, volatility, drawdown, and distance from
  highs;
- size and liquidity: market capitalization, dollar volume, and trading
  continuity;
- optional regime context: broad-market valuation, trend, and volatility.

Composite scores are decomposed first. Exact published composites may be
retained as reference features when complete and reproducible. Custom learned
scores belong downstream inside temporal training folds. See ADR 0005.

### Representation

The default representation for every accepted numeric feature is:

- raw value;
- percentile rank within snapshot date.

Raw values preserve interpretability and allow alternate preprocessing.
Cross-sectional ranks reduce unit sensitivity, extreme-value influence, and
valuation-regime drift. Sector-relative ranks remain an empirical question:
they may improve comparability but can erase meaningful sector allocation
signals.

Null is the normal representation of unavailable or invalid information.
Imputation is a downstream model decision unless a feature's definition itself
implies a value. Infinity is never a valid stored feature value.

### Research sequence

The preferred sequence is:

1. source-field inventory and point-in-time lineage;
2. family-level literature and formula comparison;
3. hand calculations on representative companies;
4. prototype DuckDB expressions;
5. coverage and distribution reports;
6. alternate-definition sensitivity analysis;
7. atomic specification in `docs/features.md`, registry review, and acceptance;
8. implementation with fixtures and full-data QA.

Do not use label correlation on the final holdout to select features. Early
univariate outcome analysis belongs only inside temporally valid development
folds and should be treated as exploratory evidence, not proof.

## Temporal validation and split design

Quarterly observations are highly dependent. Adjacent snapshots for one stock
share most of their forward path, and securities on the same date share market
outcomes. Row count therefore greatly overstates effective sample size.

All evaluation is temporal. Entity-disjoint random splits do not solve shared
market-path leakage.

For a test period beginning at `test_start`, a training row is eligible for
horizon H only when:

```text
snapshot_date + H + embargo < test_start
```

Rows whose label windows cross the boundary are purged. A parameterized embargo
adds distance from the boundary. Eligibility is horizon-specific so short
horizons do not discard as much recent training data as long horizons.

Overlapping rows inside the training set remain available but receive
horizon-specific uniqueness weights. The sum of weights is a more honest view
of sample size than the number of rows.

Planned schemes:

- expanding-window walk-forward folds for model selection;
- a sealed, most-recent holdout for final evaluation;
- schema support for later combinatorial purged cross-validation.

Required conceptual references before implementation include López de Prado,
*Advances in Financial Machine Learning*, chapters 4, 7, 11, and 12, and
Bailey et al., “The Probability of Backtest Overfitting.” Reading notes should
live under `docs/research/splits/`, not in this file.

## Dataset assembly

The final assembly stage joins:

1. snapshot identity and entry-price context;
2. point-in-time fundamentals and accepted features;
3. continuous and binary labels;
4. horizon-specific split and weight metadata;
5. provenance and dataset version.

Final dataset versions are immutable. A manifest should record input artifact
hashes, schemas, source snapshot dates, code version, feature registry version,
and all material conventions.

## Quality strategy

QA is part of each stage, not a final cleanup pass. Expected reports include:

- identifier resolution and ambiguity;
- universe counts and survivorship depth;
- source freshness and filing staleness;
- feature coverage by year and sector;
- null, infinity, and outlier rates;
- label completeness by horizon;
- delisting reason and endpoint invariants;
- point-to-point versus smoothed label flips;
- split purging counts and effective sample size.

Any QA result that changes a modeling rule should lead to a decision record.
