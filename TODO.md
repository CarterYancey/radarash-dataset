# TODO — task register

Concrete development tasks. Design rationale lives in [PLAN.md](PLAN.md);
resolved questions get an ADR in `docs/decisions/` and are checked off here.

## Milestones (PLAN.md §-refs)

- [x] **M1 — Ingestion & identity.** Bulk download raw tables; permaticker
      mapping; universe table. Exit: universe counts per year plotted; V2, V3 done.
      *(Code done; V2/V3 writeups still open below.)*
- [ ] **M2 — Point-in-time verified.** V1 done; as-of join machinery working and
      tested against hand-checked examples.
- [ ] **M3 — Labels.** Forward returns with delisting handling; V4, V6 done.
      *(Code done: `src/labels/`, `docs/labels.md`, decisions 0001/0002.
      Remaining: V4, V6 below.)*
- [ ] **M4 — Features.** Feature families implemented with per-family tests and
      null-rate reports; V5 done.
      *(Code done: `src/features/` implements the canonical registry in its
      build order, registry-validated columns, hand-checked fixture tests;
      null-rate reports = `sharadar-qa coverage`. Ranks and the two
      assembly-stage composites land at M5 assembly. Remaining: V5 below.)*
- [ ] **M5 — Splits & assembly.** Purged/embargoed split tagging; `dataset_v1.0`
      produced end-to-end by one command; QA report published.

## Next major task: M5 splits & assembly

M4 implementation shipped (2026-07-15): `src/features/` implements the
canonical registry (`docs/features.md` ↔ `registry.py`, 1:1 enforced by
tests and by the writer) in the build order — foundations `base` (T0 as-of
join + reportperiod lag matching, ADR 0004) and `market` (self-built
marketcap/EV, ADR 0007), then the eight families, each writing
`data/interim/features/{family}.parquet` on the labels key. Staleness is
metadata + flags, never a filter (ADR 0006). Run with `make features`;
re-run `make qa` after the first real-data build (per-year/per-tier
null-rate check, ADR 0004 burn-in).

Real-data `make features` + coverage pass done (2026-07-15): reports
committed under `docs/research/reports/` — 515,731 median snapshots,
97% with an ARQ filing, fresh-within-365d 95.7%, worst field-level null
rate 8% (`workingcapital`, the classified-balance-sheet REIT story from
§F10); staleness×labels gradient monotone, consistent with ADR 0006.
Nothing in the pass contradicts the registry or the staleness policy.

Still open in M4: **V5** (bank/insurer separation half).

M5 split tagging shipped (2026-07-15): `src/splits/` tags per-horizon
purged + embargoed roles for the sealed `holdout` and expanding
`walkforward` schemes (calendar-year folds, median-only test rows, tags
never filters) → `splits.parquet` + frozen fold manifest
`split_folds.parquet`. Design: `docs/decisions/0011`; canonical
definitions: `docs/splits.md`. Run `make splits` after the first
real-data build and sanity-check the logged fold calendar.

Split-methodology debate resolved 2026-07-17 (ADR 0010, PLAN §7.7):
the empirical questions became `sharadar-qa splits-diag` (implemented,
fixture-tested; workspace `docs/research/splits.md`), and the tagging
emits the diagnostic-only `entity_holdout` / `random_kfold` schemes
(mechanics in ADR 0011 §7) for the leakage-gap experiment registered as a
`value-ml-models` task. Still pending: run `splits-diag` on real data
after `make features` and record findings in the workspace.

M5 assembly shipped (2026-07-18): `src/assemble/` (`sharadar-assemble`,
`make dataset`) joins families × labels on the snapshot key
(registry-validated), computes registry-driven ranks/sector-ranks
(ADR 0008), the assembly-stage composites `mohanram_g7` +
`conservative_score` (ADR 0013 — four new quality-family component
features), and per-horizon uniqueness weights `sample_weight_{H}y`
(ADR 0012, resolving the open question below), then writes the immutable
`data/datasets/dataset_v1.0/` (dataset + split files + manifest).
Canonical doc: `docs/dataset.md`; from an existing ingest, `make all` is
the one-command end-to-end build. Remaining for the M5 exit: run the
real-data build (`make all`), sanity-check the logged fold calendar and
effective-sample-size sums, re-run `make qa` (including the pending
`splits-diag` real-data pass), and publish the QA report.

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
      in `value-ml-models`** → `docs/decisions/0010` *(accepted; workspace
      `docs/research/splits.md` — real-data run still pending)*.
- [x] Uniqueness-weight definition details: **exact day-granularity average
      uniqueness per (permaticker, horizon), computed as a boundary-integral
      difference; the three low/median/high snapshots share one pool; NULL
      where the label is unobservable; unnormalized**
      → `docs/decisions/0012` *(accepted; `splits-diag`'s real-data label
      decomposition and twin test remain the empirical cross-check)*.
