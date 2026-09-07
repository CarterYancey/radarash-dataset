# 0016 — Per-feature rank policy: no ranks for integer scores, pinned ranks for mass points, a quarter-key audit

Date: 2026-09-03
Status: accepted (amends 0008 §2/§4 and 0013 "ranked like any numeric feature")

## Context

`value-ml-models` ran the registered era-identifiability probe
(manual §7) on `dataset_v1.0` under `entity_holdout`, 3y: predict the
calendar year of a row from its features alone, train and test
entity-disjoint. Their brief is archived verbatim in
[research/rank-quarter-keys.md](../research/rank-quarter-keys.md). The
headline: the raw feature set dates a row with 0.45 accuracy (genuine
drift), the **rank set with 0.954**, and four rank columns alone —
`piotroski_f_rank`, `mohanram_g7_rank`, `rnd_to_assets_rank`,
`dividend_yield_rank` — with 0.917, against 0.148 for the same four
columns raw. The rank transform *adds* a quarter identifier.

The mechanism is the tie convention, not economics. Ranks are
`percent_rank()` within (calendar quarter, snapshot_kind) and tied values
share the lower percent rank (decision 0008), so a tied group at value *v*
in quarter *q* carries `(# rows in q with value < v) / (n_q − 1)`: the share
of that quarter's cross-section below the group. That share is a property
of the quarter and recurs in no other quarter. `piotroski_f` takes ten
integer values, so every quarter emits ten constants; verified on the
parquet, `piotroski_f_rank` has 1160 distinct (quarter, value) pairs over
116 quarters and 1044 distinct values — every constant except the bottom
group's 0.0 occurs in exactly one quarter. A zero-inflated ratio has the
same property at one point: its zero group ranks 0.0 everywhere (harmless)
but the first non-zero rank equals the quarter's zero share.

Consequences downstream: the diagnostic schemes `entity_holdout` and
`random_kfold` are contaminated for rank-fed models (the model looks the
test row's quarter up among training rows and reads off that quarter's base
rate), so the registered leakage-gap experiment (decision 0010) would
mostly measure this; `walkforward` and `holdout` are not inflated (test
quarters are unseen) but rank-fed models waste capacity memorising training
quarters, absorb an undeclared market-state signal (PLAN §5.6 gates those
behind an ablation), and yield extracted rules whose thresholds mean a
different score cutoff in every quarter.

No tie convention fixes it: average, dense or midpoint ranks are all
deterministic functions of the tied group's share, so all are keys. The
problem is structural to ranking a discrete or mass-point variable within a
cross-section.

## Decision

1. **Rank policy is a per-feature registry attribute** (`FeatureSpec.rank`,
   mirrored in the notes column of docs/features.md and enforced 1:1 by
   `tests/test_features_registry.py`), with three values:

   - **`full`** — decision 0008 unchanged: `percent_rank()` within
     (quarter, kind) over non-NULL values, thin-slice guard, ties share the
     lower rank. For continuous features, whose rank granularity
     `1/(n_q − 1)` is below what histogram binning resolves.
   - **`none`** — no `{name}_rank` (nor `_secrank`) column. Applied to
     every integer-valued composite, count and share: `piotroski_f`,
     `mohanram_g7`, `fundamentals_age_days` (integer days),
     `fund_history_quarters`, the four `div_*_10y` counters, the twelve
     `*_up_frac_{w}q` and four `ocf_positive_frac_{w}q` shares (at most
     w+1 values) — and `ni_change_scaled`, which is bounded to [−1, 1] and
     sits at exactly +1 / −1 for every loss→profit / profit→loss flip (a
     fifth of the cross-section in 2010-Q4): two masses cannot be pinned,
     and the raw value is a fixed-scale score already (Ohlson's CHIN
     term). The raw score is already cross-sectionally comparable; a
     fixed-scale [0, 1] version (`piotroski_f / 9`) is a downstream
     one-liner if wanted, and is deliberately **not** shipped as a column —
     it would be redundant with the raw score.
   - **`pinned`** — for features with a probability mass at exactly one
     raw value, declared as `pin_value` (0 unless stated) with a pin rank
     `pin_rank ∈ {0, 0.5, 1}`: rows at `pin_value` take the rank
     `pin_rank` in every quarter; the rest are `percent_rank()`ed **within
     their side of the pin** and mapped onto the matching interval — below
     to `pin_rank · pr`, above to `pin_rank + (1 − pin_rank) · pr`. The
     mass's rank is thus a fixed constant instead of the quarter's share
     below it, the mapping is weakly monotone in the raw value, and each
     side is continuous, so no key remains. The pin rank sits at the empty
     end of a one-sided support and in the middle of a two-sided one:
     - mass at 0, rank **0**: `dividend_yield` (non-payers),
       `rnd_to_assets` (non-reporters, the ADR 0013 fill),
       `capex_to_assets`, `debt_to_equity` (debt-free), `sales_yield` and
       `asset_turnover` (pre-revenue firms);
     - mass at 0, rank **0.5**: `net_payout_yield` (neither payout nor
       issuance), `ext_financing_to_assets`, `share_count_growth_1y`
       (unchanged share count), and — found by the first real-data audit
       run, 2026-09-07 — `gp_to_assets` (pre-revenue firms, gross profit
       exactly 0), `asset_turnover_delta_1y`, `gross_margin_delta_1y`,
       `gross_margin_delta_2y` (unchanged YoY) and `ret_1m` (no price
       change in a month) — signed supports, negatives
       below the pin, positives above;
     - mass at 0, rank **1**: `dist_52w_high` (≤ 0 by construction; a
       stock at its 52-week high is the top of the cross-section, and a
       large share of `high`-kind rows sit exactly there);
     - mass at **1** (same audit run): `gross_margin` at rank **1** (no
       cost of revenue reported ⇒ gross profit = revenue, and the margin is
       ≤ 1 by construction), `gmi` (unchanged margin, a ratio of 1) and
       `ev_to_marketcap` (no debt and no cash ⇒ EV = market cap) at rank
       **0.5**.
     The value nearest the pin on a one-sided support shares the pin rank
     (its within-side percent rank is 0); accepted — the raw column
     separates them, and the alternative (a NULL rank for the mass) would
     conflate "zero" with "not knowable" (manual §6). Anomalous values on
     the wrong side of a one-sided pin (a positive `dist_52w_high`, a
     gross margin above 1) collapse onto the pin. The thin-slice guard
     keeps counting non-NULL values, not the off-pin support.

   Sector ranks (`_secrank`) follow the same policy as the feature's
   plain rank. `conservative_score` keeps its formula
   (`(1 − vol_36m_rank) + mom_12_2_rank + net_payout_yield_rank`, range
   [0, 3]) with the now-pinned `net_payout_yield_rank` as input, and stays
   ranked (`full`) — it is continuous once its inputs are key-free.

2. **A build-time quarter-key audit gates every dataset build**
   (`src/assemble/audit.py`). After `dataset.parquet` is written, every
   rank and sector-rank column is measured per snapshot kind on the parquet
   itself:

   | metric | definition |
   |---|---|
   | `tie_mass` | share of rows whose rank value is shared with ≥ 1 other row of the same (quarter, kind) — the brief's (i) |
   | `keyed_mass` | share of rows in such tie groups whose rank value occurs in exactly one quarter of that kind |
   | `max_key_share` | the largest keyed tie group as a share of its (quarter, kind) cross-section |
   | `key_quarter`, `key_rank_value`, `key_raw_value` | where that group sits and the raw value behind it — the raw value is the `pin_value` a registry fix declares (or says the feature is integer-valued ⇒ `none`) |
   | `distinct_values`, `distinct_quarter_value_pairs`, `quarters` | the brief's (ii) |

   The **gate is `max_key_share > --max-key-share` (default 0.02)**, not
   tie mass: a fine-grained integer column ties nearly every row in groups
   of a few rows, and its constants are too light and too numerous for a
   tree's histogram bins to resolve, whereas a single tied group holding a
   few percent of a cross-section is a resolvable constant. Zero-pinned
   groups are tied in every quarter but never keyed (the pin recurs), so
   they pass by construction. A failing audit **removes the directory and
   exits 1**, naming every column with its worst group and the remedy
   (change the feature's rank policy in the registry and rebuild), and
   keeps the audit table under `data/interim/qa/` so the failure can be
   read without a rebuild.
   `--allow-rank-keys` publishes anyway; the keyed columns are then listed
   in `manifest.json["rank_audit"]["flagged"]`. The full table ships as
   `rank_audit.parquet` in the dataset directory, and the manifest carries
   the per-column worst case (`rank_audit.columns`) and the full policy
   (`rank_policy`) so consumers can exclude columns themselves — the
   brief's option (b), on top of (a).

3. **Dataset v1.2, a breaking change.** Rank column semantics change for
   18 features and 25 rank columns disappear, so results must not be
   compared across the v1.1 → v1.2 boundary; rank-fed downstream configs
   need a `min_dataset_version` bump. `sharadar-assemble` defaults to
   `1.2`. The inference dataset (decision 0014) uses the same
   `build_wide_views`, so it carries the same policy verbatim (its manifest
   records `rank_policy`); the audit is not run there — a single-partition
   cross-section has no quarter to key.

4. **Raw columns and flags are untouched.** The raw four-column arm's 0.148
   is genuine drift in payer and R&D-reporter shares — era signal a
   walk-forward model is entitled to see. No feature definition changes.

5. **Acceptance test.** The era probe is re-run downstream on receipt
   (`scripts/run_diagnostic.py era-probe` in `value-ml-models`): a
   `ranks`-only probe under `entity_holdout` should land near the raw
   level (≈ 0.15–0.45), not 0.9. The audit is the upstream proxy for it
   and runs on every build.

## Consequences

- `docs/features.md` notes carry the policy per row (`not ranked`,
  `pinned rank (r [at raw v])`); `docs/dataset.md` documents the rank groups,
  `rank_audit.parquet` and the new manifest fields; `docs/manual.md` tells
  downstream how to read them and about the version boundary.
- Decision 0008 §2 ("Column naming: `{feature}_rank`" for every numeric)
  and §4 ("Composites are ranked like any other numeric feature") and
  decision 0013's "ranked like any numeric feature" are amended by §1
  above; 0008's mechanics are otherwise unchanged.
- A registry mistake (a mass point nobody declared) cannot silently return:
  the next real-data build fails with the column, quarter and raw value
  named, and keeps the audit table. The first policy list was decided from
  feature definitions; the first real-data build (2026-09-07, 1.53M rows)
  flagged eleven more columns (worst: `ni_change_scaled` 20%,
  `gp_to_assets` 19%, `asset_turnover_delta_1y` 14%, the gross-margin
  family 6–8%, `ret_1m` and `ev_to_marketcap` ~2–3%), which is where the
  mass-at-1 pins come from; the second run located `ni_change_scaled`'s
  mass at raw +1 (a sign flip, not "unchanged"), which is why it is
  unranked rather than pinned. A flagged column means "declare its
  policy", not "raise the threshold".
- The leakage-gap experiment (decision 0010) and the era probe become
  meaningful for rank-fed models; their downstream registrations stand.
- Cost: 24 fewer rank columns; ~113 extra column-pruned scans of the
  written parquet at assembly (seconds to a minute on the real dataset).
