"""The wide feature table: join, composites, and rank passes.

View chain (each a pure-SQL temp view over the previous):

    wide_raw       labels_src ⋈ the eight feat_{family} views (inner, on the
                   shared snapshot key)
    wide_g         + mohanram_g7 from famaindustry medians (decision 0013)
    wide_r1        + {name}_rank / {name}_secrank for every registry numeric
                   except conservative_score (decision 0008 mechanics)
    wide_r2        + conservative_score from the pass-1 ranks
    wide_features  + conservative_score_rank

Rank rule (decision 0008): `percent_rank()` within (calendar quarter,
snapshot_kind) — plus Sharadar `sector` for the `_secrank` allowlist — over
non-NULL values only, NULL raw ⇒ NULL rank, cross-sections with fewer than
`rank_guard` non-NULL values ⇒ NULL rank.
"""

from __future__ import annotations

import duckdb

from features.registry import FAMILIES, FEATURES, family_features

from .source import family_view, key_meta_columns, label_matrix_columns

# ADR 0008: minimum non-null cross-section for any rank to be emitted.
RANK_GUARD = 20
# ADR 0013: minimum non-null famaindustry cross-section per G-score median.
MIN_INDUSTRY_PEERS = 5

# The conservative-formula composite is built *from* rank columns, so it is
# ranked in a second pass (ADR 0013).
CONSERVATIVE = "conservative_score"

# (feature, industry-median comparison direction) per Mohanram signal that
# uses a median; the accruals signal (cfo > roa) is firm-level (ADR 0013).
MOHANRAM_MEDIAN_SIGNALS: tuple[tuple[str, str], ...] = (
    ("roa", ">"),
    ("cfo_to_assets", ">"),
    ("roa_variability_3y", "<"),
    ("revenue_growth_variability_3y", "<"),
    ("rnd_to_assets", ">"),
    ("capex_to_assets", ">"),
)


def feature_columns_in_order() -> tuple[str, ...]:
    """All feature columns, family build order, assembly-stage in place."""
    return tuple(
        spec.name
        for family in FAMILIES
        for spec in family_features(family, include_assembly_stage=True)
    )


def numeric_feature_names() -> tuple[str, ...]:
    return tuple(s.name for s in FEATURES if s.kind == "numeric")


def rank_columns() -> tuple[str, ...]:
    return tuple(f"{name}_rank" for name in numeric_feature_names())


def secrank_columns() -> tuple[str, ...]:
    return tuple(f"{s.name}_secrank" for s in FEATURES if s.sector_rank)


def _rank_expr(col: str, partition: str, guard: int) -> str:
    return (
        f"CASE WHEN {col} IS NOT NULL"
        f" AND count({col}) OVER (PARTITION BY {partition}) >= {int(guard)}"
        f" THEN percent_rank() OVER ("
        f"PARTITION BY {partition}, {col} IS NULL ORDER BY {col}) END"
    )


def build_wide_views(
    con: duckdb.DuckDBPyConnection,
    *,
    rank_guard: int = RANK_GUARD,
    min_industry_peers: int = MIN_INDUSTRY_PEERS,
) -> None:
    """Create the wide_raw → wide_features view chain."""
    # -- wide_raw: labels ⋈ families ------------------------------------
    select = [f"l.{c}" for c in key_meta_columns(con) + label_matrix_columns(con)]
    joins = []
    for family in FAMILIES:
        select += [
            f"{family_view(family)}.{spec.name}"
            for spec in family_features(family)
        ]
        joins.append(
            f"JOIN {family_view(family)}"
            " USING (permaticker, snapshot_date, snapshot_kind)"
        )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW wide_raw AS
        SELECT {", ".join(select)}
        FROM labels_src l
        {" ".join(joins)}
        """
    )

    # -- wide_g: mohanram_g7 (ADR 0013) ---------------------------------
    med_selects = ", ".join(
        f"CASE WHEN count({col}) >= {int(min_industry_peers)} "
        f"THEN median({col}) END AS med_{col}"
        for col, _ in MOHANRAM_MEDIAN_SIGNALS
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW industry_medians AS
        SELECT quarter, snapshot_kind, famaindustry, {med_selects}
        FROM wide_raw
        WHERE famaindustry IS NOT NULL
        GROUP BY quarter, snapshot_kind, famaindustry
        """
    )
    signals = [
        f"CAST(w.{col} {op} m.med_{col} AS INTEGER)"
        for col, op in MOHANRAM_MEDIAN_SIGNALS
    ]
    signals.insert(2, "CAST(w.cfo_to_assets > w.roa AS INTEGER)")
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW wide_g AS
        SELECT w.*, {" + ".join(signals)} AS mohanram_g7
        FROM wide_raw w
        LEFT JOIN industry_medians m
          USING (quarter, snapshot_kind, famaindustry)
        """
    )

    # -- wide_r1: registry-driven ranks + sector ranks ------------------
    qk = "quarter, snapshot_kind"
    rank_selects = [
        f"{_rank_expr(name, qk, rank_guard)} AS {name}_rank"
        for name in numeric_feature_names()
        if name != CONSERVATIVE
    ] + [
        f"CASE WHEN sector IS NOT NULL THEN "
        f"{_rank_expr(spec.name, qk + ', sector', rank_guard)} END"
        f" AS {spec.name}_secrank"
        for spec in FEATURES
        if spec.sector_rank
    ]
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW wide_r1 AS
        SELECT *, {", ".join(rank_selects)} FROM wide_g
        """
    )

    # -- wide_r2 + wide_features: the conservative formula (ADR 0013) ----
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW wide_r2 AS
        SELECT *,
               (1 - vol_36m_rank) + mom_12_2_rank + net_payout_yield_rank
                   AS {CONSERVATIVE}
        FROM wide_r1
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW wide_features AS
        SELECT *, {_rank_expr(CONSERVATIVE, qk, rank_guard)}
                      AS {CONSERVATIVE}_rank
        FROM wide_r2
        """
    )
