"""Splits diagnostics — PLAN §7's empirical questions, measured (§7.7).

Answers, with numbers instead of argument, the questions raised when the §7
methodology was challenged (research workspace: docs/research/splits.md,
decision 0010):

- **Q1/Q2 (features):** which features actually differ across the three
  same-quarter snapshot kinds, and by how much? Fundamental-only features
  should be constant within a (stock, quarter) except when a filing lands
  between two kinds' dates (`filing_straddle` counts those); price-touching
  features should differ whenever the kind dates differ.
- **Q2 (labels):** how much of forward-return variance is the within-quarter
  entry-price gradient vs. shared structure — the same-stock serial overlap
  and same-date cross-sectional overlap of §7.1? Plus the low/high label
  flip rate: how often the margin-of-safety gradient actually flips a
  binary label.
- **Q3 (row uniqueness):** the twin test — for a sample of rows, find the
  nearest neighbor in rank-feature space and ask whether it is a same-stock
  neighbor quarter or a same-date peer, and how correlated the labels of
  near-twins are vs. random pairs. This directly sizes the "memorize the
  AAPL-2015 neighborhood" channel.
- **Purge cost:** per horizon and candidate test boundary, how many training
  rows the `snapshot_date + horizon + embargo < test_start` rule burns
  (§7.2). Unweighted counts; uniqueness-weighted effective sample sizes are
  added once M5 defines `sample_weight`.

All views are aggregate diagnostics over labels/features that already exist;
nothing here feeds the dataset itself.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import duckdb

from features.registry import FAMILIES, family_features
from identity.source import sql_quote

logger = logging.getLogger(__name__)

HORIZONS: tuple[tuple[str, int], ...] = (("1y", 1), ("2y", 2), ("3y", 3), ("5y", 5))
THRESHOLDS_PCT: tuple[int, ...] = (0, 5, 8, 10)
SERIAL_LAGS: tuple[int, ...] = (1, 2, 3, 4)
DEFAULT_EMBARGO_DAYS = 30
DEFAULT_TWIN_SAMPLE = 1000

# Rank-space axes for the twin test: broad-coverage numeric features spanning
# the families (raw values are percent-ranked within calendar quarter, per
# the ADR-0008 convention; assembly-stage ranks don't exist yet at QA time).
TWIN_FEATURES: tuple[tuple[str, str], ...] = (
    ("valuation", "earnings_yield"),
    ("valuation", "book_to_market"),
    ("valuation", "sales_yield"),
    ("profitability", "gp_to_assets"),
    ("profitability", "asset_turnover"),
    ("solvency", "liabilities_to_assets"),
    ("solvency", "cash_to_assets"),
    ("quality", "accruals_to_assets"),
    ("technical", "ret_6m"),
    ("technical", "vol_12m"),
    ("technical", "dist_52w_high"),
    ("technical", "log_marketcap"),
)


def required_families() -> tuple[str, ...]:
    """Families whose parquets the diagnostics read (all with numeric/flag
    columns — classification is categorical-only and unused here)."""
    return tuple(
        fam
        for fam in FAMILIES
        if any(s.kind in ("numeric", "flag") for s in family_features(fam))
    )


def create_splits_source_views(
    con: duckdb.DuckDBPyConnection,
    *,
    snapshots_parquet: Path,
    labels_parquet: Path,
    features_dir: Path,
) -> None:
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW snapshots_all AS
        SELECT permaticker, quarter, snapshot_kind, snapshot_date
        FROM read_parquet({sql_quote(str(snapshots_parquet))})
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW labels_all AS
        SELECT * FROM read_parquet({sql_quote(str(labels_parquet))})
        """
    )
    for family in required_families():
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW feat_{family} AS
            SELECT * FROM read_parquet(
                {sql_quote(str(features_dir / f"{family}.parquet"))})
            """
        )

    # Long form of every numeric/flag feature (UNPIVOT drops NULLs, so group
    # counts below reflect present values only).
    branches = []
    for family in required_families():
        specs = [
            s for s in family_features(family) if s.kind in ("numeric", "flag")
        ]
        casts = ", ".join(
            f"{s.name}::DOUBLE AS {s.name}"
            if s.kind == "numeric"
            else f"{s.name}::INT::DOUBLE AS {s.name}"
            for s in specs
        )
        cols = ", ".join(s.name for s in specs)
        branches.append(
            f"""
            SELECT permaticker, snapshot_date, snapshot_kind,
                   '{family}' AS family, feature, value
            FROM (
                SELECT permaticker, snapshot_date, snapshot_kind, {casts}
                FROM feat_{family}
            ) UNPIVOT (value FOR feature IN ({cols}))
            """
        )
    con.execute(
        "CREATE OR REPLACE TEMP VIEW feature_long AS "
        + " UNION ALL ".join(branches)
    )

    # Per-horizon labeled slices used by several views below.
    for tag, _years in HORIZONS:
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW labeled_{tag} AS
            SELECT permaticker, quarter, fwd_{tag}_cagr AS y
            FROM labels_all WHERE fwd_{tag}_cagr IS NOT NULL
            """
        )
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW labeled_median_{tag} AS
            SELECT permaticker, quarter, fwd_{tag}_cagr AS y
            FROM labels_all
            WHERE snapshot_kind = 'median' AND fwd_{tag}_cagr IS NOT NULL
            """
        )


def build_feature_variance_views(con: duckdb.DuckDBPyConnection) -> None:
    """Q1/Q2, feature side: intra-quarter variation across snapshot kinds."""
    # A group is a (feature, permaticker, quarter) with >= 2 present values;
    # rel_range = (max - min) / |discrete median|, the spread of the three
    # kind values in units of the typical value.
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW feature_intraquarter AS
        SELECT family, feature,
               count(*) AS groups,
               round(avg((vmax > vmin)::INT), 4) AS frac_groups_differ,
               round(median(CASE WHEN vmax > vmin THEN
                   (vmax - vmin) / nullif(abs(vmed), 0) END), 4)
                   AS median_rel_range
        FROM (
            SELECT family, feature, f.permaticker, s.quarter,
                   min(value) AS vmin, max(value) AS vmax,
                   quantile_disc(value, 0.5) AS vmed
            FROM feature_long f
            JOIN snapshots_all s
                USING (permaticker, snapshot_date, snapshot_kind)
            GROUP BY family, feature, f.permaticker, s.quarter
            HAVING count(*) >= 2
        )
        GROUP BY family, feature
        ORDER BY frac_groups_differ DESC, family, feature
        """
    )
    # Straddles: quarters whose kinds resolve to different filings (decision
    # 0001 — a datekey landing between two kind dates). NULL datekeys count
    # as a distinct state so "first filing arrives mid-quarter" straddles too.
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW filing_straddle AS
        SELECT count(*) AS stock_quarters,
               sum(straddled::INT) AS straddled_quarters,
               round(avg(straddled::INT), 4) AS frac_straddled
        FROM (
            SELECT m.permaticker, s.quarter,
                   count(DISTINCT coalesce(m.fund_datekey, DATE '0001-01-01'))
                       > 1 AS straddled
            FROM feat_meta m
            JOIN snapshots_all s
                USING (permaticker, snapshot_date, snapshot_kind)
            GROUP BY m.permaticker, s.quarter
        )
        """
    )


def build_label_structure_views(con: duckdb.DuckDBPyConnection) -> None:
    """Q2, label side: within-quarter spread vs. shared structure (§7.1)."""
    flips = []
    for tag, _years in HORIZONS:
        label_cols = [f"cagr_ge_{pct}" for pct in THRESHOLDS_PCT] + ["beat_spy"]
        for short in label_cols:
            col = f"label_{tag}_{short}"
            flips.append(
                f"""
                SELECT '{tag}' AS horizon, '{short}' AS label,
                       count(*) AS groups,
                       round(avg((lo <> hi)::INT), 4) AS frac_flip
                FROM (
                    SELECT permaticker, quarter,
                           max(CASE WHEN snapshot_kind = 'low'
                               THEN {col}::INT END) AS lo,
                           max(CASE WHEN snapshot_kind = 'high'
                               THEN {col}::INT END) AS hi
                    FROM labels_all
                    GROUP BY permaticker, quarter
                ) WHERE lo IS NOT NULL AND hi IS NOT NULL
                """
            )
    con.execute(
        "CREATE OR REPLACE TEMP VIEW label_kind_flip AS "
        + " UNION ALL ".join(flips)
    )

    # Exact ANOVA shares: sum-of-squares within (stock, quarter) groups over
    # total (all kinds) = how much of label variance the entry-price gradient
    # explains; 1 - within-quarter share on median rows = the calendar-quarter
    # fixed effect (cross-sectional overlap, §7.1).
    decomp = []
    for tag, _years in HORIZONS:
        decomp.append(
            f"""
            SELECT '{tag}' AS horizon,
                   t.n AS rows_all_kinds,
                   round(t.v, 6) AS var_all_kinds,
                   round(w.within_ss / nullif(t.n * t.v, 0), 4)
                       AS within_stock_quarter_share,
                   m.n AS rows_median,
                   round(m.v, 6) AS var_median,
                   round(1 - q.within_q_ss / nullif(m.n * m.v, 0), 4)
                       AS quarter_fe_share
            FROM (SELECT count(*) AS n, coalesce(var_pop(y), 0) AS v
                  FROM labeled_{tag}) t,
                 (SELECT coalesce(sum(ng * vg), 0) AS within_ss FROM (
                      SELECT count(*) AS ng, var_pop(y) AS vg
                      FROM labeled_{tag} GROUP BY permaticker, quarter)) w,
                 (SELECT count(*) AS n, coalesce(var_pop(y), 0) AS v
                  FROM labeled_median_{tag}) m,
                 (SELECT coalesce(sum(nq * vq), 0) AS within_q_ss FROM (
                      SELECT count(*) AS nq, var_pop(y) AS vq
                      FROM labeled_median_{tag} GROUP BY quarter)) q
            """
        )
    con.execute(
        "CREATE OR REPLACE TEMP VIEW label_variance_decomposition AS "
        + " UNION ALL ".join(decomp)
    )

    serial = []
    for tag, _years in HORIZONS:
        for lag in SERIAL_LAGS:
            serial.append(
                f"""
                SELECT '{tag}' AS horizon, {lag} AS lag_quarters,
                       count(*) AS pairs,
                       round(CASE WHEN isnan(corr(a.y, b.y)) THEN NULL
                             ELSE corr(a.y, b.y) END, 4) AS label_corr
                FROM labeled_median_{tag} a
                JOIN labeled_median_{tag} b
                  ON b.permaticker = a.permaticker
                 AND b.quarter = (a.quarter + INTERVAL '{3 * lag} months')::DATE
                """
            )
    con.execute(
        "CREATE OR REPLACE TEMP VIEW label_serial_correlation AS "
        + " UNION ALL ".join(serial)
    )


def build_twin_views(
    con: duckdb.DuckDBPyConnection, *, sample_size: int = DEFAULT_TWIN_SAMPLE
) -> None:
    """Q3: nearest neighbors in rank-feature space, vs. random pairs."""
    aliases = {family: f"t{i}" for i, family in
               enumerate(sorted({fam for fam, _col in TWIN_FEATURES}))}
    cols = [
        f"{aliases[fam]}.{col} AS f{i}"
        for i, (fam, col) in enumerate(TWIN_FEATURES)
    ]
    joins = "\n".join(
        f"JOIN feat_{fam} {alias} USING (permaticker, snapshot_date, snapshot_kind)"
        for fam, alias in aliases.items()
    )
    not_null = " AND ".join(
        f"{aliases[fam]}.{col} IS NOT NULL" for fam, col in TWIN_FEATURES
    )
    ranks = ", ".join(
        f"percent_rank() OVER (PARTITION BY quarter ORDER BY f{i}) AS r{i}"
        for i in range(len(TWIN_FEATURES))
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW twin_space AS
        SELECT permaticker, quarter, snapshot_date, {ranks}
        FROM (
            SELECT s.permaticker, s.quarter, s.snapshot_date,
                   {", ".join(cols)}
            FROM snapshots_all s
            {joins}
            WHERE s.snapshot_kind = 'median' AND {not_null}
        )
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW twin_sample AS
        SELECT * FROM twin_space
        ORDER BY hash(concat(permaticker, '#', snapshot_date))
        LIMIT {int(sample_size)}
        """
    )

    dist = " + ".join(
        f"(s.r{i} - c.r{i}) * (s.r{i} - c.r{i})"
        for i in range(len(TWIN_FEATURES))
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW twin_pairs AS
        SELECT *,
               CASE WHEN permaticker = nn_permaticker
                     AND abs(date_diff('month', quarter, nn_quarter)) <= 12
                    THEN 'same_stock_within_1y'
                    WHEN permaticker = nn_permaticker
                    THEN 'same_stock_distant'
                    WHEN quarter = nn_quarter THEN 'same_quarter_peer'
                    ELSE 'unrelated' END AS nn_relation
        FROM (
            SELECT s.permaticker, s.quarter, s.snapshot_date,
                   c.permaticker AS nn_permaticker,
                   c.quarter AS nn_quarter,
                   c.snapshot_date AS nn_snapshot_date,
                   {dist} AS dist2,
                   row_number() OVER (
                       PARTITION BY s.permaticker, s.snapshot_date
                       ORDER BY {dist}, c.permaticker, c.snapshot_date
                   ) AS rn
            FROM twin_sample s
            JOIN twin_space c
              ON NOT (c.permaticker = s.permaticker
                      AND c.quarter = s.quarter)
        ) WHERE rn = 1
        """
    )
    # Deterministic random partner per sampled row (different hash salt than
    # the sampling order), same own-(stock, quarter) exclusion as the NN.
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW twin_random_pairs AS
        WITH numbered AS (
            SELECT *, row_number() OVER (
                ORDER BY hash(concat(permaticker, '#', snapshot_date))) AS rn
            FROM twin_space
        ), total AS (SELECT count(*) AS n FROM numbered)
        SELECT s.permaticker, s.quarter, s.snapshot_date,
               c.permaticker AS nn_permaticker, c.quarter AS nn_quarter,
               c.snapshot_date AS nn_snapshot_date
        FROM twin_sample s
        CROSS JOIN total
        JOIN numbered c
          ON c.rn = 1 + (hash(concat(s.permaticker, '@', s.snapshot_date))
                         % total.n)::BIGINT
        WHERE NOT (c.permaticker = s.permaticker AND c.quarter = s.quarter)
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW twin_relations AS
        SELECT nn_relation, count(*) AS pairs,
               round(count(*) / sum(count(*)) OVER (), 4) AS share,
               round(avg(dist2), 4) AS mean_dist2
        FROM twin_pairs
        GROUP BY nn_relation
        ORDER BY pairs DESC
        """
    )
    corrs = []
    for tag, _years in HORIZONS:
        for pairing, view in (("nearest", "twin_pairs"),
                              ("random", "twin_random_pairs")):
            corrs.append(
                f"""
                SELECT '{tag}' AS horizon, '{pairing}' AS pairing,
                       count(*) AS labeled_pairs,
                       round(CASE WHEN isnan(corr(la.y, lb.y)) THEN NULL
                             ELSE corr(la.y, lb.y) END, 4) AS label_corr,
                       round(avg(abs(la.y - lb.y)), 4) AS mean_abs_diff
                FROM {view} p
                JOIN labeled_median_{tag} la
                  ON la.permaticker = p.permaticker
                 AND la.quarter = p.quarter
                JOIN labeled_median_{tag} lb
                  ON lb.permaticker = p.nn_permaticker
                 AND lb.quarter = p.nn_quarter
                """
            )
    con.execute(
        "CREATE OR REPLACE TEMP VIEW twin_label_corr AS "
        + " UNION ALL ".join(corrs)
    )


def default_test_starts(con: duckdb.DuckDBPyConnection) -> list[date]:
    """Yearly Jan-1 boundaries from two years after the first snapshot year
    through the last snapshot year."""
    lo, hi = con.execute(
        """
        SELECT min(extract(year FROM snapshot_date))::INT,
               max(extract(year FROM snapshot_date))::INT
        FROM snapshots_all
        """
    ).fetchone()
    if lo is None:
        return []
    return [date(year, 1, 1) for year in range(lo + 2, hi + 1)]


def build_purge_cost_view(
    con: duckdb.DuckDBPyConnection,
    *,
    test_starts: list[date],
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
) -> None:
    """§7.2 pricing: rows the eligibility rule keeps/burns per boundary.

    `train_pool_rows` is everything before the boundary (all snapshot kinds),
    `eligible_rows` satisfies `snapshot_date + horizon + embargo < test_start`,
    `purged_rows` is the difference; `test_rows_1y_window` counts the
    median-kind rows in the year after the boundary (low/high kinds are
    training-only, decision 0001)."""
    bounds = ", ".join(f"(DATE '{d.isoformat()}')" for d in test_starts)
    hz = ", ".join(f"('{tag}', {years})" for tag, years in HORIZONS)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW purge_cost AS
        SELECT test_start, horizon, train_pool_rows, eligible_rows,
               purged_rows,
               round(purged_rows / nullif(train_pool_rows, 0)::DOUBLE, 4)
                   AS frac_pool_purged,
               test_rows_1y_window
        FROM (
            WITH bounds(test_start) AS (VALUES {bounds}),
                 hz(horizon, years) AS (VALUES {hz})
            SELECT b.test_start, h.horizon,
                   count(*) FILTER (
                       WHERE s.snapshot_date < b.test_start
                   ) AS train_pool_rows,
                   count(*) FILTER (
                       WHERE s.snapshot_date + to_years(h.years)
                             + to_days({int(embargo_days)}) < b.test_start
                   ) AS eligible_rows,
                   count(*) FILTER (
                       WHERE s.snapshot_date < b.test_start
                         AND NOT (s.snapshot_date + to_years(h.years)
                                  + to_days({int(embargo_days)})
                                  < b.test_start)
                   ) AS purged_rows,
                   count(*) FILTER (
                       WHERE s.snapshot_kind = 'median'
                         AND s.snapshot_date >= b.test_start
                         AND s.snapshot_date < b.test_start + to_years(1)
                   ) AS test_rows_1y_window
            FROM snapshots_all s
            CROSS JOIN bounds b
            CROSS JOIN hz h
            GROUP BY b.test_start, h.horizon
        )
        ORDER BY test_start, horizon
        """
    )


def splits_diag_report_sections(con: duckdb.DuckDBPyConnection) -> list[str]:
    from .report import md_table

    return [
        "# Splits diagnostics (PLAN §7.7, decision 0010)",
        f"Generated {date.today().isoformat()} by `sharadar-qa splits-diag`. "
        "Full tables land as CSVs next to this report; interpretation guide "
        "in docs/research/splits.md.",
        "## Q1/Q2 — which features move within a quarter",
        "Top features by the fraction of (stock, quarter) groups whose three "
        "snapshot kinds disagree. Price-touching features should lead; "
        "fundamental-only features should differ only in filing-straddle "
        "quarters (full list: `feature_intraquarter.csv`).",
        md_table(
            con,
            "SELECT * FROM feature_intraquarter "
            "ORDER BY frac_groups_differ DESC, family, feature LIMIT 30",
        ),
        md_table(con, "SELECT * FROM filing_straddle"),
        "## Q2 — label structure across kinds, stocks, and quarters",
        "Flip rate: among (stock, quarter) groups where both the low and "
        "high kinds have observable labels, how often the binary label "
        "disagrees — the margin-of-safety gradient made visible.",
        md_table(con, "SELECT * FROM label_kind_flip ORDER BY horizon, label"),
        "Variance decomposition (exact ANOVA shares): "
        "`within_stock_quarter_share` is the entry-price gradient's share of "
        "all-kinds label variance; `quarter_fe_share` is the calendar-"
        "quarter fixed effect on median rows — the §7.1 cross-sectional "
        "overlap. Serial correlation is same-stock, median-kind, by quarter "
        "lag — the §7.1 serial overlap.",
        md_table(con, "SELECT * FROM label_variance_decomposition ORDER BY horizon"),
        md_table(
            con,
            "SELECT * FROM label_serial_correlation ORDER BY horizon, lag_quarters",
        ),
        "## Q3 — twin test (row uniqueness)",
        "Nearest neighbor of each sampled median row in quarter-ranked "
        "feature space (axes: "
        + ", ".join(col for _fam, col in TWIN_FEATURES)
        + "). If near-twins are disproportionately same-stock neighbor "
        "quarters or same-date peers, and their labels are far more "
        "correlated than random pairs', approximate memorization has "
        "something to recall (pairs detail: `twin_pairs.parquet`).",
        md_table(con, "SELECT * FROM twin_relations"),
        md_table(
            con, "SELECT * FROM twin_label_corr ORDER BY horizon, pairing"
        ),
        "## Purge cost (§7.2 priced per boundary)",
        "Most recent three boundaries shown; all boundaries in "
        "`purge_cost.csv`. Unweighted row counts — uniqueness-weighted "
        "effective sample sizes follow once M5 defines `sample_weight`.",
        md_table(
            con,
            """
            SELECT * FROM purge_cost
            WHERE test_start IN (
                SELECT DISTINCT test_start FROM purge_cost
                ORDER BY test_start DESC LIMIT 3)
            ORDER BY test_start, horizon
            """,
        ),
    ]
