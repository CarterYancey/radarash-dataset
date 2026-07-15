"""Earnings-quality family: Beneish M inputs/composite, Piotroski F,
accruals, NOA, external financing.

Beneish indices are ART pairs lagged one fiscal year (research §F2.2).
`piotroski_f` counts the 9 signals from the shared components; signal 5
(leverage down) uses non-current debt over current-quarter assets — F2.2's
field choice under the registry's current-level denominator convention —
and signal 7 uses the cash-flow convention `ncfcommon <= 0`. Composites
are NULL when any component/signal is NULL. `mohanram_g7` is
assembly-stage (M5) and not emitted here.
"""

from __future__ import annotations

import duckdb

from .sqlutil import safe_div


def build_quality_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_quality` view."""
    dsri = safe_div(
        safe_div("b.l_receivables", "b.f_revenue"),
        safe_div("b.l1_receivables", "b.f1_revenue"),
    )
    gm = safe_div("b.f_gp", "b.f_revenue")
    gm_l1 = safe_div("b.f1_gp", "b.f1_revenue")
    # GMI is NULL if either margin is <= 0 (registry rule): the inner
    # safe_div only guards revenue, so gate on both margins explicitly.
    gmi = (
        f"CASE WHEN ({gm}) > 0 AND ({gm_l1}) > 0 "
        f"THEN ({gm_l1}) / ({gm}) END"
    )
    soft = f"1 - {safe_div('b.l_assetsc + b.l_ppnenet', 'b.l_assets')}"
    soft_l1 = f"1 - {safe_div('b.l1_assetsc + b.l1_ppnenet', 'b.l1_assets')}"
    aqi = safe_div(soft, soft_l1)
    sgi = safe_div("b.f_revenue", "b.f1_revenue")
    dep_rate = safe_div("b.f_depamor", "b.f_depamor + b.l_ppnenet")
    dep_rate_l1 = safe_div("b.f1_depamor", "b.f1_depamor + b.l1_ppnenet")
    depi = safe_div(dep_rate_l1, dep_rate)
    sgai = safe_div(
        safe_div("b.f_sgna", "b.f_revenue"),
        safe_div("b.f1_sgna", "b.f1_revenue"),
    )
    lvgi = safe_div(
        safe_div("b.l_debt + b.l_liabilitiesc", "b.l_assets"),
        safe_div("b.l1_debt + b.l1_liabilitiesc", "b.l1_assets"),
    )
    tata = safe_div("b.f_netinc - b.f_ncfo", "b.l_assets")

    roa = safe_div("b.f_netinc", "b.l_assets")
    roa_l1 = safe_div("b.f1_netinc", "b.l1_assets")
    at = safe_div("b.f_revenue", "b.l_assets")
    at_l1 = safe_div("b.f1_revenue", "b.l1_assets")
    f_signals = " + ".join(
        f"CAST(({sig}) AS INTEGER)"
        for sig in (
            f"({roa}) > 0",
            "b.f_ncfo > 0",
            f"({roa}) - ({roa_l1}) > 0",
            "b.f_ncfo > b.f_netinc",
            f"({safe_div('b.l_debtnc', 'b.l_assets')})"
            f" < ({safe_div('b.l1_debtnc', 'b.l1_assets')})",
            f"({safe_div('b.l_assetsc', 'b.l_liabilitiesc')})"
            f" > ({safe_div('b.l1_assetsc', 'b.l1_liabilitiesc')})",
            "b.f_ncfcommon <= 0",
            f"({gm}) - ({gm_l1}) > 0",
            f"({at}) - ({at_l1}) > 0",
        )
    )

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW features_quality AS
        SELECT b.permaticker, b.snapshot_date, b.snapshot_kind,
               {dsri} AS dsri,
               {gmi} AS gmi,
               {aqi} AS aqi,
               {sgi} AS sgi,
               {depi} AS depi,
               {sgai} AS sgai,
               {lvgi} AS lvgi,
               {tata} AS accruals_to_assets,
               -4.84 + 0.92 * ({dsri}) + 0.528 * ({gmi}) + 0.404 * ({aqi})
                     + 0.892 * ({sgi}) + 0.115 * ({depi}) - 0.172 * ({sgai})
                     + 4.679 * ({tata}) - 0.327 * ({lvgi}) AS beneish_m,
               {f_signals} AS piotroski_f,
               {safe_div('(b.l_assets - b.l_cashneq - b.l_investments)'
                         ' - (b.l_liabilities - b.l_debt)', 'b.l1_assets')}
                   AS noa_to_assets,
               {safe_div('b.f_ncfcommon + b.f_ncfdebt', 'b.l_assets')}
                   AS ext_financing_to_assets
        FROM fund_base b
        """
    )
