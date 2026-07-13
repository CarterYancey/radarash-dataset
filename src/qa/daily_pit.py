"""V7 — is Sharadar DAILY point-in-time safe? (features.md §F8.1)

DAILY carries daily marketcap/ev/pe/pb/ps. If Nasdaq recomputes *historical*
rows after restatements, the table incorporates lookahead and M4 valuation
must build its own snapshot-date market inputs instead. Three diagnostics,
none individually conclusive, together decisive:

1. **Freshness**: distribution of `lastupdated - date` by year. Old rows with
   recent `lastupdated` are being touched after the fact (caveat: bulk
   schema refreshes also bump `lastupdated` — corroborate with #2/#3).
2. **Marketcap replication**: DAILY.marketcap vs. our own
   `SEP.close × ARQ shares` as of each date, on a deterministic ticker
   sample. A unit scale (Sharadar reports $M) is inferred as the median
   ratio; deviations beyond split-timing noise indicate a different (possibly
   restated) share source.
3. **ARQ-vs-MRQ discrimination**: where as-reported and most-recent equity
   for the same date differ (i.e. restated periods), is DAILY.pb closer to
   the ARQ-derived or the MRQ-derived book value? Numerator is DAILY's own
   marketcap in both, so the comparison isolates the equity source. Closer
   to MRQ ⇒ recomputed ⇒ **not** PIT-safe.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from identity.source import sql_quote

logger = logging.getLogger(__name__)

DEFAULT_SAMPLE_TICKERS = 500
FRESHNESS_LAG_FLAG_DAYS = 35
PB_DISCRIMINATION_MIN_LOG_DIFF = 0.01


def build_daily_pit_views(
    con: duckdb.DuckDBPyConnection,
    *,
    daily_parquet: Path,
    sep_parquet: Path,
    sf1_parquet: Path,
    has_sharefactor: bool,
    sample_tickers: int = DEFAULT_SAMPLE_TICKERS,
) -> None:
    daily = sql_quote(str(daily_parquet))
    sep = sql_quote(str(sep_parquet))
    sf1 = sql_quote(str(sf1_parquet))

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW daily_freshness AS
        SELECT
            extract(year FROM date)::INT AS year,
            count(*) AS rows,
            median(lastupdated - date) AS median_lag_days,
            quantile_cont(lastupdated - date, 0.95) AS p95_lag_days,
            round(avg(((lastupdated - date) > {FRESHNESS_LAG_FLAG_DAYS})::INT), 4)
                AS frac_lag_gt_{FRESHNESS_LAG_FLAG_DAYS}d
        FROM read_parquet({daily})
        WHERE date IS NOT NULL AND lastupdated IS NOT NULL
        GROUP BY 1 ORDER BY 1
        """
    )

    # Deterministic sample: hash-ordered tickers that have ARQ share counts.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW pit_tickers AS
        SELECT ticker FROM (
            SELECT DISTINCT ticker
            FROM read_parquet({sf1})
            WHERE dimension = 'ARQ' AND sharesbas IS NOT NULL
        )
        ORDER BY md5(ticker)
        LIMIT {int(sample_tickers)}
        """
    )

    shares_expr = "sharesbas"
    if has_sharefactor:
        shares_expr = "sharesbas * coalesce(sharefactor, 1)"
    for dim, view in (("ARQ", "pit_sf1_arq"), ("MRQ", "pit_sf1_mrq")):
        con.execute(
            f"""
            CREATE OR REPLACE TEMP VIEW {view} AS
            SELECT * EXCLUDE (rn) FROM (
                SELECT
                    ticker,
                    datekey,
                    {shares_expr} AS shares,
                    equity,
                    row_number() OVER (
                        PARTITION BY ticker, datekey
                        ORDER BY reportperiod DESC
                    ) AS rn
                FROM read_parquet({sf1})
                WHERE dimension = '{dim}'
                  AND ticker IN (SELECT ticker FROM pit_tickers)
                  AND datekey IS NOT NULL
            ) WHERE rn = 1
            """
        )

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW pit_base AS
        SELECT
            d.ticker,
            d.date,
            d.marketcap,
            d.pb,
            p.close * a.shares AS own_mcap,
            a.equity AS equity_arq,
            m.equity AS equity_mrq
        FROM (
            SELECT ticker, date, marketcap, pb
            FROM read_parquet({daily})
            WHERE ticker IN (SELECT ticker FROM pit_tickers)
              AND date IS NOT NULL
        ) d
        JOIN read_parquet({sep}) p
          ON p.ticker = d.ticker AND p.date = d.date AND p.close > 0
        ASOF JOIN pit_sf1_arq a
          ON d.ticker = a.ticker AND d.date >= a.datekey
        ASOF LEFT JOIN pit_sf1_mrq m
          ON d.ticker = m.ticker AND d.date >= m.datekey
        """
    )

    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW pit_marketcap_by_year AS
        WITH usable AS (
            SELECT date, own_mcap / marketcap AS ratio
            FROM pit_base
            WHERE marketcap > 0 AND own_mcap > 0
        ),
        scale AS (SELECT median(ratio) AS s FROM usable),
        errs AS (
            SELECT date, abs(ratio / (SELECT s FROM scale) - 1) AS abs_err
            FROM usable
        )
        SELECT
            extract(year FROM date)::INT AS year,
            count(*) AS rows,
            round((SELECT s FROM scale), 2) AS unit_scale,
            round(median(abs_err), 4) AS median_abs_err,
            round(quantile_cont(abs_err, 0.9), 4) AS p90_abs_err,
            round(avg((abs_err <= 0.01)::INT), 4) AS frac_within_1pct,
            round(avg((abs_err <= 0.05)::INT), 4) AS frac_within_5pct
        FROM errs
        GROUP BY 1 ORDER BY 1
        """
    )

    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW pit_pb_check AS
        WITH usable AS (
            SELECT
                date,
                pb,
                marketcap / equity_arq AS pb_arq,
                marketcap / equity_mrq AS pb_mrq
            FROM pit_base
            WHERE pb > 0 AND marketcap > 0
              AND equity_arq > 0 AND equity_mrq > 0
        ),
        scale AS (SELECT median(pb / pb_arq) AS s FROM usable),
        discriminating AS (
            SELECT
                date,
                abs(ln(pb) - ln(pb_arq * (SELECT s FROM scale))) AS err_arq,
                abs(ln(pb) - ln(pb_mrq * (SELECT s FROM scale))) AS err_mrq
            FROM usable
            WHERE abs(ln(pb_arq) - ln(pb_mrq)) > {PB_DISCRIMINATION_MIN_LOG_DIFF}
        )
        SELECT
            extract(year FROM date)::INT AS year,
            count(*) AS discriminating_rows,
            round(avg((err_arq < err_mrq)::INT), 4) AS frac_closer_to_arq
        FROM discriminating
        GROUP BY 1 ORDER BY 1
        """
    )


def daily_pit_report_sections(con: duckdb.DuckDBPyConnection) -> list[str]:
    from datetime import date

    from .report import md_table

    overall = con.execute(
        """
        SELECT sum(discriminating_rows),
               round(sum(frac_closer_to_arq * discriminating_rows)
                     / nullif(sum(discriminating_rows), 0), 4)
        FROM pit_pb_check
        """
    ).fetchone()
    n_disc = int(overall[0] or 0)
    frac_arq = overall[1]
    if n_disc == 0:
        verdict = (
            "No discriminating (restated) rows in the sample — enlarge "
            "`--sample-tickers` before drawing a conclusion."
        )
    else:
        verdict = (
            f"Across {n_disc:,} restated ticker-days, DAILY.pb is closer to "
            f"the **as-reported** book value {frac_arq:.1%} of the time. "
            "Near 100% ⇒ historical rows look frozen (PIT-safe, DAILY usable "
            "for M4 valuation); near 0% ⇒ recomputed from restated data — "
            "use the self-built SEP × ARQ construction (features.md §F8.1)."
        )
    return [
        "# V7 — DAILY point-in-time safety",
        f"Generated {date.today().isoformat()} by `sharadar-qa daily-pit` on a "
        "deterministic ticker sample. Caveats: no single diagnostic is "
        "conclusive — bulk refreshes bump `lastupdated` without changing "
        "values (#1), and shares split-adjusted between filing and price "
        "date add benign noise to the replication (#2); #3 is the sharp "
        "test.",
        f"**Verdict input:** {verdict}",
        "## 1. `lastupdated` freshness by year (full DAILY)\n\n"
        + md_table(con, "SELECT * FROM daily_freshness"),
        "## 2. Marketcap replication vs. SEP × ARQ shares (sample)\n\n"
        + md_table(con, "SELECT * FROM pit_marketcap_by_year"),
        "## 3. ARQ-vs-MRQ discrimination via DAILY.pb (sample, restated rows "
        "only)\n\n" + md_table(con, "SELECT * FROM pit_pb_check"),
    ]
