# Canonical label definitions (M3)

Produced by `sharadar-labels` (`src/labels/`), consuming the ingested raw
tables and the identity artifacts. Two outputs under `data/interim/`:

- `snapshots.parquet` — one row per (permaticker, quarter, snapshot_kind)
- `labels.parquet` — one row per snapshot, wide label matrix

Design decisions: snapshot dates in
[decisions/0001](decisions/0001-quarterly-snapshot-dates.md), delisting
convention in [decisions/0002](decisions/0002-delisting-return-convention.md),
max drawdowns in [decisions/0017](decisions/0017-max-drawdown-label.md).

## Snapshots

Three per (permaticker, calendar quarter), on the dates the adjusted close
touched the quarter's **low**, **median** (discrete quantile), and **high**;
earliest date on ties. Universe-filtered (`universe.in_universe`), reused
tickers resolved to permatickers by the mapping's price-coverage window.

| column | meaning |
|---|---|
| `permaticker` | canonical entity key |
| `ticker` | ticker at the snapshot date (join key only) |
| `quarter` | first day of the calendar quarter |
| `quarter_trading_days` | priced days this stock had in the quarter |
| `snapshot_kind` | `low` \| `median` \| `high` |
| `snapshot_date` | the touch date — a real trading day |
| `entry_closeadj` | adjusted close on `snapshot_date` (label entry price) |

## Label conventions

- Horizons **H ∈ {1y, 2y, 3y, 5y}**; a horizon's nominal end is
  `snapshot_date + H` (calendar years), its **horizon end** is the last
  trading day on or before that.
- **Terminal-month average**: the end value is the mean adjusted close over
  the **21 trading days ending at** the horizon end.
- **Forward path**: the price on any trading day is the most recent adjusted
  close on or before it (forward-fill). Past a delisting this carries the
  final adjusted close at 0% to the horizon (decision 0002); it also bridges
  ordinary halts.
- **CAGR**: `(end_value / entry_closeadj)^(1/H) − 1`, nominal-year exponent.
- **Max drawdown**: the largest peak-to-trough fall of the forward path over
  `[snapshot_date, horizon end]`, `max over s ≤ t of 1 − P_t / P_s`, as a
  positive fraction (0 = never below an earlier close); the entry price
  counts as a peak. Flat past a delisting, so it adds nothing there.
- **Max drawdown from entry**: the worst mark-to-market loss vs. the entry
  price over the same path, `1 − min(P) / entry_closeadj` — bought on the
  snapshot date, sold at the lowest close before the horizon end. The entry
  day is on the path, so it is ≥ 0 (0 = never closed below entry) and never
  exceeds the max drawdown; the two differ when the path rises before it
  falls.
- **Benchmark**: SPY from SFP, identical entry/terminal conventions.
- **Observability**: labels exist only when the nominal end date is on or
  before the last calendar date; otherwise every column for that horizon is
  NULL (delisted stocks included — the benchmark path is still unknown).

## `labels.parquet` columns

Keys and entry metadata as in `snapshots.parquet`, then per horizon `{H}`:

| column | type | meaning |
|---|---|---|
| `fwd_{H}_closeadj_avg` | double | mean adjusted close over the terminal window |
| `fwd_{H}_closeadj_p2p` | double | adjusted close on the horizon-end day |
| `fwd_{H}_closeadj_min` | double | terminal-window minimum adjusted close |
| `fwd_{H}_closeadj_max` | double | terminal-window maximum adjusted close |
| `fwd_{H}_cagr` | double | terminal-month-average CAGR |
| `fwd_{H}_cagr_p2p` | double | point-to-point CAGR (endpoint-noise control) |
| `fwd_{H}_min_cagr` | double | CAGR to the terminal-window minimum |
| `fwd_{H}_max_cagr` | double | CAGR to the terminal-window maximum |
| `fwd_{H}_max_drawdown` | double | max peak-to-trough fall over the whole forward path, positive fraction in [0, 1) (decision 0017) |
| `fwd_{H}_max_drawdown_from_entry` | double | worst close over the whole forward path vs. entry, `1 − min / entry_closeadj`, in [0, 1) (decision 0017) |
| `fwd_{H}_spy_cagr` | double | SPY CAGR over the same window, same convention |
| `fwd_{H}_excess_cagr` | double | `fwd_{H}_cagr` − `fwd_{H}_spy_cagr` |
| `label_{H}_cagr_ge_0` | bool | `fwd_{H}_cagr ≥ 0%` |
| `label_{H}_cagr_ge_5` | bool | `fwd_{H}_cagr ≥ 5%` |
| `label_{H}_cagr_ge_8` | bool | `fwd_{H}_cagr ≥ 8%` |
| `label_{H}_cagr_ge_10` | bool | `fwd_{H}_cagr ≥ 10%` |
| `label_{H}_cagr_ge_15` | bool | `fwd_{H}_cagr ≥ 15%` |
| `label_{H}_cagr_ge_20` | bool | `fwd_{H}_cagr ≥ 20%` |
| `label_{H}_beat_spy` | bool | `fwd_{H}_cagr` > SPY CAGR |
| `label_{H}_excess_ge_5` | bool | `fwd_{H}_excess_cagr ≥ 5%` (beat SPY by ≥ 5 pts CAGR) |
| `label_{H}_excess_ge_10` | bool | `fwd_{H}_excess_cagr ≥ 10%` (beat SPY by ≥ 10 pts CAGR) |
| `delisted_in_window_{H}` | varchar | `'false'`, or the delist reason (decision 0002); NULL = horizon unobservable |

Binary thresholds are inclusive (`≥`). Continuous CAGRs are stored so
thresholds can be re-derived without recomputation, and the raw terminal
`closeadj` values so every CAGR can be re-derived (or re-conventioned)
straight from prices: each `fwd_{H}_*_cagr` equals
`(fwd_{H}_closeadj_* / entry_closeadj)^(1/H) − 1`. Drawdown thresholds
(e.g. "3y max drawdown < 20%") are likewise derived downstream from
`fwd_{H}_max_drawdown{,_from_entry}`; no drawdown binaries are stored
(decision 0017). The path's lowest close is
`entry_closeadj × (1 − fwd_{H}_max_drawdown_from_entry)`.

## Module layout (two-stage, PLAN.md §6)

1. **`paths`** — stage 1, path extraction: terminal-window daily price paths
   per (snapshot, horizon), and the full forward path compressed to
   calendar-quarter segments of (max, min, inner drawdown) — all delisting
   handling here and only here. Triple-barrier labels (v2) reuse the
   segments; the label functions below don't change.
2. **`compute`** — stage 2, label functions: pure aggregations over the
   extracted paths (max drawdown is an ordered fold over the segments).

Supporting: `source` (permaticker-resolved prices, trading calendar,
benchmark), `snapshots` (quarterly touch dates), `delistings` (final trade,
final price, reason from ACTIONS).
