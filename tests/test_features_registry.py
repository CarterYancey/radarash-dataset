"""The registry contract: src/features/registry.py is 1:1 with docs/features.md.

Parses the markdown feature tables (one section per family) and compares
names, order, depth tiers, sector-rank markers, rank policy markers
("not ranked" / "pinned rank (r [at raw v])", ADR 0016) and assembly-stage notes
against the code registry.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from features.registry import FAMILIES, FEATURES, FeatureSpec, family_features

DOC_PATH = Path(__file__).resolve().parents[1] / "docs" / "features.md"

SECTION_FAMILIES = {
    "Meta": "meta",
    "Valuation": "valuation",
    "Profitability": "profitability",
    "Growth & trends": "growth",
    "Trend & consistency": "trend",
    "Solvency / distress": "solvency",
    "Earnings quality": "quality",
    "Technical": "technical",
    "Classification": "classification",
}


def parse_doc_rows() -> list[dict]:
    """Feature rows from docs/features.md: name, family, tier, S, assembly."""
    rows: list[dict] = []
    family = None
    for line in DOC_PATH.read_text().splitlines():
        if line.startswith("## "):
            heading = line[3:].strip()
            family = next(
                (
                    fam
                    for title, fam in SECTION_FAMILIES.items()
                    if heading == title or heading.startswith(title + " (")
                ),
                None,
            )
            continue
        if family is None or not line.startswith("| `"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        names = re.findall(r"`([a-z_][a-z0-9_]*)`", cells[0])
        tier = None
        if family != "classification":
            tier = cells[1].split()[0] if cells[1] else None
        notes = cells[-1]
        # "S" marks the sector-rank allowlist; it must not match prose that
        # merely starts with the letter (e.g. "S is not applied").
        sector = bool(re.match(r"S(;|$)", notes))
        assembly = "assembly-stage" in notes
        pinned = re.search(
            r"pinned rank \(([0-9.]+)(?: at raw ([-0-9.]+))?\)", notes
        )
        if "not ranked" in notes:
            rank, pin_rank, pin_value = "none", 0.0, 0.0
        elif pinned:
            rank = "pinned"
            pin_rank = float(pinned.group(1))
            pin_value = float(pinned.group(2) or 0.0)
        else:
            rank, pin_rank, pin_value = "full", 0.0, 0.0
        for name in names:
            rows.append(
                {
                    "name": name,
                    "family": family,
                    "tier": tier,
                    "sector_rank": sector,
                    "assembly_stage": assembly,
                    "rank": rank,
                    "pin_rank": pin_rank,
                    "pin_value": pin_value,
                }
            )
    return rows


def test_doc_and_registry_names_match_per_family():
    doc_rows = parse_doc_rows()
    for family in FAMILIES:
        doc_names = [r["name"] for r in doc_rows if r["family"] == family]
        reg_names = [
            s.name for s in family_features(family, include_assembly_stage=True)
        ]
        assert doc_names == reg_names, f"family {family} out of sync with doc"


def test_doc_and_registry_attributes_match():
    by_name = {s.name: s for s in FEATURES}
    doc_rows = parse_doc_rows()
    assert len(doc_rows) == len(FEATURES)
    for row in doc_rows:
        spec = by_name[row["name"]]
        assert spec.tier == row["tier"], row["name"]
        assert spec.sector_rank == row["sector_rank"], row["name"]
        assert spec.assembly_stage == row["assembly_stage"], row["name"]
        if spec.kind == "numeric":
            assert spec.rank == row["rank"], row["name"]
            assert spec.pin_rank == row["pin_rank"], row["name"]
            assert spec.pin_value == row["pin_value"], row["name"]


def test_flags_and_classification_are_never_ranked():
    for spec in FEATURES:
        if spec.kind in ("flag", "categorical", "metadata"):
            assert spec.rank == "none", spec.name
            assert not spec.ranked and not spec.sector_rank, spec.name


def test_rank_policy_adr_0016():
    """Integer-valued composites, counts and shares are never ranked; the
    documented mass-point features are pinned at the documented value/rank."""
    by_name = {s.name: s for s in FEATURES}
    unranked = {
        "fundamentals_age_days", "piotroski_f", "mohanram_g7",
        "fund_history_quarters", "div_years_paid_10y", "div_streak_10y",
        "div_cuts_10y", "div_history_years_10y", "ni_change_scaled",
    } | {
        f"{series}_up_frac_{w}q"
        for series in ("revenue", "tangibles", "ocf")
        for w in (4, 8, 12, 20)
    } | {f"ocf_positive_frac_{w}q" for w in (4, 8, 12, 20)}
    assert {s.name for s in FEATURES if s.kind == "numeric" and s.rank == "none"} == unranked

    pinned = {  # name: (pin_value, pin_rank)
        "sales_yield": (0.0, 0.0), "dividend_yield": (0.0, 0.0),
        "net_payout_yield": (0.0, 0.5), "asset_turnover": (0.0, 0.0),
        "share_count_growth_1y": (0.0, 0.5), "debt_to_equity": (0.0, 0.0),
        "ext_financing_to_assets": (0.0, 0.5), "rnd_to_assets": (0.0, 0.0),
        "capex_to_assets": (0.0, 0.0), "dist_52w_high": (0.0, 1.0),
        "gp_to_assets": (0.0, 0.5), "asset_turnover_delta_1y": (0.0, 0.5),
        "gross_margin_delta_1y": (0.0, 0.5),
        "gross_margin_delta_2y": (0.0, 0.5), "ret_1m": (0.0, 0.5),
        # masses at raw 1: no cost of revenue / unchanged margin / no net debt
        "gross_margin": (1.0, 1.0), "gmi": (1.0, 0.5),
        "ev_to_marketcap": (1.0, 0.5),
    }
    assert {
        s.name: (s.pin_value, s.pin_rank) for s in FEATURES if s.rank == "pinned"
    } == pinned
    # Everything else numeric is a full percent rank.
    for spec in FEATURES:
        if spec.kind == "numeric" and spec.name not in unranked | set(pinned):
            assert spec.rank == "full", spec.name
    # A sector rank needs a rank policy; the spec constructor enforces it.
    assert all(by_name[n].ranked for n in by_name if by_name[n].sector_rank)
    with pytest.raises(ValueError):
        FeatureSpec("x", "valuation", "T0", "numeric", "d", rank="none", sector_rank=True)
    with pytest.raises(ValueError):
        FeatureSpec("x", "meta", "T0", "flag", "d", rank="full")
    with pytest.raises(ValueError):
        FeatureSpec("x", "valuation", "T0", "numeric", "d", pin_rank=0.5)
    with pytest.raises(ValueError):
        FeatureSpec("x", "valuation", "T0", "numeric", "d", pin_value=1.0)


def test_sector_rank_allowlist_matches_adr_0008():
    allow = {s.name for s in FEATURES if s.sector_rank}
    assert allow == {
        "earnings_yield", "ocf_yield", "fcf_yield", "sales_yield",
        "book_to_market", "tangible_book_to_market", "ebit_to_ev",
        "ebitda_to_ev", "gp_to_assets", "gross_margin", "operating_margin",
        "net_margin", "accruals_to_assets",
    }
