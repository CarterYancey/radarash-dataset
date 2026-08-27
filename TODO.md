# TODO — task register

Concrete development tasks. Design rationale lives in [PLAN.md](PLAN.md);
resolved questions get an ADR in `docs/decisions/` and are checked off here.

## Milestones (PLAN.md §-refs)

- [x] **M1 — Ingestion & identity.** Bulk download raw tables; permaticker
      mapping; universe table. Exit: universe counts per year plotted; V2, V3 done.
      *(Code done; V2/V3 writeups still open below.)*
- [ ] **M2 — Point-in-time verified.** V1 done; as-of join machinery working and
      tested against hand-checked examples.
      *(Machinery done: `src/features/base` T0 as-of join + lag matching,
      ADR 0004, fixture-tested. Remaining: the V1 EDGAR spot-check below.)*
- [ ] **M3 — Labels.** Forward returns with delisting handling; V4, V6 done.
      *(Code done: `src/labels/`, `docs/labels.md`, decisions 0001/0002.
      Remaining: V4, V6 below.)*
- [ ] **M4 — Features.** Feature families implemented with per-family tests and
      null-rate reports; V5 done.
      *(Code + real-data coverage pass done: `src/features/` implements the
      canonical registry, 1:1 enforced; null-rate reports =
      `sharadar-qa coverage`, committed. Remaining: V5 bank/insurer half below.)*
- [x] **M5 — Splits & assembly.** Purged/embargoed split tagging; `dataset_v1.0`
      produced end-to-end by one command; QA report published.
      *(Done 2026-07-18: `make all` real-data build + `make qa`; all four
      reports committed under `docs/research/reports/`, splits-diag findings
      recorded in `docs/research/splits.md`. Design: decisions 0010–0013;
      canonical docs `docs/splits.md` / `docs/dataset.md`.)*
- [x] **M6 — Inference dataset.** Label-free snapshot of the latest tradable
      cross-section for scoring with a trained model: `make inference` →
      `data/datasets/inference_{as_of}/`.
      *(Done 2026-07-22: `src/inference/` reuses the training feature +
      rank machinery verbatim; ADR 0014, `docs/dataset.md` §inference,
      `docs/manual.md` §9.)*

## Current state & next

All five milestones' code is shipped and `dataset_v1.0` builds end-to-end
from a raw ingest (`make all`); the 2026-07-18 real-data QA reports are
committed under `docs/research/reports/`. What remains in this repo:

- the **verification writeups** V1–V6 below (V7 done) — do these before
  trusting the data for real decisions;
- the remaining **open questions** below (microcap floor, snapshot
  frequency, min/max labels, regime features);
- maintenance: refresh ingests, rebuild, bump the dataset version.

Model training moves downstream to `value-ml-models`, guided by the
dataset user manual **[docs/manual.md](docs/manual.md)** — the registered
experiments (leakage-gap, ADR 0010; restated-variant ablation, ADR 0009;
era-identifiability probe) live on its task list, not here.

- [ ] **M4 — Features.** Add a meta feature tracking if a ticker was in
      the S&P 500 at snapshot date.
- [x] **M3 — Labels.** Tail-threshold labels (`cagr_ge_{15,20}`) and
      excess-vs-SPY threshold labels (`excess_ge_{5,10}`) — docs/labels.md;
      appear in the next labels build/dataset version.
- [ ] **Training-outcomes improvement backlog** — prioritized review in
      `docs/research/dataset-improvements.md` (2026-08-27): top items are
      the V1/V6/V4 verifications, a valuation-vs-own-history feature
      family, path-dependent labels (interim-low CAGR, max drawdown — the
      PLAN §6 stage-1 widening), Ohlson O-score + magic-formula composite
      + F-score component flags, and trend-family extensions (share count,
      margins). Each graduates via its own ADR.
- [x] **M4 — Features.** Trend & consistency family (long-horizon financial
      health: revenue/tangibles/OCF trends over 4/8/12/20-quarter windows,
      10-year dividend record) → `docs/decisions/0015`; dataset version
      1.1. *(Motivated by models surfacing stocks without a consistent
      financial history at inference.)*

## Verification tasks (do these before trusting anything)

Each produces a short writeup in `docs/decisions/`.

- [ ] **V1 — datekey semantics.** For ~10 known filings, confirm ARQ `datekey`
      matches the actual SEC filing date (check EDGAR) and that ARQ values match
      the original (pre-restatement) filing. Confirm `calendardate` vs.
      `reportperiod` behavior for off-cycle fiscal years. Also resolve the
      possible discrepancy noted in PLAN.md §2 (availability = first trading
      day strictly after `datekey`).
- [ ] **V2 — ticker reuse.** Find tickers in `TICKERS` mapping to multiple
      permatickers. Determine how SF1/SEP rows disambiguate (or don't). Define the
      resolution rule and test it. *(Raw material: `data/interim/ticker_reuse.parquet`;
      labels currently disambiguate by the mapping's price-coverage window.)*
- [ ] **V3 — survivorship depth.** Count in-universe stocks per year 1998→present,
      split by alive/delisted-later. Compare delisting counts around 2000–2002 and
      2008–2009 against published delisting statistics. Decide the earliest year
      the data is trustworthy (expect ~1998 hard floor; possibly later).
- [ ] **V4 — delisting returns.** Sample bankruptcies; inspect final SEP prices vs.
      known recoveries. Confirm ACTIONS/EVENTS give usable delist reasons (the
      labels module mines ACTIONS with a specificity priority — validate its
      vocabulary and coverage). Audit the decision-0002 convention against real cases.
- [ ] **V5 — financials identification.** Verify sector/SIC filters cleanly
      separate banks/insurers; check feature null rates by sector to confirm the
      exclusion decision (and confirm REIT features are usable).
      *(REIT half done via the coverage report, research §F10: REIT features
      usable except classified-balance-sheet inputs, ~84% NULL by
      construction. Bank/insurer separation still open.)*
- [ ] **V6 — benchmark.** Confirm SFP SPY adjusted close is total-return.
- [x] **V7 — DAILY point-in-time safety.** Ran via `sharadar-qa daily-pit`:
      DAILY was wholesale re-stamped (~2019) so "frozen" can't be certified,
      but values behave as-reported (85.9% ARQ-sided on restated rows, flat
      across years) and our `SEP.close × ARQ shares` construction replicates
      it to <0.1% median error. Writeup + decision (self-built canonical,
      DAILY cross-check only): `docs/decisions/0007` *(accepted)*; results
      in research §F12.

## Open questions (decide → ADR in docs/decisions/ → check off)

- [x] Acquisition delisting convention: **0%** from the final adjusted value,
      all delist reasons alike → `docs/decisions/0002`.
- [x] Price-sensitivity augmentation (PLAN.md §4): adopted in v1 as the three
      low/median/high touch-date snapshots → `docs/decisions/0001`.
- [x] Staleness cutoff for fundamentals at snapshot time: **no cutoff** —
      age is a feature, cutoffs are flag columns → `docs/decisions/0006`
      *(accepted; data in research §F11)*.
- [ ] Minimum liquidity/market-cap floor? (Microcaps dominate a total-market
      universe and may not be investable; consider a `min_marketcap` flag column
      rather than exclusion, so downstream can choose. The registry's
      `dollar_volume_3m`/`amihud_12m` columns carry the liquidity side;
      the flag-column decision itself is still open.)
- [x] Minimum-data filters for snapshots (PLAN.md §3): **no filing
      requirement** — `has_filing_183d`/`has_filing_365d` flags instead
      → folded into `docs/decisions/0006` *(accepted)*.
- [x] As-reported vs restated ("what they actually had") features:
      **as-reported (ARQ/ART) only** — deployment consistency, restatement
      timing embeds the label, and the reported-vs-actual gap is the
      quality family's signal → `docs/decisions/0009`. A restated-variant
      diagnostic ablation is registered there as a `value-ml-models` task
      (same purged splits; diagnostic only, never shipped).
- [x] Rank features within-date only, or within-date-and-sector?
      **Within (calendar quarter, snapshot_kind)**, `percent_rank`,
      thin-slice guard 20; sector variant for an allowlist
      → `docs/decisions/0008` *(accepted; research §F7 + §F10)*.
- [ ] Snapshot frequency: quarterly vs. monthly (monthly triples data volume and
      overlap; quarterly is the default until shown insufficient).
- [ ] Min/max terminal-price labels: keep, or drop after sensitivity analysis?
- [ ] Market-regime features (PLAN.md §5.6): include in v1 feature set (with
      ablation requirement) or defer?
- [x] Is the §7 purged/temporal methodology worth its data cost, or should a
      ticker-split validation set arbitrate splitting strategies? **Temporal
      seal stays the arbiter; `entity_holdout`/`random_kfold` tagged as
      diagnostic-only schemes; the open empirical questions became the
      `sharadar-qa splits-diag` report + a registered leakage-gap experiment
      in `value-ml-models`** → `docs/decisions/0010` *(accepted; real-data
      diagnostics run 2026-07-18, findings in `docs/research/splits.md`)*.
- [x] Uniqueness-weight definition details: **exact day-granularity average
      uniqueness per (permaticker, horizon), computed as a boundary-integral
      difference; the three low/median/high snapshots share one pool; NULL
      where the label is unobservable; unnormalized**
      → `docs/decisions/0012` *(accepted; cross-checked by the 2026-07-18
      `splits-diag` run — serial-overlap and twin-test findings in
      `docs/research/splits.md`)*.
