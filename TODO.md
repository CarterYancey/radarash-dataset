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

*Status:* first full research pass done (findings F1–F9 in the workspace);
ADRs **0003** (composite scores in-house), **0004** (history depth),
**0005** (v1 scope) drafted in *proposed* status — review, then flip to
accepted and draft `docs/features.md` from the workspace tables. Remaining
research questions are data-gated: run the coverage report (workspace §F9)
against a real ingest.

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
- [ ] **V6 — benchmark.** Confirm SFP SPY adjusted close is total-return.
- [ ] **V7 — DAILY point-in-time safety.** Are historical DAILY rows
      (marketcap, ev, pe, pb, ps) frozen as-computed, or recomputed after
      restatements? Compare against hand-computed `SEP.close × ARQ shares`
      for later-restated filings; check `lastupdated`. Gates whether M4
      valuation uses DAILY or the self-built PIT construction
      (`docs/research/features.md` §F8.1).

## Open questions (decide → ADR in docs/decisions/ → check off)

- [x] Acquisition delisting convention: **0%** from the final adjusted value,
      all delist reasons alike → `docs/decisions/0002`.
- [x] Price-sensitivity augmentation (PLAN.md §4): adopted in v1 as the three
      low/median/high touch-date snapshots → `docs/decisions/0001`.
- [ ] Staleness cutoff for fundamentals at snapshot time (6 vs. 12 months).
- [ ] Minimum liquidity/market-cap floor? (Microcaps dominate a total-market
      universe and may not be investable; consider a `min_marketcap` flag column
      rather than exclusion, so downstream can choose.)
- [ ] Minimum-data filters for snapshots (PLAN.md §3): price on snapshot date
      exists by construction; require an ARQ filing in the trailing 12 months?
- [ ] Rank features within-date only, or within-date-and-sector? *(Reframed
      by research §F7: touch-date snapshots make exact-date cross-sections
      thin; proposal is within (calendar quarter, snapshot_kind), sector
      variant for an allowlist only. Needs its own ADR at registry time.)*
- [ ] Snapshot frequency: quarterly vs. monthly (monthly triples data volume and
      overlap; quarterly is the default until shown insufficient).
- [ ] Min/max terminal-price labels: keep, or drop after sensitivity analysis?
- [ ] Market-regime features (PLAN.md §5.6): include in v1 feature set (with
      ablation requirement) or defer?
- [ ] Uniqueness-weight definition details: exact overlap counting for the
      `sample_weight` column (de Prado ch. 4), and whether the three
      low/median/high snapshots share a weight pool with each other.
