"""The registry contract: src/features/registry.py is 1:1 with docs/features.md.

Parses the markdown feature tables (one section per family) and compares
names, order, depth tiers, sector-rank markers, and assembly-stage notes
against the code registry.
"""

from __future__ import annotations

import re
from pathlib import Path

from features.registry import FAMILIES, FEATURES, family_features

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
        for name in names:
            rows.append(
                {
                    "name": name,
                    "family": family,
                    "tier": tier,
                    "sector_rank": sector,
                    "assembly_stage": assembly,
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


def test_flags_and_classification_are_never_ranked():
    for spec in FEATURES:
        if spec.kind in ("flag", "categorical", "metadata"):
            assert not spec.ranked and not spec.sector_rank, spec.name


def test_sector_rank_allowlist_matches_adr_0008():
    allow = {s.name for s in FEATURES if s.sector_rank}
    assert allow == {
        "earnings_yield", "ocf_yield", "fcf_yield", "sales_yield",
        "book_to_market", "tangible_book_to_market", "ebit_to_ev",
        "ebitda_to_ev", "gp_to_assets", "gross_margin", "operating_margin",
        "net_margin", "accruals_to_assets",
    }
