"""Valuation family: yields and deep-value markers (ADR 0005 §4).

Yield orientation throughout — the denominator is marketcap (positive by
construction when present) or EV (NULL when <= 0, with the sign kept once
in the `negative_ev` flag); negative numerators are meaningful and kept.
"""

from __future__ import annotations

import duckdb

from .sqlutil import safe_div


def build_valuation_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_valuation` view."""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW features_valuation AS
        SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
               {safe_div('b.f_netinc', 'm.marketcap')} AS earnings_yield,
               {safe_div('b.f_ncfo', 'm.marketcap')} AS ocf_yield,
               {safe_div('b.f_fcf', 'm.marketcap')} AS fcf_yield,
               {safe_div('b.f_revenue', 'm.marketcap')} AS sales_yield,
               {safe_div('b.l_equity', 'm.marketcap')} AS book_to_market,
               {safe_div('b.l_tangibles', 'm.marketcap')} AS tangible_book_to_market,
               {safe_div('b.f_ebit', 'm.ev')} AS ebit_to_ev,
               {safe_div('b.f_ebitda', 'm.ev')} AS ebitda_to_ev,
               {safe_div('-b.f_ncfdiv', 'm.marketcap')} AS dividend_yield,
               {safe_div('-(b.f_ncfdiv + b.f_ncfcommon)', 'm.marketcap')} AS net_payout_yield,
               {safe_div('b.l_assetsc - b.l_liabilities', 'm.marketcap')} AS ncav_to_marketcap,
               {safe_div('m.ev', 'm.marketcap')} AS ev_to_marketcap
        FROM fund_base b
        JOIN market_inputs m
          USING (permaticker, snapshot_date, snapshot_kind)
        """
    )
