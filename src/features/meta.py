"""Meta family: filing provenance, staleness, and sign flags.

ADR 0006: no staleness cutoff — `fundamentals_age_days` is a first-class
(ranked) feature and the 183d/365d cutoffs are stored as flag columns for
downstream filtering. No-filing snapshots keep NULL age (the flags are
determinably false); sign flags stay NULL when their input is missing.
"""

from __future__ import annotations

import duckdb


def build_meta_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_meta` view from `fund_base` and `market_inputs`."""
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW features_meta AS
        SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
               b.fund_datekey,
               b.fund_reportperiod,
               b.snapshot_date - b.fund_datekey AS fundamentals_age_days,
               coalesce(b.snapshot_date - b.fund_datekey <= 183, false)
                   AS has_filing_183d,
               coalesce(b.snapshot_date - b.fund_datekey <= 365, false)
                   AS has_filing_365d,
               b.l_equity <= 0 AS negative_equity,
               b.f_ebitda <= 0 AS negative_ebitda,
               m.ev <= 0 AS negative_ev
        FROM fund_base b
        JOIN market_inputs m
          USING (permaticker, snapshot_date, snapshot_kind)
        """
    )
