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

Status 2026-07-13: first full research pass done (findings F1–F9 below);
ADRs [0003](../decisions/0003-composite-scores-in-house.md) (composite
scores), [0004](../decisions/0004-fundamental-history-depth.md) (history
depth), [0005](../decisions/0005-feature-set-scope-v1.md) (v1 scope)
**accepted**.

Status 2026-07-14: the `make qa` reports ran against a real ingest
(committed under [reports/](reports/)) — findings F10–F12 below close the
data-gated (⛁) questions. Three more ADRs drafted in **proposed** status:
[0006](../decisions/0006-staleness-policy.md) (staleness),
[0007](../decisions/0007-market-inputs-daily-pit.md) (market inputs / V7),
[0008](../decisions/0008-rank-representation.md) (rank representation).
The canonical registry **`docs/features.md`** is drafted from the workspace
tables — the research-phase exit criteria are met once 0006–0008 are
accepted.

Status 2026-07-14 (close-out): ADRs 0006–0008 reviewed and **accepted**;
`docs/features.md` is **canonical**. All exit criteria below are met — the
research phase is closed and M4 implementation of `src/features/` proceeds
in the registry's build order. This workspace is now a historical record;
new findings during implementation go to new ADRs, not here.

## Research questions

### Cross-family (answer once, apply everywhere)

- [x] **SF1 field inventory.** → F1. Documentation-level inventory done; every
      candidate formula is computable from SF1 except the noted gaps.
      Null rates by year/sector measured on real data → F10 (feeds V5).
- [x] **History depth.** → F4, ADR 0004 (accepted). Depth tiers 0/4/8/12
      quarters + 12m/36m price windows; lag resolution by `reportperiod`
      window, not positional LAG. Universe survival per tier per year
      measured → F10: tiers are viable (T1 ≥ 86% from 2000, T3 ≥ ~80% from
      2003).
- [x] **Staleness interaction.** → F11, ADR 0006 (accepted). The gradient is
      real and steep (delist-within-1y rate 7.9% fresh → 29.4% at >365d
      stale): staleness is signal, not noise. No feature-level cutoff; age
      stored as a feature; cutoffs only as assembly-time filter flags.
- [x] **Rank representation details.** → F7, ADR 0008 (accepted): rank within
      (calendar quarter, snapshot_kind); sector-relative variant for a small
      allowlist (F10's sector sizes support it — smallest real sector ≈ 60
      snapshots/quarter, above the thin-slice guard).
- [x] **Winsorization/clipping.** → F7.3. Store raw untouched; ranks are the
      outlier defense. No winsorized/z-scored duplicates in v1.
- [x] **Negative-denominator semantics.** → F6. Prefer **yield orientation**
      (E/P, B/P, EBIT/EV…) so the denominator is price/EV, which is positive
      by construction for price (EV gets a flag); negative *numerators* are
      meaningful and kept. Where a fundamental denominator is unavoidable
      (ROE with negative equity, debt/EBITDA with EBITDA ≤ 0): NULL, plus the
      information preserved in dedicated flag features. One rule everywhere.
- [x] **Point-in-time market inputs.** → F8.1, F12, ADR 0007 (accepted). V7
      ran: DAILY was wholesale re-stamped (~2019), so "frozen as computed"
      cannot be certified, but its values behave as-reported (85.9%
      ARQ-sided on restated rows, flat across years) and our own
      `SEP.close × ARQ shares` construction replicates DAILY.marketcap to
      <0.1% median error. Decision: self-built construction is canonical;
      DAILY is a cross-check only.

### Per family (PLAN.md §5 numbering)

1. **Valuation** — → F2, F6. Composites: proposed ADR 0003 (compute in-house,
   store components *and* canonical composite).
2. **Solvency/distress** — → F2.2. Z'' is the mixed-universe variant to
   feature; original Z retained as a composite for comparability. O-score:
   components yes, composite deferred (GNP-deflator term, F2.2).
3. **Earnings quality (M-score)** — → F2.3. Compute the 8 indices from ART
   pairs lagged one fiscal year; fiscal alignment rule in F4.2.
4. **Profitability & growth** — → F3.2, F3.3. ROIC via `invcapavg`
   (Sharadar-computed) plus our own EBIT/(NWC+net PP&E) for the Magic-formula
   convention; growth via reportperiod-matched YoY.
5. **Technical** — → F5. Small set confirmed: 12-2 momentum, 6m return, 1m
   reversal, 12m/36m vol, 52w-high distance, log marketcap, dollar volume.
6. **Market-regime (candidate)** — stays deferred; ablation protocol must be
   designed before inclusion (unchanged from PLAN.md §5.6; not in ADR 0005).
7. **Classification columns** — → F8.3. `TICKERS.famaindustry` already ships
   Fama-French-48-style industry; sector/industry are **current-state, not
   historical** (⛁ verify restatement behavior; acceptable for slow-moving
   membership, documented caveat).

## Findings

### F1 — SF1 field inventory (2026-07-13)

Sources: Nasdaq Data Link [SF1 database page](https://data.nasdaq.com/databases/SF1)
(150 indicators, ~14k–16k companies, up to 28 years ≈ 1998 floor — consistent
with PLAN.md §2 and V3's expectation), Sharadar indicator descriptions
(`SHARADAR/INDICATORS` table — ingest it, it is tiny and gives us the
canonical field dictionary as data; added to F9 checklist).

Fields the candidate formulas need, grouped. Names below are from the public
SF1 dictionary; **the first coding task of M4 is to verify this list against
`SHARADAR/INDICATORS`** (⛁).

| Group | SF1 fields |
|---|---|
| Income statement | `revenue`, `cor`, `gp`, `sgna`, `rnd`, `opex`, `opinc`, `ebit`, `ebitda`, `intexp`, `taxexp`, `ebt`, `netinc`, `netinccmn`, `prefdivis`, `depamor`, `sbcomp`, `eps`, `epsdil`, `shareswa`, `shareswadil`, `sharesbas` |
| Balance sheet | `assets`, `assetsc`, `assetsnc`, `cashneq`, `investments`, `investmentsc`, `receivables`, `inventory`, `ppnenet`, `intangibles`, `tangibles`, `taxassets`, `liabilities`, `liabilitiesc`, `liabilitiesnc`, `payables`, `debt`, `debtc`, `debtnc`, `deferredrev`, `taxliabilities`, `equity`, `retearn`, `workingcapital`, `accoci` |
| Cash flow | `ncfo`, `ncfi`, `ncff`, `capex`, `fcf`, `ncfdiv`, `ncfcommon`, `ncfdebt`, `ncfbus`, `ncfinv`, `ncfx`, `ncf` |
| Sharadar-computed ratios (per-row) | `roa`, `roe`, `roic`, `ros`, `grossmargin`, `netmargin`, `ebitdamargin`, `assetturnover`, `currentratio`, `de`, `divyield`, `payoutratio`, `bvps`, `tbvps`, `sps`, `fcfps`, `invcap`, `invcapavg`, `equityavg`, `assetsavg` |
| Row-level market fields (⚠ see F8.1) | `marketcap`, `ev`, `pe`, `pb`, `ps`, `evebit`, `evebitda`, `price` |
| Keys/meta | `ticker`, `dimension`, `datekey`, `reportperiod`, `calendardate`, `lastupdated`, `fxusd`, `sharefactor` |

**Known gaps** (fields formulas want but SF1 lacks):

- **Advertising expense** — folded into `sgna`. Kills 1 of 8 Mohanram
  G-score signals (F2.4): we compute a 7-signal variant, documented.
- **Income taxes payable** (separate from `taxliabilities`) — pushes Sloan
  accruals to the cash-flow-statement method, which is the better-regarded
  variant anyway (F3.4).
- **GNP price deflator** — Ohlson O-score's size term deflates assets by
  GNP price level; needs an external macro series. Components stored,
  composite deferred (F2.2).
- **Funds from operations** (Ohlson's FFO/TL) — proxy with `ncfo` or
  `netinc + depamor`; pick one, document it (registry).

Dimension policy (restates PLAN.md §2): **ARQ** for point-in-time quarterly
levels/flows, **ART** for trailing-twelve-month flows (annual-style formulas
want a year of flow — use ART, not ARY: same as-reported discipline, fresher
by up to 3 quarters). `MR*` never. Availability = first trading day strictly
after `datekey` (V1 verifies).

### F2 — Composite formula scores (2026-07-13)

*Addresses outstanding question 2 (vendor vs. self-computed vs. components
vs. custom score). Conclusion → proposed ADR 0003.*

#### F2.0 Vendor survey (option 2.1)

- **GuruFocus** advertises F-score and friends with
  [history to 1978](https://www.gurufocus.com/data-api/stocks/valuations) via
  API. But their scores are computed from *standardized, restated*
  financials — the numbers as known today, not as reported then. That
  violates our core invariant (no lookahead through restatements). They also
  don't publish the per-signal as-of discipline (when did each input become
  "known"?), coverage of *delisted* stocks in deep history is unverifiable
  from outside, and bulk redistribution/ML licensing is its own contract.
- **WRDS / Compustat Point-in-Time (snapshot)** would be the academically
  correct vendor source, but it is a separate institutional subscription and
  a second data contract to reconcile against Sharadar identities — a
  project on its own for data we can derive.
- **Intrinio and similar** document *how to compute* F-score from their
  fundamentals ([example](https://intrinio.com/blog/how-to-use-python-to-calculate-the-piotroski-f-score-with-intrinios-api)),
  i.e. even vendors treat it as a derived quantity.

**Verdict: no vendor.** Every input to every candidate score is already in
SF1 as-reported. A vendor score would add a second identity system, a second
PIT audit burden, licensing cost/terms, and would still be *less*
trustworthy than our own ARQ/ART arithmetic, because we can unit-test ours
against hand-checked filings (the repo's whole testing style).

#### F2.1 Components vs. composite (options 2.2 / 2.3 / 2.4)

Do **both** 2.2 and 2.3 — they are nearly free once either is built:

- **Components are the primary features.** For tree models a composite is a
  hand-made decision stump ensemble: F-score's "+1 if ΔROA > 0" throws away
  the magnitude, and the published weights (Altman's 1.2/1.4/3.3/…, Beneish's
  coefficients) were fit on 1960s–80s samples. Trees can relearn thresholds
  and interactions from the raw ratios — giving them pre-thresholded sums
  only destroys information.
- **Composites are still worth storing** because they cost one SQL
  expression over components we already have, they are the interpretable
  baselines every results discussion will want ("did the model beat plain
  F-score?"), they serve as cross-checks against published summary
  statistics (a sanity test on our plumbing), and low-depth trees can use
  them as high-quality single splits.
- **Custom re-weighted score (option 2.4) is explicitly out of scope for the
  dataset**: learning weights over the components *is the downstream model's
  job* (`value-ml-models`). Baking a fitted score into the dataset would
  smuggle model training into data construction — and any fitting would have
  to respect the splits, which don't exist at feature-build time. If a
  hand-tuned score is ever wanted, it's a v2 feature computed from stored
  components, no pipeline change.

This resolves the "too many features" worry about 2.3 the right way: the
component count is bounded (~30 across all composites, most shared — ΔROA
serves F-score, profitability trends, and O-score's ΔNI cousin), and
question-1's answer (F6.1: dataset is wide, selection happens at model time)
removes the pressure entirely.

#### F2.2 Formula-by-formula computability on SF1

Notation: `Δx` = YoY change (fiscal-aligned, F4.2); `x₋₁` = value one fiscal
year prior; TTM figures from ART, point-in-time levels from ARQ.

**Piotroski F-score (2000)** — 9 binary signals, all computable, depth tier
T1 (needs prior fiscal year):

| # | Signal | SF1 expression |
|---|---|---|
| 1 | ROA > 0 | `netinc_ttm / assetsavg > 0` |
| 2 | CFO > 0 | `ncfo_ttm > 0` |
| 3 | ΔROA > 0 | vs. prior-year TTM |
| 4 | Accruals: CFO > NI | `ncfo_ttm > netinc_ttm` |
| 5 | Δleverage < 0 | `debtnc/assetsavg` down YoY |
| 6 | Δcurrent ratio > 0 | `assetsc/liabilitiesc` up YoY |
| 7 | No new equity issued | `ncfcommon_ttm ≤ 0` (cash-flow convention; share-count fallback `Δsharesbas ≤ ~2%` — registry documents the choice) |
| 8 | Δgross margin > 0 | `gp/revenue` up YoY |
| 9 | Δasset turnover > 0 | `revenue_ttm/assetsavg` up YoY |

**Altman Z (1968) / Z' (1983) / Z'' (1995)** — depth tier T0 (single row):
shared component set `workingcapital/assets`, `retearn/assets`,
`ebit_ttm/assets`, `marketcap/liabilities` (Z) or `equity/liabilities`
(Z'/Z''), `revenue_ttm/assets`. Z'' (6.56·WC/TA + 3.26·RE/TA + 6.72·EBIT/TA
+ 1.05·BVE/TL, no sales term) is the variant designed for
non-manufacturers — the right *featured* composite for our mixed universe;
store classic Z too for literature comparability. Components stored once,
three composites are three expressions.

**Ohlson O-score (1980)** — components all computable T1:
`log(assets)` (nominal — see gap note), `liabilities/assets`,
`workingcapital/assets`, `liabilitiesc/assetsc`, `netinc_ttm/assets`,
`ffo_proxy/liabilities`, dummies `liabilities > assets`,
`netinc_ttm < 0 AND netinc_ttm₋₁ < 0`, and scaled earnings change
`(NI − NI₋₁)/(|NI| + |NI₋₁|)`. **Composite deferred**: the size term wants
GNP-deflated assets (external series), and the composite adds nothing over
components for trees. Zmijewski + Z'' cover the "one distress number" need.

**Zmijewski (1984)** — trivially computable T0/T1:
`−4.336 − 4.513·NI/TA + 5.679·TL/TA + 0.004·CA/CL`. All three inputs
already stored as components elsewhere; composite is free.

**Beneish M-score (1999)** — 8 indices from consecutive fiscal years (ART
pair, tier T1). All computable:

| Index | Inputs |
|---|---|
| DSRI | `receivables/revenue` vs. prior year |
| GMI | prior GM / current GM |
| AQI | `1 − (assetsc + ppnenet)/assets` ratio YoY |
| SGI | `revenue/revenue₋₁` |
| DEPI | depreciation rate `depamor/(depamor + ppnenet)` YoY |
| SGAI | `sgna/revenue` YoY |
| LVGI | `(debt + liabilitiesc)/assets` YoY |
| TATA | `(netinc_ttm − ncfo_ttm)/assets` (cash-flow method) |

Composite: `−4.84 + 0.92·DSRI + 0.528·GMI + 0.404·AQI + 0.892·SGI +
0.115·DEPI − 0.172·SGAI + 4.679·TATA − 0.327·LVGI`. Beneish designed it on
annual data → ART pairs, not ARQ pairs.

**Mohanram G-score (2005)** — 7 of 8 signals computable (advertising gap,
F1); signals are *industry-median-relative* (uses `famaindustry`), so this
family computes at assembly time where the cross-section exists (F7). The
two variability signals (earnings, sales-growth variability vs. industry)
want 3+ years of history → tier T3, lowest priority; ship the 5
level-signals first, variability signals behind the coverage report.

**Magic formula (Greenblatt)** — earnings yield `ebit_ttm/ev` + return on
capital `ebit_ttm/(workingcapital + ppnenet)` (Greenblatt's tangible-capital
convention; Sharadar's `roic`/`invcapavg` stored alongside as the
conventional variant). T0.

**Conservative formula (Blitz & van Vliet 2018)** — 36m volatility (low),
12-1 momentum (high), net payout yield `(ncfdiv_neg + share buybacks −
issuance)/marketcap` ≈ `−(ncfdiv + ncfcommon)_ttm/marketcap` (sign
conventions to pin down in tests). Components land in the technical family
(vol, momentum) + valuation (NPY); composite is a rank-sum, computable at
assembly. Price tier P36.

#### F2.3 Cross-checks to build into tests

Published base rates make good fixture assertions: F-score distribution is
roughly bell-shaped over 0–9 with mass at 4–7; M-score flags ~5–10% of
non-financial firms at the −1.78 cutoff; Z'' distress zone < 1.1. Synthetic
fixtures should include one hand-computed company per composite (the ZIG
style from `tests/test_labels_cli.py`).

### F3 — Additional fundamental candidates (2026-07-13)

*Addresses outstanding question 4.1. Conclusion → proposed ADR 0005.*

Beyond PLAN §5's list, these have strong literature support, are cheap given
the machinery the core families already require, and fit the deep-value
thesis:

- **F3.1 Gross profitability (Novy-Marx 2013):** `gp_ttm/assets`. One
  column, the single best-documented quality factor; also G-score input.
- **F3.2 Sloan accruals (1996):** cash-flow method
  `(netinc_ttm − ncfo_ttm)/assetsavg` (the balance-sheet method needs taxes
  payable — gap, and the CF method is the modern standard). Already TATA's
  numerator. Earnings-quality family.
- **F3.3 Asset growth (Cooper–Gulen–Schill 2008):** `Δassets/assets₋₁` YoY.
  Strong negative predictor; T1.
- **F3.4 Net operating assets (Hirshleifer et al. 2004):**
  `((assets − cashneq − investments) − (liabilities − debt))/assets₋₁`.
  Balance-sheet bloat; T1.
- **F3.5 External financing (Bradshaw–Richardson–Sloan 2006):**
  `(ncfcommon_ttm + ncfdebt_ttm)/assetsavg`; issuance predicts poor returns.
  Complements F-score signal 7 with magnitude.
- **F3.6 Shareholder yield / net payout yield:**
  `−(ncfdiv_ttm + ncfcommon_ttm)/marketcap` — dividends + net buybacks;
  Conservative-formula input; supersedes plain dividend yield (keep both,
  `divyield` is free).
- **F3.7 Graham deep-value markers:** NCAV = `assetsc − liabilities` vs.
  marketcap (net-net discount), and **negative enterprise value** flag +
  `ev/marketcap`. Directly on-thesis; near-zero cost; expect heavy nulls in
  large caps and that's fine.
- **F3.8 Balance-sheet dilution:** `Δsharesbas` YoY (split-adjusted via
  `sharefactor` — verify semantics ⛁). Complements F3.5 from the share-count
  side.

Deliberately **excluded** from v1: O'Shaughnessy-style mega-composites
(redundant given components + ranks), anything needing segment data,
estimates, or ownership tables (different Sharadar products), and macro
series (regime family, still gated).

### F4 — History depth & the splits question (2026-07-13)

*Addresses outstanding question 3. Conclusion → proposed ADR 0004.*

#### F4.1 Depth tiers

Standardize every feature's history requirement to one of:

| Tier | Requirement | Used by |
|---|---|---|
| T0 | current filing only | levels, valuation, Z components |
| T1 | +4 quarters (1 fiscal year back) | YoY: F-score, M-score, growth, asset growth, NOA |
| T2 | +8 quarters | 2y trend slopes (margin trend, turnover trend) |
| T3 | +12 quarters | 3y CAGRs, G-score variability signals |
| P12 | 252 trading days | momentum, 12m vol, 52w high |
| P36 | 756 trading days | 36m vol (Conservative formula) |

Cap fundamental depth at **T3 (3 years)** in v1. Rationale: the data floor
is ~1998 (V3), so a 5-year fundamental lookback burns the sample to 2003
*and* systematically nulls young/newly-listed firms — precisely the
small/neglected names a deep-value model cares about. 5-year-history
features (user's "5y CAGR labels from 5y features" hypothesis) are testable
later by adding T5 columns to a new dataset version; the registry design
(F8) makes that additive, not a rewrite.

**Multiple depths side by side, yes** — e.g. `revenue_growth_1y` (T1) and
`revenue_growth_3y_cagr` (T3) are separate columns with separate null
policies. The dataset stays label-agnostic: we do *not* build per-horizon
feature sets. Whether 5y-CAGR labels are better predicted by longer-history
features is a *model-selection* question the wide dataset lets downstream
answer; deciding it here would bake in a hypothesis.

#### F4.2 Fiscal alignment rule ("consecutive" is a trap)

Positional `LAG(4)` over ARQ rows breaks on amended filings, fiscal-year
changes, and gaps. Define lags by **reportperiod arithmetic**: the YoY
partner of a row is the same-permaticker ARQ/ART row whose `reportperiod`
falls in `[reportperiod − 395d, reportperiod − 335d]` (tolerance for 52/53-
week and shifted fiscal calendars), taking the row with the latest `datekey`
that is still `≤ snapshot_date` (PIT: use the version of history known at
snapshot time; V1's amendment-semantics check feeds this). No partner in the
window ⇒ the feature is NULL. `calendardate` is *not* used for lag matching
(it is allowed only for cross-sectional grouping, PLAN §2).

#### F4.3 Effect on splits: none on the rules, two documented consequences

Leakage flows **forward through labels**, not backward through features. The
purge/embargo condition (`snapshot_date + horizon + embargo < test_start`,
PLAN §7.2) is about a training row's *label window* reaching into the test
period. A trailing feature window extends a row's dependence *backward* in
time. A test row whose features use training-period data is not leakage —
it is exactly what deployment looks like (the model will always see fresh
features computed over the recent past). De Prado's embargo already exists
to absorb residual *serial correlation* in features across the boundary;
trailing windows change its magnitude marginally, not its mechanism, and
the embargo is parameterized if evidence ever demands more.

So: **history depth does not change the split rules.** It has two real
consequences to document and QA instead:

1. **Burn-in.** With a ~1998 floor, T1 features exist from ~1999, T3 from
   ~2001, P36 from ~2001. The earliest walk-forward fold must start after
   the deepest tier *it uses* is populated — a property the QA report
   asserts (per-year null rates by tier), not a split-rule change.
2. **Age-correlated missingness.** History requirements null out young
   firms. Rows are **never dropped** for missing history (nulls stay null,
   PLAN §5) — dropping would tilt the universe toward seasoned survivors,
   survivorship bias through the back door. Trees route around nulls; the
   null-rate report keeps us honest about how much of the universe each
   tier covers.

#### F4.4 Staleness interaction (framing; decision needs data ⛁)

The staleness cutoff (TODO open question) and history tiers interact: a firm
whose latest filing is 11 months old at snapshot has *stale* T0 features and
likely a *broken* T1 chain. Late filing is itself distress signal (the
delinquent-filer literature), which argues for: keep the row, keep the stale
features, add **`fundamentals_age_days`** as a first-class feature, and let
the staleness cutoff be an assembly-time *filter column* (like the proposed
`min_marketcap` flag) rather than silent row deletion. Decide 6-vs-12 with
the coverage report in hand.

### F5 — Technical features (2026-07-13)

*Addresses outstanding question 4.2. Conclusion → proposed ADR 0005.*

Yes — a small set, all from `SEP.closeadj` (already label plumbing), all
strictly backward-looking from `snapshot_date`:

| Feature | Definition | Tier |
|---|---|---|
| `mom_12_2` | total return over t−252…t−21 (skip most recent month — standard momentum, avoids reversal contamination) | P12 |
| `ret_6m` | total return t−126…t | P12 |
| `ret_1m` | total return t−21…t (short-term reversal) | P12 |
| `vol_12m` | σ of daily log returns, annualized, ≥ ~200 obs required | P12 |
| `vol_36m` | same over 756d (Conservative formula input) | P36 |
| `dist_52w_high` | `closeadj / max(closeadj over t−252…t) − 1` (adjusted series, so splits don't fake a crash; George–Hwang anchor effect) | P12 |
| `log_marketcap` | `ln(marketcap)` at snapshot (source per F8.1) | T0 |
| `dollar_volume_3m` | median daily `close × volume`, t−63…t | P12 |
| `amihud_12m` | mean `|ret| / dollar_volume` (illiquidity; also informs the liquidity-floor open question as a *column*, not a filter) | P12 |

Momentum/reversal/low-vol are the best-replicated anomalies in existence and
they interact with value (value+momentum works better than either); the
Conservative formula *requires* vol and momentum anyway. These also give the
trees "cheap **and** stabilizing" vs. "cheap **and** collapsing" — a
distinction fundamentals alone cannot see. All computed off the same
adjusted-price series as labels, so no new PIT machinery. Betas and anything
needing intraday/microstructure data: out.

Interaction with decision 0001: technical features are exactly where the
three snapshot kinds differ (fundamentals are shared within the quarter);
`dist_52w_high`, `ret_1m` etc. will mechanically differ low-vs-high — that
is the margin-of-safety gradient working as designed, worth a QA glance.

### F6 — How many features; representation rules (2026-07-13)

*Addresses outstanding question 1.*

**Agreed: the dataset is wide; selection is model-work.** Storage is
parquet-cheap and trees are robust to irrelevant columns; the real marginal
cost of a feature is **QA surface** (a null-rate entry, a test, a registry
row) — so the gate for inclusion is "has literature or thesis support and a
testable definition," not a count budget. The candidate registry below lands
at **~95 raw features** (≈35 shared components, ~8 composites, ~15
valuation, ~12 profitability/growth, ~10 solvency, ~10 quality, ~9
technical, ~4 classification) → ~190 columns with ranks. Guardrails:

- Every feature enters through the registry (F8.2) — no drive-by columns.
- Redundancy is fine (ROA and ROE both stay) but *near-duplicates* by
  construction (same numerator, `assets` vs `assetsavg` denominator) pick
  one convention and note the alternative in the registry.
- **Yield orientation** for valuation: store E/P not P/E, B/M not P/B,
  EBIT/EV not EV/EBIT. Yields are defined for negative numerators (a
  loss-maker has meaningful negative E/P; its P/E is garbage), monotone
  ("more = cheaper"), and rank cleanly. Multiples can be derived downstream;
  we don't store both.
- Negative *fundamental* denominators (equity < 0 for ROE, EBITDA ≤ 0 for
  debt/EBITDA): NULL + the fact captured once in flag features
  (`negative_equity`, `negative_ebitda`, `negative_ev`) rather than a signed
  convention that poisons ranks. One rule across all families.

### F7 — Rank representation under decision-0001 snapshot dates (2026-07-13)

**New problem found during this pass.** PLAN §5 says "cross-sectional rank
within snapshot date," but decision 0001 makes snapshot dates *touch dates*
— scattered across the quarter per stock. The cross-section at any exact
date is a thin, non-random slice of the universe (whoever touched their
low/median/high that day), so within-exact-date percentiles would be noisy
and kind-biased.

Options considered:

1. **Rank within (calendar quarter, snapshot_kind).** Cross-section = whole
   universe, comparing like with like (everyone at *their* quarter-low).
   Fundamentals-based features are fine (shared within quarter);
   price-based features are asynchronous by up to ~13 weeks. Cheap.
2. Rank against a full-universe feature matrix recomputed at every distinct
   touch date — correct, but explodes compute (~63 cross-sections/quarter ×
   universe × features).
3. Rank all features against a fixed quarter-end reference cross-section —
   introduces a mild lookahead for snapshots earlier in the quarter
   (quarter-end fundamentals of *other* firms may postdate the snapshot).
   Rejected on PIT grounds.

**Proposal: option 1**, with ranks computed at **assembly time** (they need
the full cross-section, so they cannot live inside per-family modules —
architecture consequence in F8.2). Percentile = `percent_rank` over non-null
values; NULL raw ⇒ NULL rank; cross-sections under ~20 non-null values ⇒
NULL rank (thin-slice guard, threshold in registry config).

**F7.2 Sector-relative ranks:** within-(quarter, kind, sector) for an
allowlist only (valuation yields, gross profitability, accruals — the
features with known industry structure), not all features (×3 column
blowup, and G-score already carries industry-relative signals). TODO's
open question narrows to "which allowlist," decidable from the null-rate
report (small sectors → thin slices).

**F7.3 Winsorization:** none. Raw stored untouched (analysis needs true
values), ranks are the model-facing representation and are outlier-immune.
Adding winsorized variants later is an additive registry change.

### F8 — Architecture: registry-driven, swap-friendly (2026-07-13)

*Addresses "easy to change both features and labels for future versions."*

#### F8.1 Market inputs (⛁ verification gate)

Valuation needs snapshot-date `marketcap`/`ev`. Two candidate sources:

- **DAILY** (`marketcap, ev, pe, pb, ps` daily): convenient, but PIT safety
  is **unverified** — if Nasdaq recomputes historical rows after
  restatements, it is poisoned for us. **V7 (new verification task):**
  compare DAILY rows against hand-computed `SEP.close × ARQ shares` for
  filings that were later restated; check `lastupdated` behavior.
- **Own construction** (PIT-safe by definition): `marketcap = SEP.close ×
  sharesbas(ARQ, latest datekey ≤ date) × sharefactor`; `ev = marketcap +
  debt − cashneq` from the same ARQ row. SF1's own per-row `marketcap/ev/
  pe/...` are tied to `datekey`-era prices, not our snapshot dates — usable
  as cross-checks only.

Plan: build the own-construction path regardless (tests need it); adopt
DAILY only if V7 passes, as an optimization.

#### F8.2 Module & artifact layout

```
src/features/
  base.py         as-of fundamentals resolution (the M2 join machinery):
                  latest ARQ/ART per permaticker with datekey < snapshot_date
                  (strictly-after rule), + reportperiod lag matching (F4.2)
  market.py       snapshot-date marketcap/EV (F8.1) + flags
  valuation.py    yields, deep-value markers          → features_valuation.parquet
  profitability.py                                     → features_profitability.parquet
  growth.py                                            → features_growth.parquet
  solvency.py     Z/O/Zmijewski components+composites → features_solvency.parquet
  quality.py      F/M/G components+composites, accruals, NOA, ext. financing
  technical.py    price-window features from SEP       → features_technical.parquet
  classification.py sector/industry/famaindustry/scale → features_classification.parquet
  registry.py     declarative FeatureSpec table (name, family, inputs,
                  depth tier, null rule, formula ref, added_in_version)
  cli.py          sharadar-features [--family ...]
```

Same conventions as `src/identity`/`src/labels`: `build_*_view(con)` pure
SQL, `write_*_table(con, dir)` → ZSTD parquet + count dict, thin argparse
CLI, exit 2 with a hint when inputs are missing.

Key contracts that make features/labels swappable:

- **One key everywhere:** every family parquet is keyed
  `(permaticker, snapshot_date, snapshot_kind)` — same key as
  `labels.parquet`. Families never read each other's outputs (shared
  components live in the family that owns them; assembly joins).
- **Ranks live in assembly (M5), not families** (F7): families emit raw
  values only; the assembly step joins families × labels × splits, computes
  ranks/sector-ranks per registry flags, and writes
  `data/datasets/dataset_vX.Y/`.
- **The registry is code and doc:** `registry.py` is the machine-readable
  truth (assembly validates that emitted columns == registry exactly);
  `docs/features.md` is generated-or-mirrored from it, one row per feature.
  Changing the feature set = edit one family + its registry rows; changing
  labels = re-run labels; either way **assembly re-composes without
  recomputing the other side** — that is the version story:
  `dataset_vX.Y = manifest(feature family versions, labels version, splits
  config)`, written into the dataset directory.
- `added_in_version` / `removed_in_version` on FeatureSpec so dataset
  versions are diffable from the registry alone.

#### F8.3 Classification columns

`TICKERS` ships `sector`/`industry` (Sharadar scheme), `sicsector`/
`sicindustry`, **`famaindustry`** (FF-48-style — no SIC→FF mapping table
needed, one less moving part), `scalemarketcap`/`scalerevenue` buckets.
Caveat to document: TICKERS is **current-state** — a reclassified firm's
history gets the new label (⛁ check `lastupdated`/history behavior; if
material, fallback is SIC-code era mapping, but industry membership is slow
enough that v1 accepts the caveat with a note). Encode as strings; trees
downstream handle categoricals; no one-hot in the dataset.

### F9 — Coverage / null-rate report (the ⛁ unblocker)

First M4 implementation artifact, *before* any feature family: a small
`src/qa/` job over a real ingest producing, per year × sector × depth tier:
universe count, rows with a usable T0 filing, T1/T2/T3 chain survival,
P12/P36 price-window coverage, and null rates for the ~30 highest-value SF1
fields. This single report unblocks every ⛁ above (staleness choice, tier
viability, G-score variability signals, sector-rank allowlist, financials
exclusion V5) and doubles as the V5 deliverable. Runnable on synthetic
fixtures for tests, meaningful on real data.

**Implemented 2026-07-13** as `src/qa/` / **`sharadar-qa`** (`make qa`),
three subcommands: `coverage` (this report), `staleness` (§F4.4's
staleness × label-bias table), `daily-pit` (V7's three diagnostics,
including the ARQ-vs-MRQ discrimination test on restated rows). Committable
markdown/CSV outputs land in `docs/research/reports/`; run against a real
ingest and commit them, then findings graduate here. Note the SF1→
permaticker resolution rule the QA jobs establish (candidate rule for
`src/features/base.py`): unique tickers resolve unconditionally; reused
tickers resolve by price-window containment with grace margins
(pre-listing 540d for S-1-era filings, post-delisting 366d), nearest
window on overlap.

### F10 — Coverage results from real data (2026-07-14)

`sharadar-qa coverage` over the full ingest ([reports/coverage.md](reports/coverage.md)):
**515,731** median-kind snapshots 1997–2026, 97.0% with an ARQ filing.

- **Data floor confirmed.** 1997 is junk (39% filing coverage — pre-floor
  partial data; V3 should formally set the floor at 1998). Burn-in matches
  ADR 0004's prediction: T1 32% in 1998 → 76% in 1999 → ≥86% from 2000;
  T2 ≥88% from 2003; T3 ≥79% from 2002. **Earliest fully-tiered
  walk-forward folds: ~2001–2003** depending on the deepest tier used.
- **Steady state is healthy**: fresh-within-365d ≈ 96%, T1 ≈ 90%,
  T3 ≈ 80–86% — the tier design costs little of the universe.
- **The 2021–22 dip is real and informative**: T1 drops to 80%/89%, T3 to
  ~68–70% — the IPO/SPAC vintage has no filing history. This is the
  age-correlated missingness ADR 0004 predicted; rows stay, NULLs stay.
- **Null rates are formula-driven, not data-quality-driven.** Overall ≤4%
  for everything except the classified-balance-sheet trio
  (`workingcapital`/`assetsc`/`liabilitiesc` ≈ 8%), which decomposes by
  sector: **Real Estate ≈ 84% null** (REITs don't file classified balance
  sheets) and residual Financial Services ≈ 55%. Consequence for the
  registry: current-ratio/quick-ratio/NCAV/Altman-Z(WC term) are
  structurally NULL for most REITs — expected, documented, and exactly what
  the NULL policy is for. Also notable: `retearn` is 20% null in Energy and
  14% in Utilities (partnership/MLP structures), degrading Z composites
  there while the components remain individually usable. This closes the
  REIT half of V5 (features usable except classified-BS ones); the
  bank/insurer-separation half of V5 remains.
- Sector cross-sections are large enough for sector ranks everywhere
  (smallest real sector, residual Financial Services: ~6.9k snapshots ≈ 60
  per quarter); the 717-row "(none)" sector gets NULL sector-ranks.

### F11 — Staleness × labels results (2026-07-14)

`sharadar-qa staleness` ([reports/staleness.md](reports/staleness.md)):
86.3% of snapshots have a filing ≤93 days old; 8.8% at 94–183d; only 0.67%
at 184–365d; 1.3% >365d; 3.0% no filing at all.

The distress gradient is steep and monotone where it matters:
delist-within-1y rate **7.9% (0–93d) → 8.9% (94–183d) → 24.8% (184–365d) →
29.4% (>365d)**; median 1y forward CAGR +1.4% fresh vs. ≈ −10% for stale
buckets; the >365d bucket's *mean* CAGR of +230% against a −7% median is
the classic distressed lottery-ticket right tail. The no-filing bucket
(median −11.2%) is a different population — mostly young listings before
their first filing — not just late filers.

**Conclusion (→ proposed ADR 0006):** staleness is one of the strongest
distress signals in the dataset. Dropping stale rows would delete exactly
the rows a deep-value model must learn to avoid (or exploit), and a
183d-vs-365d cutoff debate is moot at 0.67%/1.3% row shares. Therefore: no
feature-level staleness cutoff at all — features compute from the freshest
filing however old; `fundamentals_age_days` becomes a first-class feature;
`has_filing_183d`/`has_filing_365d` flags let downstream apply any cutoff
as a filter. This also resolves TODO's "minimum-data filter" question in
the same stroke: no row exclusion, flags instead.

### F12 — V7 results: DAILY point-in-time safety (2026-07-14)

`sharadar-qa daily-pit` ([reports/daily_pit.md](reports/daily_pit.md)):

1. **Freshness:** `lastupdated − date` declines linearly from ~7,600 days
   (1998) to ~0 (2020+) — the signature of a **wholesale re-stamp/rebuild
   around 2019**. Historical DAILY rows are therefore *not* certifiably
   frozen-as-computed; whatever they contain was (re)written years after
   the fact.
2. **Marketcap replication:** our `SEP.close × ARQ sharesbas × sharefactor`
   construction matches DAILY.marketcap (unit scale $1M) with ≤0.02% median
   error and ~98% of rows within 1%, every year. This simultaneously
   validates our own construction and shows DAILY's share source is
   as-reported.
3. **The sharp test:** on 428k restated ticker-days, DAILY.pb sides with
   the **as-reported** equity 85.9% of the time — and the rate is *flat*
   across years (84–89%, including 2026 rows that cannot have been
   restated-and-recomputed yet). If the 2019 rebuild had used restated
   data, old years would skew toward MRQ and recent years toward ARQ; the
   flatness says the residual ~14% is a systematic definition/timing
   mismatch (equity variant, price timing), not progressive recomputation.

**Verdict (→ proposed ADR 0007):** DAILY behaves point-in-time in its
values but cannot be certified frozen, and our own construction replicates
it essentially exactly — so the self-built SEP × ARQ path is the canonical
market-input source (PIT-safe *by construction*, unit-testable), and DAILY
is kept as a cross-check in QA only. No feature reads DAILY.

## Reading list / sources

- [x] Piotroski (2000) — F-score components → F2.2.
- [x] Altman (1968; 1983/1995 revisions) — Z, Z', Z'' → F2.2.
- [x] Ohlson (1980) — O-score → F2.2 (composite deferred).
- [x] Beneish (1999) — M-score indices → F2.2.
- [x] Greenblatt — Magic formula → F2.2.
- [x] Blitz & van Vliet (2018) — Conservative formula → F2.2.
- [x] Zmijewski (1984) → F2.2.
- [x] Mohanram (2005) — G-score → F2.2 (7-signal variant).
- [x] Sloan (1996); Hirshleifer et al. (2004); Cooper–Gulen–Schill (2008);
      Bradshaw–Richardson–Sloan (2006); Novy-Marx (2013) → F3.
- [ ] Sharadar SF1 documentation / `SHARADAR/INDICATORS` — field
      definitions, restatement semantics (pairs with V1; ⛁ needs API access).
- [x] Fama-French industry mapping — moot: `TICKERS.famaindustry` ships it
      (F8.3), caveat noted.

Web sources consulted 2026-07-13:
[SF1 database page](https://data.nasdaq.com/databases/SF1),
[Sharadar publisher page](https://data.nasdaq.com/publishers/SHARADAR),
[QuantRocket Sharadar overview](https://www.quantrocket.com/sharadar/),
[GuruFocus data API](https://www.gurufocus.com/data-api/stocks/valuations),
[Intrinio F-score how-to](https://intrinio.com/blog/how-to-use-python-to-calculate-the-piotroski-f-score-with-intrinios-api).

## Exit criteria (research phase → M4 implementation)

- [x] Every cross-family question above has an ADR or an explicit deferral.
      *(0003/0004/0005 accepted 2026-07-13; 0006/0007/0008 from F10–F12
      accepted 2026-07-14; market-regime stays explicitly deferred per
      PLAN §5.6.)*
- [x] `docs/features.md` drafted: the canonical registry — one row per
      feature: name, family, formula, SF1/SEP inputs, history requirement,
      null policy, rank treatment. *(Canonical as of 2026-07-14 with
      0006–0008 accepted.)*
- [x] Per-family null-rate/coverage report runnable against real data (F9
      implemented as `sharadar-qa`; real-data results in F10–F12 and
      `reports/`).
- [x] Implementation order for `src/features/` decided (registry §Build
      order): base/market → valuation → profitability/growth → solvency →
      quality → technical → classification → assembly-stage (ranks, G-score,
      Conservative score); regime deferred behind its ablation gate.
