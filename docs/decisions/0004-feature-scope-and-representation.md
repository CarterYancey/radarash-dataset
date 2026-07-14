# Feature scope and representation

Status: accepted

Dataset v1 will contain a broad, curated library of economically distinct
features rather than every possible field, ratio, transform, and lookback. The
planning range is 80–150 base numeric columns before rank mirrors and
provenance. This is not a quota; every feature must pass the acceptance criteria
in `docs/research/features.md` and `docs/features.md`.

Each accepted numeric feature stores its raw value and, when cross-sectionally
meaningful, a snapshot-date percentile rank. Sector-relative ranks and clipped
variants require separate evidence. Raw values are never overwritten by
winsorization. Infinity is invalid, and missing/invalid inputs remain null
unless a feature definition explicitly says otherwise.

The initial registry includes valuation, profitability, efficiency, accruals,
growth/stability, solvency/distress, capital allocation, investment, size,
liquidity, and a compact technical family. Market-regime features are optional
and require ablation because they may act as date identifiers.
