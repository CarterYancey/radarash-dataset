"""Feature computation (M4): per-family point-in-time features per snapshot.

The canonical registry is docs/features.md; `registry.py` is its 1:1
machine-readable mirror. Families are built in the registry's build order
from shared foundation views (`base` for as-of/lag fundamentals, `market`
for snapshot-date marketcap/EV) and each writes
data/interim/features/{family}.parquet on the labels key
(permaticker, snapshot_date, snapshot_kind). Ranks and the assembly-stage
composites (mohanram_g7, conservative_score) are computed at assembly (M5).
"""
