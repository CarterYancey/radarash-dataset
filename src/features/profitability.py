"""Profitability family.

Denominators are current-quarter levels, not `*avg` — one convention
everywhere (noted deviation from textbook ROA, docs/features.md). Ratios
over `revenue` are NULL when revenue <= 0.
"""

from __future__ import annotations

import duckdb

from .sqlutil import safe_div


def build_profitability_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_profitability` view."""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW features_profitability AS
        SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
               {safe_div('b.f_gp', 'b.l_assets')} AS gp_to_assets,
               {safe_div('b.f_netinc', 'b.l_assets')} AS roa,
               {safe_div('b.f_netinc', 'b.l_equity')} AS roe,
               {safe_div('b.f_ebit', 'b.l_invcap')} AS ebit_to_invcap,
               {safe_div('b.f_ebit', 'b.l_workingcapital + b.l_ppnenet')} AS roc_greenblatt,
               {safe_div('b.f_gp', 'b.f_revenue')} AS gross_margin,
               {safe_div('b.f_ebit', 'b.f_revenue')} AS operating_margin,
               {safe_div('b.f_netinc', 'b.f_revenue')} AS net_margin,
               {safe_div('b.f_fcf', 'b.f_revenue')} AS fcf_margin,
               {safe_div('b.f_ncfo', 'b.l_assets')} AS cfo_to_assets,
               {safe_div('b.f_revenue', 'b.l_assets')} AS asset_turnover
        FROM fund_base b
        """
    )
