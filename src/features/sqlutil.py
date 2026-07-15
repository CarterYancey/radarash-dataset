"""SQL expression helpers shared by the family modules."""

from __future__ import annotations


def safe_div(num: str, den: str) -> str:
    """Registry null rule: a ratio is NULL unless its denominator is > 0.

    Covers both cases in docs/features.md — market denominators (marketcap,
    ev) and fundamental denominators — and lets negative *numerators* pass
    through (yield orientation, ADR 0005 §4). NULL inputs propagate to NULL.
    """
    return f"CASE WHEN ({den}) > 0 THEN ({num}) / ({den}) END"


def safe_ln(arg: str) -> str:
    """ln(x), NULL for non-positive or missing x."""
    return f"CASE WHEN ({arg}) > 0 THEN ln({arg}) END"
