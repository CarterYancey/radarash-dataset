"""Classification family: sector/industry/famaindustry/scale from TICKERS.

Current-state, not historical — a reclassified firm's history gets today's
label (documented caveat, research §F8.3; `siccode` is the era-stable
fallback). Strings stay strings: trees handle categoricals downstream, no
one-hot in the dataset, never ranked (ADR 0008).
"""

from __future__ import annotations

import duckdb


def build_classification_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_classification` view from `snapshots` × `universe`."""
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW features_classification AS
        SELECT s.permaticker, s.snapshot_date, s.snapshot_kind,
               u.sector, u.industry, u.famaindustry, u.scalemarketcap,
               u.siccode
        FROM snapshots s
        JOIN universe u USING (permaticker)
        """
    )
