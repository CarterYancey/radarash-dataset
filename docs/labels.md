# Label conventions

Each eligible stock-quarter emits exactly three snapshots: the earliest date at
the minimum adjusted close, earliest date at the discrete median adjusted close,
and earliest date at the maximum adjusted close. The discrete median is always
an observed price. Kinds remain separate when selected dates coincide.

Labels cover 1, 2, 3, and 5 years. The primary endpoint is the mean of the last
21 trading observations ending at the horizon. Point-to-point, terminal-window
minimum/maximum, CAGR, SPY-relative CAGR, and threshold labels are retained.

For a delisting after the snapshot and on or before the horizon, the last SEP
adjusted close is carried unchanged to the horizon: zero post-delisting return,
while retaining the entry-to-final-value return. All endpoint variants use that
carried value.

Each delisted_in_window_H column is VARCHAR because Parquet cannot mix booleans
and strings in one column. It contains "False" or the most specific nearby
ACTIONS reason, prioritized as bankruptcy/liquidation, regulatory, voluntary,
acquisition, merger, then generic delisted.
