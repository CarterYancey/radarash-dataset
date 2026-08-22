# 0015 — Trend & consistency family: quarterly windows to 20q, annual dividend record

Date: 2026-08-22
Status: accepted

## Context

Models trained on `dataset_v1.0` backtest well but, on the inference
dataset, surface stocks without a consistent financial history — the kind a
manual screen (is revenue growing steadily? book value? operating cash
flow? has the dividend been paid without interruption?) would reject. The
v1.0 registry describes growth *rates* (1y/3y, ADR 0004) but almost nothing
about the *consistency* of the whole visible history: two firms with
identical `revenue_growth_3y` can have wildly different paths.

Exploration of generic time-series shape analysis (multi-model curve
fitting with AICc selection, KMeans shape clustering) was considered and
rejected for the dataset itself: model-selection tournaments are unstable
at 5–20 points and produce categorical outputs that flip between adjacent
snapshots; cluster centroids fit on the panel leak cross-sectional future
information; and raw fit parameters are scale-dependent. The one curve
that matters for fundamentals is the exponential (steady compounding),
and fitting it is OLS on log values — available in DuckDB as
`regr_slope`/`regr_r2`, deterministic, scale-invariant, pure SQL.

ADR 0004 capped fundamental depth at T3 (3 fiscal years) for v1 and
explicitly reserved deeper tiers as "additive registry changes for a
future dataset version". This ADR is that change.

## Decision

1. **New feature family `trend`** ("Trend & consistency" in
   docs/features.md), built from a new foundation view (`fund_history`,
   `src/features/history.py`) holding, per snapshot, the point-in-time
   visible history of a few series at **quarterly spacing** up to 20
   quarters back.

2. **Quarterly windows, matched to the label horizons.** Each trend
   feature is computed over the last **4, 8, 12, or 20 quarters**
   (~1y/2y/3y/5y — aligned with the 1y/2y/3y/5y label horizons so
   horizon-vs-window dependence is testable downstream). Multiple windows
   coexist as separate columns (same reasoning as ADR 0004 §2); shorter
   windows populate further back in the sample and for younger firms.

3. **Series and statistics.** For `revenue` (ART TTM), `tangibles`
   (ARQ level, tangible book value) and `ncfo` (ART TTM, operating cash
   flow), per window `w`:
   - `{s}_trend_{w}q` — `regr_slope(ln(value), time_in_years)`: the
     annualized log growth rate (the exponential fit's rate parameter).
   - `{s}_consistency_{w}q` — `regr_r2` of the same fit: how well steady
     compounding describes the path (1 = textbook compounder). A constant
     series scores 1 (consistent, zero trend) — by design.
   - `{s}_up_frac_{w}q` — fraction of available consecutive-quarter pairs
     that increased (scale-free monotonicity).
   Additionally `ocf_positive_frac_{w}q` — fraction of observations with
   `ncfo > 0` — because log-trend features are undefined exactly when OCF
   goes negative, which is itself the signal.
   `fund_history_quarters` counts the observations present in the 20q
   window: short history is *the* "no consistent record" case, exposed as
   a feature rather than hidden (ADR 0004 §5 — never row-drop).

4. **TTM at quarterly spacing is intentional.** Consecutive TTM values
   share three quarters, so quarterly-sampled TTM series are smoothed and
   autocorrelated; `consistency` values are therefore systematically
   higher than an annual-sampled equivalent. That is acceptable: features
   are cross-sectionally comparable, seasonality-free (a TTM increase
   means the latest quarter beat its year-ago quarter), and deterministic.
   These are features, not inference statistics.

5. **Matching rule** (extends ADR 0004 §3): the lag-q observation is the
   filing whose `reportperiod` is within ±30 days of
   `fund_reportperiod − q·91.3125`, taking the latest
   `datekey < snapshot_date` version (`<=` for the inference dataset,
   ADR 0014). Off-grid filings (fiscal-year changes) degrade to NULL,
   never mis-pair. No partner ⇒ bucket missing.

6. **Null rules.** `trend`/`consistency` are NULL unless the window holds
   at least **{4q: 3, 8q: 5, 12q: 7, 20q: 11}** observations (more than
   half) and every present observation is **> 0** (no silent filtering of
   the log's domain — a window containing a non-positive value has no
   log-trend). `up_frac` needs min−1 pairs; `ocf_positive_frac` the same
   min counts. Snapshots with no T0 filing get NULL everywhere (counts
   included). Missing stays NULL; nothing is imputed or dropped.

7. **Dividend record is annual, not windowed by quarter.** Payout
   schedules vary; the question is "paid, every year, without cuts" —
   so dividend features sample the TTM cash dividend (`−ncfdiv`) at
   **fiscal-year anniversaries** (`fund_reportperiod − y·365.25` ± 30
   days, y = 0…9; same version-of-history rule), over a **10-year**
   window — long enough to separate "cut in 2009 and 2020, otherwise
   40 years of payments" from "has only existed for 3 years":
   - `div_years_paid_10y` — years with a dividend paid (`−ncfdiv > 0`);
   - `div_streak_10y` — consecutive paying years ending at the current
     filing (a missing or unknown year breaks the streak);
   - `div_cuts_10y` — consecutive-year pairs where the prior year paid
     and the current year's TTM dividend fell below **0.8×** the prior
     (omission included; the 20% tolerance ignores timing noise and small
     trims, catches real cuts);
   - `div_history_years_10y` — annual observations present (the
     denominator context; distinguishes gaps from youth).
   The three counters together encode exactly the asymmetry wanted: an
   old payer with two crisis cuts scores high `years_paid`, small `cuts`,
   moderate `streak`; a 3-year-old payer scores low `years_paid` and low
   `history`.

8. **Depth tiers extended** (amends ADR 0004 §1): **T5** (+20 quarters)
   and **T10** (+10 fiscal years) join the menu. Windowed features carry
   the tier of their full window (4q→T1, 8q→T2, 12q→T3, 20q→T5;
   dividends T10) but degrade to partial-window values per the min-count
   rules above rather than nulling outright — the tier states the depth
   *used*, the min-count rule states what's *required*.

9. **Splits unchanged** (ADR 0004 §4 verbatim): leakage flows forward
   through label windows; trailing feature windows of any depth don't
   change the purge/embargo condition.

## Consequences

- `FAMILIES` gains `trend` (build order: after `growth`); assembly, QA
  and the inference dataset pick it up via the registry with no further
  changes. Every numeric gets a `_rank` column at assembly (ADR 0008).
- The assembled output is **dataset v1.1** (`added_in_version: "1.1"`;
  `sharadar-assemble` default bumped). v1.0 directories are immutable and
  unaffected.
- Burn-in: 20q features populate fully from ~2003, dividend 10y from
  ~2008 (data floor ~1998); shorter windows and the count features
  populate much earlier. Age-correlated missingness is measured by the
  QA coverage report, as before.
- Firm age/seasonedness is partly encoded (deliberately — it is real,
  point-in-time-visible information); downstream models can now prefer
  "old and boring" explicitly instead of the inference screen doing it
  by hand.
- Shape clustering and multi-model curve classification stay out of the
  dataset; if wanted, they are downstream (`value-ml-models`) or
  `docs/research/` material.
