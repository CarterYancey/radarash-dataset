"""Staleness × labels — data for the 6-vs-12-month cutoff question.

Buckets every median-kind snapshot by the age of its freshest ARQ filing and
compares 1y label outcomes across buckets (features.md §F4.4). Late filers
are disproportionately distressed, so a hard staleness cutoff can bias the
label distribution — this report measures whether it would, and how many
rows each candidate cutoff affects.

Reading the output: a monotone gradient in delist rate / mean forward CAGR
across buckets means staleness is informative (keep the rows, expose
`fundamentals_age_days` as a feature, apply cutoffs as assembly-time filters
per ADR 0004); the bucket sizes above 183d/365d price the two cutoffs.
"""

from __future__ import annotations

import logging

import duckdb

logger = logging.getLogger(__name__)

BUCKETS = (
    ("no filing", None),
    ("0-93d", 93),
    ("94-183d", 183),
    ("184-365d", 365),
    (">365d", None),
)


def build_staleness_views(con: duckdb.DuckDBPyConnection) -> None:
    """Requires `snapshot_latest_arq` (coverage) and `labels_median`."""
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW snapshot_staleness AS
        SELECT
            b.permaticker,
            b.snapshot_date,
            b.age_days,
            CASE
                WHEN b.reportperiod IS NULL THEN 'no filing'
                WHEN b.age_days <= 93 THEN '0-93d'
                WHEN b.age_days <= 183 THEN '94-183d'
                WHEN b.age_days <= 365 THEN '184-365d'
                ELSE '>365d'
            END AS staleness_bucket,
            CASE
                WHEN b.reportperiod IS NULL THEN 0
                WHEN b.age_days <= 93 THEN 1
                WHEN b.age_days <= 183 THEN 2
                WHEN b.age_days <= 365 THEN 3
                ELSE 4
            END AS bucket_order,
            l.fwd_1y_cagr,
            l.label_1y_cagr_ge_0,
            l.label_1y_beat_spy,
            l.delisted_in_window_1y
        FROM snapshot_latest_arq b
        JOIN labels_median l USING (permaticker, snapshot_date)
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW staleness_by_bucket AS
        SELECT
            staleness_bucket,
            count(*) AS snapshots,
            round(count(*) / sum(count(*)) OVER (), 4) AS share,
            count(fwd_1y_cagr) AS labeled_1y,
            round(avg(fwd_1y_cagr), 4) AS mean_fwd_1y_cagr,
            round(median(fwd_1y_cagr), 4) AS median_fwd_1y_cagr,
            round(avg(label_1y_cagr_ge_0::INT), 4) AS frac_1y_ge_0,
            round(avg(label_1y_beat_spy::INT), 4) AS frac_1y_beat_spy,
            round(avg((delisted_in_window_1y <> 'false')::INT), 4)
                AS frac_delisted_1y
        FROM snapshot_staleness
        GROUP BY staleness_bucket, bucket_order
        ORDER BY bucket_order
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW staleness_by_year AS
        SELECT
            year,
            staleness_bucket,
            snapshots,
            round(snapshots / sum(snapshots) OVER (PARTITION BY year), 4)
                AS share_of_year
        FROM (
            SELECT
                extract(year FROM snapshot_date)::INT AS year,
                staleness_bucket,
                bucket_order,
                count(*) AS snapshots
            FROM snapshot_staleness
            GROUP BY 1, staleness_bucket, bucket_order
        )
        ORDER BY year, bucket_order
        """
    )


def staleness_report_sections(con: duckdb.DuckDBPyConnection) -> list[str]:
    from datetime import date

    from .report import md_table

    return [
        "# Staleness × labels report (features.md §F4.4)",
        f"Generated {date.today().isoformat()} by `sharadar-qa staleness` over "
        "median-kind snapshots; label stats use the 1y horizon and skip "
        "unobservable windows. Per-year bucket shares: "
        "`staleness_by_year.csv`.",
        md_table(con, "SELECT * FROM staleness_by_bucket"),
        "A monotone delist-rate / return gradient across buckets means "
        "staleness is signal (keep rows; cutoff only as an assembly filter). "
        "The 184-365d and >365d shares price a 183d vs. 365d cutoff.",
    ]
