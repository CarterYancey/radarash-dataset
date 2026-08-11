# 0015 — Index-membership features (Dow / S&P 500 / Russell)

**Status:** accepted (2026-08-11)

## Context

Membership of a major index is a real, tradable state: it drives who may
hold the stock (index funds, many mandates), how much passive flow it
receives, and how a value screen should read a name's liquidity and
institutional coverage. Nothing in the v1 feature set carries it —
`scalemarketcap` is a current-state Sharadar bucket, not membership, and
market cap alone does not tell you whether a stock is *in* an index.

The three indices differ sharply in what is available:

- **S&P 500** — Sharadar ships `SHARADAR/SP500`, a constituent-action table
  (`added` / `removed` / `historical` / `current`) with dates. This is real
  point-in-time membership history and was simply not being ingested.
- **Dow 30** — no Sharadar table, and no bulk source in the licence we
  have. The index has 30 members and changes roughly once a year, so the
  full change history is small enough to check into the repository.
- **Russell 1000/2000/3000** — no Sharadar table and no licence-free
  constituent history at all. FTSE Russell publishes reconstitution files
  commercially; scraping them is out of scope for a batch pipeline that
  must be reproducible from the Sharadar bulk exports alone.

The pipeline's own invariants constrain the answer: features may only use
information public on or before `snapshot_date`, missing values stay NULL
rather than being imputed, and `permaticker` (not `ticker`) is the entity
key, so any external membership list has to be resolved through the
mapping's price-coverage windows.

## Decision

Add an `index` feature family (`src/features/indexes.py`) with three
independently-sourced blocks, each honest about its fidelity.

1. **`in_sp500`, `days_in_sp500` — real PIT.** Ingest `SHARADAR/SP500`
   (`src/ingest/tables.py`). Constituent actions are resolved to
   permatickers with the same rule the rest of the pipeline uses, then
   folded into membership *spells* by gaps-and-islands. A ticker whose
   earliest action is not `added` is seeded as a member from the table's
   first date: it was already a constituent when the history starts.
   `days_in_sp500` is therefore left-censored for those names, which is
   preferable to inventing a start date. The SP500 parquet is an *optional*
   input — a data directory built before this change still runs, and S&P 500
   membership comes out NULL (never false) with a logged warning.

2. **`in_dow`, `days_in_dow` — checked-in change history.**
   `src/features/reference/dow_membership.csv` holds one row per (ticker,
   membership spell) from 1999-11-01 — the composition after the 1999-11-01
   change — to today, including the ticker changes that were *not* index
   changes (ALD→HON, HWP→HPQ, SBC→T, DD→DWDP→DOW, UTX→RTX). Spells resolve
   to permatickers by maximal overlap with the price-coverage window, which
   is what separates the two companies that held the ticker `T`. The file
   carries a `VERIFIED THROUGH` date (2024-11-08); membership is carried
   forward past it and the build logs a staleness warning naming the file.

3. **`in_russell1000/2000/3000` — an explicit proxy.** Each June
   reconstitution is reconstructed by ranking *all* common stocks (the
   universe's financial exclusions included, since Russell's breakpoints are
   set on the whole market) by self-built market cap (ADR 0007) on the last
   trading day on or before May 31, effective from the first trading day of
   July until the next reconstitution: rank ≤ 1000, 1001–3000, ≤ 3000.

4. **`in_major_index`** = `in_sp500 OR in_dow OR in_russell3000`, NULL only
   when all three are NULL.

Coverage is tracked per index and **snapshots before an index's coverage
start get NULL, not false** — absence of history is not evidence of
non-membership. Within coverage, a stock we can rank but that misses the
top 3000 (including because it has no market cap that day) reads as false.

The flags are never ranked (ADR 0008 treats flags as flags); the two tenure
columns are ordinary numerics and get `_rank` at assembly, no sector rank.

## Consequences

- The dataset gains eight columns and the pipeline gains one small raw
  table (`SP500`, a few thousand rows). Assembly, the inference dataset, and
  the manifest pick the family up automatically from the registry.
- Only the S&P 500 columns are audit-grade point-in-time. The Dow columns
  are exact but depend on a hand-maintained file that must be appended to
  when the index changes — a stale file silently carries the last known
  composition forward (mitigated by the logged warning, not eliminated).
- The Russell columns are a reconstruction and will disagree with the real
  index near the breakpoints and for mid-year IPO additions. They are named
  and documented as a proxy; a model that keys hard on
  `in_russell1000`/`in_russell2000` around the 1000-rank boundary is
  reading our ranking rule, not FTSE Russell's. If a licensed constituent
  file ever lands, it can replace the proxy behind the same column names —
  which is the reason the proxy ships under those names rather than under
  `marketcap_rank_bucket`.
- No survivorship or lookahead is introduced: membership is read as of the
  snapshot date from dated events only, and delisted names keep the spells
  they had (unlike the current-state classification columns).
