"""Machine-readable feature registry — the 1:1 mirror of docs/features.md.

Every emitted feature column is declared here; `output.write_family_table`
refuses to write a family parquet whose columns don't match this registry
exactly, and assembly (M5) drives rank/sector-rank computation from the
`rank` policy and `sector_rank` flag of each spec (ADR 0008 mechanics,
ADR 0016 per-feature policy). Update docs/features.md and this file
together (tests/test_features_registry.py enforces the 1:1).
"""

from __future__ import annotations

from dataclasses import dataclass

# The shared key of every family parquet — same key as labels.parquet.
KEY_COLUMNS: tuple[str, ...] = ("permaticker", "snapshot_date", "snapshot_kind")

# Output families in build order (foundation views `base` and `market` are
# not families — they emit no parquet of their own).
FAMILIES: tuple[str, ...] = (
    "meta",
    "valuation",
    "profitability",
    "growth",
    "trend",
    "solvency",
    "quality",
    "technical",
    "classification",
)

# kind: only numeric features can carry ranks at assembly; flags /
# categoricals / metadata never do (ADR 0008).
KINDS = ("numeric", "flag", "categorical", "metadata")

# Rank policy of a numeric feature (ADR 0016; mechanics in assemble/wide.py):
#   full         percent_rank over every non-NULL value of the cross-section
#                (ADR 0008) — continuous features only.
#   pinned       rows at exactly `pin_value` (a probability mass, usually 0)
#                take the fixed rank `pin_rank`; the rest are percent-ranked
#                within their side of the pin and mapped below / above it.
#                A within-quarter rank of the mass would equal the quarter's
#                share below it — a quarter identifier.
#   none         no rank column. Integer-valued composites, counts and
#                shares: each tied score group's percent rank is a
#                quarter-specific constant, so the raw score — already
#                cross-sectionally comparable — is shipped alone.
RANK_POLICIES = ("full", "pinned", "none")


@dataclass(frozen=True)
class FeatureSpec:
    """One feature column: name, family, depth tier, and rank treatment."""

    name: str
    family: str
    tier: str | None  # T0-T3 / P12 / P36 (ADR 0004), T5 / T10 (ADR 0015); None for classification
    kind: str
    definition: str
    rank: str = "full"  # one of RANK_POLICIES; forced to "none" for non-numeric kinds
    pin_value: float = 0.0  # pinned only: the raw value carrying the mass
    pin_rank: float = 0.0  # pinned only: rank of that mass (0.0 / 0.5 / 1.0)
    sector_rank: bool = False  # "S" in docs/features.md (ADR 0008 allowlist)
    assembly_stage: bool = False  # computed at assembly (M5), not by a family
    added_in_version: str = "1.0"
    removed_in_version: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"{self.name}: unknown kind {self.kind!r}")
        if self.rank not in RANK_POLICIES:
            raise ValueError(f"{self.name}: unknown rank policy {self.rank!r}")
        if self.kind != "numeric" and self.rank != "none":
            raise ValueError(f"{self.name}: only numeric features are ranked")
        if self.rank != "pinned" and (self.pin_value, self.pin_rank) != (0.0, 0.0):
            raise ValueError(f"{self.name}: pin_value/pin_rank need rank='pinned'")
        if not 0.0 <= self.pin_rank <= 1.0:
            raise ValueError(f"{self.name}: pin_rank must lie in [0, 1]")
        if self.sector_rank and self.rank == "none":
            raise ValueError(f"{self.name}: sector_rank requires a rank policy")

    @property
    def ranked(self) -> bool:
        """Whether assembly emits `{name}_rank` (and `_secrank` if allowed)."""
        return self.rank != "none"


def _f(name, family, tier, kind, definition, **kw) -> FeatureSpec:
    if kind != "numeric":
        kw.setdefault("rank", "none")
    return FeatureSpec(name, family, tier, kind, definition, **kw)


FEATURES: tuple[FeatureSpec, ...] = (
    # ---- meta ------------------------------------------------------------
    _f("fund_datekey", "meta", "T0", "metadata", "datekey of the filing used"),
    _f("fund_reportperiod", "meta", "T0", "metadata", "reportperiod of that filing"),
    _f("fundamentals_age_days", "meta", "T0", "numeric", "snapshot_date - datekey", rank="none"),
    _f("has_filing_183d", "meta", "T0", "flag", "fundamentals_age_days <= 183"),
    _f("has_filing_365d", "meta", "T0", "flag", "fundamentals_age_days <= 365"),
    _f("negative_equity", "meta", "T0", "flag", "equity_q <= 0"),
    _f("negative_ebitda", "meta", "T0", "flag", "ebitda <= 0"),
    _f("negative_ev", "meta", "T0", "flag", "ev <= 0"),
    # ---- valuation (yield orientation, ADR 0005 §4) ----------------------
    _f("earnings_yield", "valuation", "T0", "numeric", "netinc / marketcap", sector_rank=True),
    _f("ocf_yield", "valuation", "T0", "numeric", "ncfo / marketcap", sector_rank=True),
    _f("fcf_yield", "valuation", "T0", "numeric", "fcf / marketcap", sector_rank=True),
    _f("sales_yield", "valuation", "T0", "numeric", "revenue / marketcap", rank="pinned", pin_rank=0.0, sector_rank=True),
    _f("book_to_market", "valuation", "T0", "numeric", "equity_q / marketcap", sector_rank=True),
    _f("tangible_book_to_market", "valuation", "T0", "numeric", "tangibles_q / marketcap", sector_rank=True),
    _f("ebit_to_ev", "valuation", "T0", "numeric", "ebit / ev", sector_rank=True),
    _f("ebitda_to_ev", "valuation", "T0", "numeric", "ebitda / ev", sector_rank=True),
    _f("dividend_yield", "valuation", "T0", "numeric", "-ncfdiv / marketcap", rank="pinned", pin_rank=0.0),
    _f("net_payout_yield", "valuation", "T0", "numeric", "-(ncfdiv + ncfcommon) / marketcap", rank="pinned", pin_rank=0.5),
    _f("ncav_to_marketcap", "valuation", "T0", "numeric", "(assetsc_q - liabilities_q) / marketcap"),
    _f("ev_to_marketcap", "valuation", "T0", "numeric", "ev / marketcap", rank="pinned", pin_value=1.0, pin_rank=0.5),
    # ---- profitability ----------------------------------------------------
    _f("gp_to_assets", "profitability", "T0", "numeric", "gp / assets_q", rank="pinned", pin_rank=0.5, sector_rank=True),
    _f("roa", "profitability", "T0", "numeric", "netinc / assets_q"),
    _f("roe", "profitability", "T0", "numeric", "netinc / equity_q"),
    _f("ebit_to_invcap", "profitability", "T0", "numeric", "ebit / invcap_q"),
    _f("roc_greenblatt", "profitability", "T0", "numeric", "ebit / (workingcapital_q + ppnenet_q)"),
    _f("gross_margin", "profitability", "T0", "numeric", "gp / revenue", rank="pinned", pin_value=1.0, pin_rank=1.0, sector_rank=True),
    _f("operating_margin", "profitability", "T0", "numeric", "ebit / revenue", sector_rank=True),
    _f("net_margin", "profitability", "T0", "numeric", "netinc / revenue", sector_rank=True),
    _f("fcf_margin", "profitability", "T0", "numeric", "fcf / revenue"),
    _f("cfo_to_assets", "profitability", "T0", "numeric", "ncfo / assets_q"),
    _f("asset_turnover", "profitability", "T0", "numeric", "revenue / assets_q", rank="pinned", pin_rank=0.0),
    # ---- growth & trends ---------------------------------------------------
    _f("revenue_growth_1y", "growth", "T1", "numeric", "revenue / revenue[-1] - 1"),
    _f("revenue_growth_3y", "growth", "T3", "numeric", "(revenue / revenue[-3])^(1/3) - 1"),
    _f("epsdil_growth_1y", "growth", "T1", "numeric", "epsdil / epsdil[-1] - 1"),
    _f("roa_delta_1y", "growth", "T1", "numeric", "roa - roa[-1]"),
    _f("gross_margin_delta_1y", "growth", "T1", "numeric", "gross_margin - gross_margin[-1]", rank="pinned", pin_rank=0.5),
    _f("gross_margin_delta_2y", "growth", "T2", "numeric", "gross_margin - gross_margin[-2]", rank="pinned", pin_rank=0.5),
    _f("asset_turnover_delta_1y", "growth", "T1", "numeric", "asset_turnover - asset_turnover[-1]", rank="pinned", pin_rank=0.5),
    _f("asset_growth_1y", "growth", "T1", "numeric", "assets_q / assets_q[-1] - 1"),
    _f("share_count_growth_1y", "growth", "T1", "numeric", "(sharesbas*sharefactor) YoY - 1", rank="pinned", pin_rank=0.5),
    # ---- trend & consistency (ADR 0015; quarterly windows, annual dividends)
    _f("revenue_trend_4q", "trend", "T1", "numeric", "regr_slope(ln(revenue), years) over last 4 quarterly obs", added_in_version="1.1"),
    _f("revenue_consistency_4q", "trend", "T1", "numeric", "regr_r2 of the 4q revenue fit", added_in_version="1.1"),
    _f("revenue_up_frac_4q", "trend", "T1", "numeric", "share of adjacent-quarter revenue increases, 4q", rank="none", added_in_version="1.1"),
    _f("revenue_trend_8q", "trend", "T2", "numeric", "regr_slope(ln(revenue), years) over last 8 quarterly obs", added_in_version="1.1"),
    _f("revenue_consistency_8q", "trend", "T2", "numeric", "regr_r2 of the 8q revenue fit", added_in_version="1.1"),
    _f("revenue_up_frac_8q", "trend", "T2", "numeric", "share of adjacent-quarter revenue increases, 8q", rank="none", added_in_version="1.1"),
    _f("revenue_trend_12q", "trend", "T3", "numeric", "regr_slope(ln(revenue), years) over last 12 quarterly obs", added_in_version="1.1"),
    _f("revenue_consistency_12q", "trend", "T3", "numeric", "regr_r2 of the 12q revenue fit", added_in_version="1.1"),
    _f("revenue_up_frac_12q", "trend", "T3", "numeric", "share of adjacent-quarter revenue increases, 12q", rank="none", added_in_version="1.1"),
    _f("revenue_trend_20q", "trend", "T5", "numeric", "regr_slope(ln(revenue), years) over last 20 quarterly obs", added_in_version="1.1"),
    _f("revenue_consistency_20q", "trend", "T5", "numeric", "regr_r2 of the 20q revenue fit", added_in_version="1.1"),
    _f("revenue_up_frac_20q", "trend", "T5", "numeric", "share of adjacent-quarter revenue increases, 20q", rank="none", added_in_version="1.1"),
    _f("tangibles_trend_4q", "trend", "T1", "numeric", "regr_slope(ln(tangibles_q), years) over last 4 quarterly obs", added_in_version="1.1"),
    _f("tangibles_consistency_4q", "trend", "T1", "numeric", "regr_r2 of the 4q tangibles fit", added_in_version="1.1"),
    _f("tangibles_up_frac_4q", "trend", "T1", "numeric", "share of adjacent-quarter tangibles increases, 4q", rank="none", added_in_version="1.1"),
    _f("tangibles_trend_8q", "trend", "T2", "numeric", "regr_slope(ln(tangibles_q), years) over last 8 quarterly obs", added_in_version="1.1"),
    _f("tangibles_consistency_8q", "trend", "T2", "numeric", "regr_r2 of the 8q tangibles fit", added_in_version="1.1"),
    _f("tangibles_up_frac_8q", "trend", "T2", "numeric", "share of adjacent-quarter tangibles increases, 8q", rank="none", added_in_version="1.1"),
    _f("tangibles_trend_12q", "trend", "T3", "numeric", "regr_slope(ln(tangibles_q), years) over last 12 quarterly obs", added_in_version="1.1"),
    _f("tangibles_consistency_12q", "trend", "T3", "numeric", "regr_r2 of the 12q tangibles fit", added_in_version="1.1"),
    _f("tangibles_up_frac_12q", "trend", "T3", "numeric", "share of adjacent-quarter tangibles increases, 12q", rank="none", added_in_version="1.1"),
    _f("tangibles_trend_20q", "trend", "T5", "numeric", "regr_slope(ln(tangibles_q), years) over last 20 quarterly obs", added_in_version="1.1"),
    _f("tangibles_consistency_20q", "trend", "T5", "numeric", "regr_r2 of the 20q tangibles fit", added_in_version="1.1"),
    _f("tangibles_up_frac_20q", "trend", "T5", "numeric", "share of adjacent-quarter tangibles increases, 20q", rank="none", added_in_version="1.1"),
    _f("ocf_trend_4q", "trend", "T1", "numeric", "regr_slope(ln(ncfo), years) over last 4 quarterly obs", added_in_version="1.1"),
    _f("ocf_consistency_4q", "trend", "T1", "numeric", "regr_r2 of the 4q ncfo fit", added_in_version="1.1"),
    _f("ocf_up_frac_4q", "trend", "T1", "numeric", "share of adjacent-quarter ncfo increases, 4q", rank="none", added_in_version="1.1"),
    _f("ocf_trend_8q", "trend", "T2", "numeric", "regr_slope(ln(ncfo), years) over last 8 quarterly obs", added_in_version="1.1"),
    _f("ocf_consistency_8q", "trend", "T2", "numeric", "regr_r2 of the 8q ncfo fit", added_in_version="1.1"),
    _f("ocf_up_frac_8q", "trend", "T2", "numeric", "share of adjacent-quarter ncfo increases, 8q", rank="none", added_in_version="1.1"),
    _f("ocf_trend_12q", "trend", "T3", "numeric", "regr_slope(ln(ncfo), years) over last 12 quarterly obs", added_in_version="1.1"),
    _f("ocf_consistency_12q", "trend", "T3", "numeric", "regr_r2 of the 12q ncfo fit", added_in_version="1.1"),
    _f("ocf_up_frac_12q", "trend", "T3", "numeric", "share of adjacent-quarter ncfo increases, 12q", rank="none", added_in_version="1.1"),
    _f("ocf_trend_20q", "trend", "T5", "numeric", "regr_slope(ln(ncfo), years) over last 20 quarterly obs", added_in_version="1.1"),
    _f("ocf_consistency_20q", "trend", "T5", "numeric", "regr_r2 of the 20q ncfo fit", added_in_version="1.1"),
    _f("ocf_up_frac_20q", "trend", "T5", "numeric", "share of adjacent-quarter ncfo increases, 20q", rank="none", added_in_version="1.1"),
    _f("ocf_positive_frac_4q", "trend", "T1", "numeric", "share of last 4 quarterly obs with ncfo > 0", rank="none", added_in_version="1.1"),
    _f("ocf_positive_frac_8q", "trend", "T2", "numeric", "share of last 8 quarterly obs with ncfo > 0", rank="none", added_in_version="1.1"),
    _f("ocf_positive_frac_12q", "trend", "T3", "numeric", "share of last 12 quarterly obs with ncfo > 0", rank="none", added_in_version="1.1"),
    _f("ocf_positive_frac_20q", "trend", "T5", "numeric", "share of last 20 quarterly obs with ncfo > 0", rank="none", added_in_version="1.1"),
    _f("fund_history_quarters", "trend", "T5", "numeric", "quarterly filings present in the 20q window", rank="none", added_in_version="1.1"),
    _f("div_years_paid_10y", "trend", "T10", "numeric", "fiscal years with -ncfdiv > 0, last 10", rank="none", added_in_version="1.1"),
    _f("div_streak_10y", "trend", "T10", "numeric", "consecutive paying years ending now, max 10", rank="none", added_in_version="1.1"),
    _f("div_cuts_10y", "trend", "T10", "numeric", "YoY TTM dividend drops below 0.8x prior, last 10y", rank="none", added_in_version="1.1"),
    _f("div_history_years_10y", "trend", "T10", "numeric", "annual dividend observations known, last 10", rank="none", added_in_version="1.1"),
    # ---- solvency / distress ----------------------------------------------
    _f("wc_to_assets", "solvency", "T0", "numeric", "workingcapital_q / assets_q"),
    _f("retearn_to_assets", "solvency", "T0", "numeric", "retearn_q / assets_q"),
    _f("ebit_to_assets", "solvency", "T0", "numeric", "ebit / assets_q"),
    _f("marketcap_to_liabilities", "solvency", "T0", "numeric", "marketcap / liabilities_q"),
    _f("equity_to_liabilities", "solvency", "T0", "numeric", "equity_q / liabilities_q"),
    _f("liabilities_to_assets", "solvency", "T0", "numeric", "liabilities_q / assets_q"),
    _f("cl_to_ca", "solvency", "T0", "numeric", "liabilitiesc_q / assetsc_q"),
    _f("current_ratio", "solvency", "T0", "numeric", "assetsc_q / liabilitiesc_q"),
    _f("quick_ratio", "solvency", "T0", "numeric", "(assetsc_q - inventory_q) / liabilitiesc_q"),
    _f("cash_to_assets", "solvency", "T0", "numeric", "cashneq_q / assets_q"),
    _f("debt_to_equity", "solvency", "T0", "numeric", "debt_q / equity_q", rank="pinned", pin_rank=0.0),
    _f("net_debt_to_ebitda", "solvency", "T0", "numeric", "(debt_q - cashneq_q) / ebitda"),
    _f("interest_coverage", "solvency", "T0", "numeric", "ebit / intexp"),
    _f("ffo_to_liabilities", "solvency", "T0", "numeric", "ncfo / liabilities_q"),
    _f("log_assets", "solvency", "T0", "numeric", "ln(assets_q)"),
    _f("ni_change_scaled", "solvency", "T1", "numeric", "(netinc - netinc[-1]) / (|netinc| + |netinc[-1]|)", rank="none"),
    _f("two_year_loss", "solvency", "T1", "flag", "netinc < 0 AND netinc[-1] < 0"),
    _f("liab_gt_assets", "solvency", "T0", "flag", "liabilities_q > assets_q"),
    _f("altman_z", "solvency", "T0", "numeric", "1.2 wc/ta + 1.4 re/ta + 3.3 ebit/ta + 0.6 mve/tl + 1.0 s/ta"),
    _f("altman_z_dd", "solvency", "T0", "numeric", "6.56 wc/ta + 3.26 re/ta + 6.72 ebit/ta + 1.05 bve/tl"),
    _f("zmijewski", "solvency", "T0", "numeric", "-4.336 - 4.513 roa + 5.679 tl/ta + 0.004 ca/cl"),
    # ---- earnings quality (Beneish inputs are ART pairs, T1) ---------------
    _f("dsri", "quality", "T1", "numeric", "(receivables_q/revenue) YoY ratio"),
    _f("gmi", "quality", "T1", "numeric", "gross_margin[-1] / gross_margin", rank="pinned", pin_value=1.0, pin_rank=0.5),
    _f("aqi", "quality", "T1", "numeric", "(1 - (assetsc_q + ppnenet_q)/assets_q) YoY ratio"),
    _f("sgi", "quality", "T1", "numeric", "revenue / revenue[-1]"),
    _f("depi", "quality", "T1", "numeric", "(depamor/(depamor + ppnenet_q)) YoY ratio, prior/current"),
    _f("sgai", "quality", "T1", "numeric", "(sgna/revenue) YoY ratio"),
    _f("lvgi", "quality", "T1", "numeric", "((debt_q + liabilitiesc_q)/assets_q) YoY ratio"),
    _f("accruals_to_assets", "quality", "T0", "numeric", "(netinc - ncfo) / assets_q", sector_rank=True),
    _f("beneish_m", "quality", "T1", "numeric", "Beneish M composite over the 8 indices"),
    _f("piotroski_f", "quality", "T1", "numeric", "count of the 9 F-score signals", rank="none"),
    _f("noa_to_assets", "quality", "T1", "numeric", "net operating assets / assets_q[-1]"),
    _f("ext_financing_to_assets", "quality", "T0", "numeric", "(ncfcommon + ncfdebt) / assets_q", rank="pinned", pin_rank=0.5),
    _f("rnd_to_assets", "quality", "T0", "numeric", "coalesce(rnd, 0) / assets_q (unreported R&D = 0, ADR 0013)", rank="pinned", pin_rank=0.0),
    _f("capex_to_assets", "quality", "T0", "numeric", "-capex / assets_q", rank="pinned", pin_rank=0.0),
    _f("roa_variability_3y", "quality", "T3", "numeric", "stddev of {roa, roa[-1], roa[-2], roa[-3]}"),
    _f("revenue_growth_variability_3y", "quality", "T3", "numeric", "stddev of the 3 YoY revenue growths"),
    _f("mohanram_g7", "quality", "T3", "numeric", "7-signal G-score vs. famaindustry medians", rank="none", assembly_stage=True),
    # ---- technical (from SEP; differs across snapshot kinds) ----------------
    _f("mom_12_2", "technical", "P12", "numeric", "total return t-252 -> t-21"),
    _f("ret_6m", "technical", "P12", "numeric", "total return t-126 -> t"),
    _f("ret_1m", "technical", "P12", "numeric", "total return t-21 -> t", rank="pinned", pin_rank=0.5),
    _f("vol_12m", "technical", "P12", "numeric", "ann. sigma of daily log returns, >=200 obs"),
    _f("vol_36m", "technical", "P36", "numeric", "ann. sigma over 756d, >=600 obs"),
    _f("dist_52w_high", "technical", "P12", "numeric", "closeadj / max_252d closeadj - 1", rank="pinned", pin_rank=1.0),
    _f("log_marketcap", "technical", "T0", "numeric", "ln(marketcap)"),
    _f("dollar_volume_3m", "technical", "P12", "numeric", "median daily close*volume, t-63 -> t"),
    _f("amihud_12m", "technical", "P12", "numeric", "mean |ret| / (close*volume)"),
    _f("conservative_score", "technical", "P36", "numeric", "rank-sum of vol_36m (low), mom_12_2 (high), net_payout_yield (high)", assembly_stage=True),
    # ---- classification (TICKERS; current-state, not ranked) ----------------
    _f("sector", "classification", None, "categorical", "Sharadar sector"),
    _f("industry", "classification", None, "categorical", "Sharadar industry"),
    _f("famaindustry", "classification", None, "categorical", "Fama-French 48-style industry"),
    _f("scalemarketcap", "classification", None, "categorical", "Sharadar size bucket"),
    _f("siccode", "classification", None, "categorical", "SIC code (era-stable industry fallback)"),
)


def family_features(
    family: str, *, include_assembly_stage: bool = False
) -> tuple[FeatureSpec, ...]:
    if family not in FAMILIES:
        known = ", ".join(FAMILIES)
        raise KeyError(f"unknown feature family {family!r}; known families: {known}")
    return tuple(
        spec
        for spec in FEATURES
        if spec.family == family
        and (include_assembly_stage or not spec.assembly_stage)
    )


def family_columns(family: str) -> tuple[str, ...]:
    """Column names a family parquet must emit (assembly-stage excluded)."""
    return tuple(spec.name for spec in family_features(family))
