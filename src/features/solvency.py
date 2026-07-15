"""Solvency / distress family: Altman-Z, Ohlson-O, and Zmijewski components
plus the canonical composites (ADR 0003).

Composites are NULL when any component is NULL. `interest_coverage` is NULL
when intexp <= 0 (no debt => NULL, not infinity); `ffo_to_liabilities`
proxies FFO with CFO (research §F1 gap); `log_assets` is nominal (the rank
representation absorbs the drift, ADR 0008).
"""

from __future__ import annotations

import duckdb

from .sqlutil import safe_div, safe_ln


def build_solvency_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_solvency` view."""
    wc_ta = safe_div("b.l_workingcapital", "b.l_assets")
    re_ta = safe_div("b.l_retearn", "b.l_assets")
    ebit_ta = safe_div("b.f_ebit", "b.l_assets")
    mve_tl = safe_div("m.marketcap", "b.l_liabilities")
    bve_tl = safe_div("b.l_equity", "b.l_liabilities")
    sales_ta = safe_div("b.f_revenue", "b.l_assets")
    roa = safe_div("b.f_netinc", "b.l_assets")
    tl_ta = safe_div("b.l_liabilities", "b.l_assets")
    ca_cl = safe_div("b.l_assetsc", "b.l_liabilitiesc")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW features_solvency AS
        SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
               {wc_ta} AS wc_to_assets,
               {re_ta} AS retearn_to_assets,
               {ebit_ta} AS ebit_to_assets,
               {mve_tl} AS marketcap_to_liabilities,
               {bve_tl} AS equity_to_liabilities,
               {tl_ta} AS liabilities_to_assets,
               {safe_div('b.l_liabilitiesc', 'b.l_assetsc')} AS cl_to_ca,
               {ca_cl} AS current_ratio,
               {safe_div('b.l_assetsc - b.l_inventory', 'b.l_liabilitiesc')}
                   AS quick_ratio,
               {safe_div('b.l_cashneq', 'b.l_assets')} AS cash_to_assets,
               {safe_div('b.l_debt', 'b.l_equity')} AS debt_to_equity,
               {safe_div('b.l_debt - b.l_cashneq', 'b.f_ebitda')}
                   AS net_debt_to_ebitda,
               {safe_div('b.f_ebit', 'b.f_intexp')} AS interest_coverage,
               {safe_div('b.f_ncfo', 'b.l_liabilities')} AS ffo_to_liabilities,
               {safe_ln('b.l_assets')} AS log_assets,
               {safe_div('b.f_netinc - b.f1_netinc',
                         'abs(b.f_netinc) + abs(b.f1_netinc)')}
                   AS ni_change_scaled,
               b.f_netinc < 0 AND b.f1_netinc < 0 AS two_year_loss,
               b.l_liabilities > b.l_assets AS liab_gt_assets,
               1.2 * ({wc_ta}) + 1.4 * ({re_ta}) + 3.3 * ({ebit_ta})
                   + 0.6 * ({mve_tl}) + 1.0 * ({sales_ta}) AS altman_z,
               6.56 * ({wc_ta}) + 3.26 * ({re_ta}) + 6.72 * ({ebit_ta})
                   + 1.05 * ({bve_tl}) AS altman_z_dd,
               -4.336 - 4.513 * ({roa}) + 5.679 * ({tl_ta})
                   + 0.004 * ({ca_cl}) AS zmijewski
        FROM fund_base b
        JOIN market_inputs m
          USING (permaticker, snapshot_date, snapshot_kind)
        """
    )
