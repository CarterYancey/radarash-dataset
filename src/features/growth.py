"""Growth & trends family: YoY changes over reportperiod-matched lags.

Lag inputs come from `fund_base` (ADR 0004 pairing); a missing partner
leaves the feature NULL. Growth ratios are NULL when the base-period value
is <= 0 (registry null rule).
"""

from __future__ import annotations

import duckdb

from .sqlutil import safe_div


def build_growth_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_growth` view."""
    roa = safe_div("b.f_netinc", "b.l_assets")
    roa_l1 = safe_div("b.f1_netinc", "b.l1_assets")
    gm = safe_div("b.f_gp", "b.f_revenue")
    gm_l1 = safe_div("b.f1_gp", "b.f1_revenue")
    gm_l2 = safe_div("b.f2_gp", "b.f2_revenue")
    at = safe_div("b.f_revenue", "b.l_assets")
    at_l1 = safe_div("b.f1_revenue", "b.l1_assets")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW features_growth AS
        SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
               {safe_div('b.f_revenue', 'b.f1_revenue')} - 1 AS revenue_growth_1y,
               -- negative current revenue under a fractional exponent would
               -- be NaN, not a number: NULL instead.
               CASE WHEN b.f3_revenue > 0 AND b.f_revenue >= 0
                    THEN pow(b.f_revenue / b.f3_revenue, 1.0 / 3) - 1
               END AS revenue_growth_3y,
               {safe_div('b.f_epsdil', 'b.f1_epsdil')} - 1 AS epsdil_growth_1y,
               ({roa}) - ({roa_l1}) AS roa_delta_1y,
               ({gm}) - ({gm_l1}) AS gross_margin_delta_1y,
               ({gm}) - ({gm_l2}) AS gross_margin_delta_2y,
               ({at}) - ({at_l1}) AS asset_turnover_delta_1y,
               {safe_div('b.l_assets', 'b.l1_assets')} - 1 AS asset_growth_1y,
               {safe_div('b.l_sharesbas * b.l_sharefactor',
                         'b.l1_sharesbas * b.l1_sharefactor')} - 1
                   AS share_count_growth_1y
        FROM fund_base b
        """
    )
