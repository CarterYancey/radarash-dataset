# Delisting terminal-value convention

Status: accepted

For every delisting type, the last positive SEP adjusted close is the terminal
value. It is carried unchanged from the final trading date to each applicable
label horizon, representing a 0% post-delisting return. The return between the
snapshot entry price and final adjusted trading value is retained.

The carried value is used for terminal-average, point-to-point, minimum, and
maximum endpoints. Rows are never dropped because a delisting occurs.

The horizon-specific delisted_in_window column is VARCHAR. It contains "False"
or a reason selected from nearby ACTIONS records, with specific failure reasons
preferred over generic delisted events.

This is a modeling convention, not a claim that bankruptcy recoveries or
acquisition proceeds economically earn exactly zero after delisting. V4 sampling
remains required to assess how well final SEP values proxy realized proceeds.
