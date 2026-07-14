"""Coverage / null-rate report — the research-phase unblocker (features.md §F9).

Per median-kind snapshot, resolve the latest ARQ filing known at the snapshot
date and measure, by year and by sector:

- fundamentals availability and freshness (staleness distribution),
- ADR-0004 depth-tier survival (T1/T2/T3 via reportperiod-window lag
  matching, never positional lags),
- price-history coverage for the P12/P36 technical windows,
- null rates of the SF1 fields the feature families need (feeds V5).

Tier definitions (ADR 0004): a snapshot is Tk-covered when its latest filing
is fresh (age <= 365d) and annual-lag partners exist at 1..k years back, each
within `reportperiod - 365*j +/- 30 days` and filed before the snapshot date.
"""

from __future__ import annotations

import logging
from datetime import date

import duckdb

logger = logging.getLogger(__name__)

FRESH_DAYS_TIGHT = 183
FRESH_DAYS_LOOSE = 365  # also the tier-gating staleness bound
LAG_WINDOW_HALF_DAYS = 30
MAX_LAG_YEARS = 3

# Calendar-day windows and minimum trading-day counts for the price tiers.
P12_WINDOW_DAYS, P12_MIN_DAYS = 372, 200
P36_WINDOW_DAYS, P36_MIN_DAYS = 1116, 600


def build_snapshot_latest_view(
    con: duckdb.DuckDBPyConnection, *, fields: list[str]
) -> None:
    """`snapshot_latest_arq`: each median snapshot with the freshest ARQ
    filing available strictly before it (PLAN §2: usable strictly after
    `datekey`), or NULLs when none exists."""
    field_list = "".join(f", f.{name}" for name in fields)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW snapshot_latest_arq AS
        SELECT
            s.permaticker,
            s.quarter,
            s.snapshot_date,
            f.datekey,
            f.reportperiod,
            s.snapshot_date - f.datekey AS age_days
            {field_list}
        FROM snapshots_median s
        ASOF LEFT JOIN sf1_arq_latest f
          ON s.permaticker = f.permaticker AND s.snapshot_date > f.datekey
        """
    )


def build_coverage_views(
    con: duckdb.DuckDBPyConnection,
    *,
    fields: list[str],
    with_prices: bool,
) -> None:
    build_snapshot_latest_view(con, fields=fields)

    lag_flags = []
    for k in range(1, MAX_LAG_YEARS + 1):
        lo = 365 * k + LAG_WINDOW_HALF_DAYS
        hi = 365 * k - LAG_WINDOW_HALF_DAYS
        lag_flags.append(
            f"coalesce(bool_or(f.reportperiod BETWEEN "
            f"b.reportperiod - {lo} AND b.reportperiod - {hi}), false) "
            f"AS has_lag_{k}y"
        )
    max_lookback = 365 * MAX_LAG_YEARS + LAG_WINDOW_HALF_DAYS
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW snapshot_history AS
        SELECT
            b.permaticker,
            b.snapshot_date,
            {", ".join(lag_flags)}
        FROM snapshot_latest_arq b
        LEFT JOIN sf1_arq f
          ON f.permaticker = b.permaticker
         AND f.datekey < b.snapshot_date
         AND f.reportperiod < b.reportperiod
         AND f.reportperiod >= b.reportperiod - {max_lookback}
        GROUP BY 1, 2
        """
    )

    if with_prices:
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW price_history AS
            SELECT
                s.permaticker,
                s.snapshot_date,
                count(p.date) FILTER (
                    WHERE p.date > s.snapshot_date - {P12_WINDOW_DAYS}
                ) AS pdays_12m,
                count(p.date) AS pdays_36m
            FROM snapshots_median s
            LEFT JOIN sep_resolved p
              ON p.permaticker = s.permaticker
             AND p.date <= s.snapshot_date
             AND p.date > s.snapshot_date - {P36_WINDOW_DAYS}
            GROUP BY 1, 2
            """
        )

    price_cols = price_join = ""
    if with_prices:
        price_cols = f""",
            p.pdays_12m,
            p.pdays_36m,
            p.pdays_12m >= {P12_MIN_DAYS} AS p12_ok,
            p.pdays_36m >= {P36_MIN_DAYS} AS p36_ok"""
        price_join = "LEFT JOIN price_history p USING (permaticker, snapshot_date)"
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW snapshot_coverage AS
        SELECT
            b.*,
            u.sector,
            b.reportperiod IS NOT NULL
                AND b.age_days <= {FRESH_DAYS_TIGHT} AS fresh_183,
            b.reportperiod IS NOT NULL
                AND b.age_days <= {FRESH_DAYS_LOOSE} AS fresh_365,
            b.reportperiod IS NOT NULL
                AND b.age_days <= {FRESH_DAYS_LOOSE} AS t0_ok,
            b.reportperiod IS NOT NULL AND b.age_days <= {FRESH_DAYS_LOOSE}
                AND h.has_lag_1y AS t1_ok,
            b.reportperiod IS NOT NULL AND b.age_days <= {FRESH_DAYS_LOOSE}
                AND h.has_lag_1y AND h.has_lag_2y AS t2_ok,
            b.reportperiod IS NOT NULL AND b.age_days <= {FRESH_DAYS_LOOSE}
                AND h.has_lag_1y AND h.has_lag_2y AND h.has_lag_3y AS t3_ok
            {price_cols}
        FROM snapshot_latest_arq b
        JOIN snapshot_history h USING (permaticker, snapshot_date)
        LEFT JOIN universe u ON u.permaticker = b.permaticker
        {price_join}
        """
    )

    price_aggs = ""
    if with_prices:
        price_aggs = """,
            round(avg(p12_ok::INT), 4) AS frac_p12,
            round(avg(p36_ok::INT), 4) AS frac_p36"""
    shared_aggs = f"""
            count(*) AS snapshots,
            count(reportperiod) AS with_filing,
            median(age_days) AS median_age_days,
            round(avg(fresh_183::INT), 4) AS frac_fresh_183,
            round(avg(fresh_365::INT), 4) AS frac_fresh_365,
            round(avg(t1_ok::INT), 4) AS frac_t1,
            round(avg(t2_ok::INT), 4) AS frac_t2,
            round(avg(t3_ok::INT), 4) AS frac_t3
            {price_aggs}"""
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW coverage_by_year AS
        SELECT
            extract(year FROM snapshot_date)::INT AS year,
            {shared_aggs}
        FROM snapshot_coverage
        GROUP BY 1 ORDER BY 1
        """
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW coverage_by_sector AS
        SELECT
            coalesce(sector, '(none)') AS sector,
            {shared_aggs}
        FROM snapshot_coverage
        GROUP BY 1 ORDER BY 1
        """
    )

    # Null rates among snapshots that do have a filing: one row per
    # (year, field) and per (sector, field).
    year_parts = [
        f"""
        SELECT
            extract(year FROM snapshot_date)::INT AS year,
            '{name}' AS field,
            count(*) AS with_filing,
            round(avg(({name} IS NULL)::INT), 4) AS null_rate
        FROM snapshot_coverage
        WHERE reportperiod IS NOT NULL
        GROUP BY 1
        """
        for name in fields
    ]
    con.execute(
        "CREATE OR REPLACE TEMP VIEW null_rates_by_year AS "
        + " UNION ALL ".join(year_parts)
        + " ORDER BY field, year"
    )
    sector_parts = [
        f"""
        SELECT
            coalesce(sector, '(none)') AS sector,
            '{name}' AS field,
            count(*) AS with_filing,
            round(avg(({name} IS NULL)::INT), 4) AS null_rate
        FROM snapshot_coverage
        WHERE reportperiod IS NOT NULL
        GROUP BY 1
        """
        for name in fields
    ]
    con.execute(
        "CREATE OR REPLACE TEMP VIEW null_rates_by_sector AS "
        + " UNION ALL ".join(sector_parts)
        + " ORDER BY field, sector"
    )


def coverage_report_sections(
    con: duckdb.DuckDBPyConnection, *, with_prices: bool
) -> list[str]:
    from .report import md_table

    overall = con.execute(
        """
        SELECT count(*), count(reportperiod),
               round(avg(fresh_365::INT), 4), round(avg(t1_ok::INT), 4),
               round(avg(t3_ok::INT), 4)
        FROM snapshot_coverage
        """
    ).fetchone()
    price_note = (
        "" if with_prices else "\n\nPrice-window coverage skipped (`--no-prices`)."
    )
    sections = [
        "# Coverage report (features.md §F9)",
        f"Generated {date.today().isoformat()} by `sharadar-qa coverage` over "
        "median-kind snapshots. Machine-readable detail (parquet/CSV, incl. "
        "full null-rate tables) under `data/interim/qa/`; the CSVs beside "
        "this file are the committable copies."
        f"{price_note}",
        f"**Headline:** {overall[0]:,} snapshots; {overall[1]:,} with an ARQ "
        f"filing; fresh-within-365d {overall[2]:.1%}; T1 {overall[3]:.1%}; "
        f"T3 {overall[4]:.1%}.",
        "## By year\n\n" + md_table(con, "SELECT * FROM coverage_by_year"),
        "## By sector\n\n" + md_table(con, "SELECT * FROM coverage_by_sector"),
        "## Highest overall null rates\n\n"
        + md_table(
            con,
            """
            SELECT field,
                   sum(with_filing) AS with_filing,
                   round(sum(null_rate * with_filing) / sum(with_filing), 4)
                       AS null_rate
            FROM null_rates_by_year
            GROUP BY field ORDER BY null_rate DESC LIMIT 15
            """,
        )
        + "\n\nFull field × year and field × sector tables: "
        "`null_rates_by_year.csv`, `null_rates_by_sector.csv`.",
    ]
    return sections
