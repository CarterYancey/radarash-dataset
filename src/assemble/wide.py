"""The wide feature table: join, composites, and rank passes.

View chain (each a pure-SQL temp view over the previous):

    wide_raw       labels_src ⋈ the eight feat_{family} views (inner, on the
                   shared snapshot key)
    wide_g         + mohanram_g7 from famaindustry medians (decision 0013)
    wide_r1        + {name}_rank / {name}_secrank for every registry feature
                   whose rank policy is not "none", except conservative_score
                   (decision 0008 mechanics, decision 0016 policy)
    wide_r2        + conservative_score from the pass-1 ranks
    wide_features  + conservative_score_rank

Rank rule (decision 0008): `percent_rank()` within (calendar quarter,
snapshot_kind) — plus Sharadar `sector` for the `_secrank` allowlist — over
non-NULL values only, NULL raw ⇒ NULL rank, cross-sections with fewer than
`rank_guard` non-NULL values ⇒ NULL rank.

Per-feature policy (decision 0016, `FeatureSpec.rank`): `full` is the rule
above; `pinned` gives rows at exactly `pin_value` (the mass, usually 0) the
fixed rank `pin_rank` and percent-ranks the rest within their side of the
pin onto the matching interval (below in [0, pin_rank], above in
[pin_rank, 1]), so the mass's rank is a constant instead of the quarter's
share below it; `none` emits no rank column at all (integer-valued
composites, counts and shares, whose tied groups would each carry a
quarter-specific constant).
"""

from __future__ import annotations

import duckdb

from features.registry import FAMILIES, FEATURES, FeatureSpec, family_features

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


def ranked_features() -> tuple[FeatureSpec, ...]:
    """Specs that get a `{name}_rank` column (rank policy other than none)."""
    return tuple(s for s in FEATURES if s.ranked)


def rank_columns() -> tuple[str, ...]:
    return tuple(f"{s.name}_rank" for s in ranked_features())


def secrank_columns() -> tuple[str, ...]:
    return tuple(f"{s.name}_secrank" for s in FEATURES if s.sector_rank)


def rank_policy() -> dict[str, dict[str, object]]:
    """Manifest view of the policy: every ranked feature's rank + pin."""
    return {
        s.name: (
            {"rank": s.rank, "pin_value": s.pin_value, "pin_rank": s.pin_rank}
            if s.rank == "pinned"
            else {"rank": s.rank}
        )
        for s in ranked_features()
    }


def _rank_expr(spec: FeatureSpec, partition: str, guard: int) -> str:
    """The rank SQL for one feature under its policy (module docstring)."""
    col = spec.name
    guarded = (
        f"{col} IS NOT NULL"
        f" AND count({col}) OVER (PARTITION BY {partition}) >= {int(guard)}"
    )
    if spec.rank == "full":
        return (
            f"CASE WHEN {guarded} THEN percent_rank() OVER ("
            f"PARTITION BY {partition}, {col} IS NULL ORDER BY {col}) END"
        )
    if spec.rank == "pinned":
        # sign(col - pin) partitions NULL / below / at / above the pin apart,
        # so each side is percent-ranked on its own; the pin's own rank is
        # unused.
        v = repr(float(spec.pin_value))
        pr = (
            f"percent_rank() OVER ("
            f"PARTITION BY {partition}, sign({col} - {v}) ORDER BY {col})"
        )
        r = repr(float(spec.pin_rank))
        return (
            f"CASE WHEN {guarded} THEN CASE"
            f" WHEN {col} = {v} THEN {r}"
            f" WHEN {col} < {v} THEN {r} * {pr}"
            f" ELSE {r} + (1 - {r}) * {pr} END END"
        )
    raise ValueError(f"{col}: rank policy {spec.rank!r} has no rank column")


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
        f"{_rank_expr(spec, qk, rank_guard)} AS {spec.name}_rank"
        for spec in ranked_features()
        if spec.name != CONSERVATIVE
    ] + [
        f"CASE WHEN sector IS NOT NULL THEN "
        f"{_rank_expr(spec, qk + ', sector', rank_guard)} END"
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
    conservative = next(s for s in FEATURES if s.name == CONSERVATIVE)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW wide_features AS
        SELECT *, {_rank_expr(conservative, qk, rank_guard)}
                      AS {CONSERVATIVE}_rank
        FROM wide_r2
        """
    )
