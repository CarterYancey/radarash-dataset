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
      null-rate reports; V5 done. **Next major task — research first**, see below.
- [ ] **M5 — Splits & assembly.** Purged/embargoed split tagging; `dataset_v1.0`
      produced end-to-end by one command; QA report published.

## Next major task: feature-set research (pre-M4)

Extensive research and planning before any feature code is written. The
workspace and findings live in **`docs/research/features.md`** — not here, not
in README/CLAUDE.md. Flow: research findings → ADRs in `docs/decisions/` →
canonical registry `docs/features.md` → implementation in `src/features/`.

*Status:* research phase complete pending final ADR review. Findings F1–F9
(2026-07-13) closed the theory questions; ADRs **0003/0004/0005** accepted.
`make qa` ran against a real ingest (reports committed in
`docs/research/reports/`, distilled into findings **F10–F12**), closing the
data-gated questions; ADRs **0006** (staleness), **0007** (market inputs /
V7), **0008** (rank representation) drafted in *proposed* status, and the
canonical registry **`docs/features.md`** is drafted. Review 0006–0008 →
flip to accepted → registry becomes canonical → implement `src/features/`
in the registry's build order.

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
      DAILY cross-check only): `docs/decisions/0007` *(proposed)*; results
      in research §F12.

## Open questions (decide → ADR in docs/decisions/ → check off)

- [x] Acquisition delisting convention: **0%** from the final adjusted value,
      all delist reasons alike → `docs/decisions/0002`.
- [x] Price-sensitivity augmentation (PLAN.md §4): adopted in v1 as the three
      low/median/high touch-date snapshots → `docs/decisions/0001`.
- [x] Staleness cutoff for fundamentals at snapshot time: **no cutoff** —
      age is a feature, cutoffs are flag columns → `docs/decisions/0006`
      *(proposed; data in research §F11)*.
- [ ] Minimum liquidity/market-cap floor? (Microcaps dominate a total-market
      universe and may not be investable; consider a `min_marketcap` flag column
      rather than exclusion, so downstream can choose. The registry's
      `dollar_volume_3m`/`amihud_12m` columns carry the liquidity side;
      the flag-column decision itself is still open.)
- [x] Minimum-data filters for snapshots (PLAN.md §3): **no filing
      requirement** — `has_filing_183d`/`has_filing_365d` flags instead
      → folded into `docs/decisions/0006` *(proposed)*.
- [x] Rank features within-date only, or within-date-and-sector?
      **Within (calendar quarter, snapshot_kind)**, `percent_rank`,
      thin-slice guard 20; sector variant for an allowlist
      → `docs/decisions/0008` *(proposed; research §F7 + §F10)*.
- [ ] Snapshot frequency: quarterly vs. monthly (monthly triples data volume and
      overlap; quarterly is the default until shown insufficient).
- [ ] Min/max terminal-price labels: keep, or drop after sensitivity analysis?
- [ ] Market-regime features (PLAN.md §5.6): include in v1 feature set (with
      ablation requirement) or defer?
- [ ] Uniqueness-weight definition details: exact overlap counting for the
      `sample_weight` column (de Prado ch. 4), and whether the three
      low/median/high snapshots share a weight pool with each other.
