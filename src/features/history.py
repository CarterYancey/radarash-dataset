"""Point-in-time history resolution: `fund_history`, `div_history` and
`annual_history`.

Foundation views for the trend family (ADR 0015), built like `fund_base`
but resolving a *set* of past filings per snapshot instead of aligned lag
columns:

- **`fund_history`** — one row per snapshot × quarterly offset `qoff`
  (0..19; 0 = the T0 filing's own reportperiod): the filing whose
  `reportperiod` falls within ±30 days of `fund_reportperiod − qoff·91.3125`,
  taking the latest `datekey < snapshot_date` version (the version of
  history known at snapshot time — same rule as ADR 0004 lags; `<=` for
  inference, ADR 0014). Off-grid filings (fiscal-year changes) match no
  bucket. Carries the trend series (`revenue`, `tangibles`, `ncfo`) plus
  the adjacent-quarter previous values (`prev_*`, valid when
  `prev_qoff = qoff + 1`), and for the relative-value family the bucket
  filing's own `netinc`, `fcf`, `equity`, `shares` (`sharesbas × sharefactor`),
  `bucket_datekey` and `bucket_reportperiod` (its historical market cap is
  priced in src/features/relvalue.py), and for the fundamental-history
  family (ADR 0023) `gp`, `ebit`, `assets` and book value per share
  `bvps = equity / shares` (NULL unless `shares > 0`), with `prev_netinc`,
  `prev_bvps`, `prev_shares` alongside the other adjacent-quarter values.
- **`div_history`** — one row per snapshot × fiscal-year offset `yoff`
  (0..9), same matching at 365.25-day spacing, carrying the TTM cash
  dividend `div_ttm = −ncfdiv` plus `prev_yoff`/`prev_div_ttm` and `streak_ok`
  (every year from yoff 0 to this one present and paying — the dividend
  streak is `count(streak_ok)`).
- **`annual_history`** — one row per snapshot × fiscal-year offset `yoff`
  (0..10: eleven observations span ten years of growth), same matching as
  `div_history`, carrying TTM `netinc` and `revenue`, `shares` and `bvps`
  (ADR 0023's ten-year record).

Snapshots with no T0 filing (`fund_reportperiod` NULL) have no rows in
any of these views; the trend family maps that to NULL features, never zero.
"""

from __future__ import annotations

import duckdb

# Bucket spacing; matching slack is ±30 days like the ADR 0004 lag windows.
QUARTER_DAYS = 365.25 / 4
YEAR_DAYS = 365.25
BUCKET_SLACK_DAYS = 30

HISTORY_QUARTERS = 20  # deepest quarterly window (T5, ADR 0015)
DIVIDEND_YEARS = 10  # dividend-record window (T10, ADR 0015)
ANNUAL_YEARS = 10  # ten-year record: offsets 0..10 (T10, ADR 0023)

# sharesbas × sharefactor, NULL unless positive (the ADR 0007 convention).
_SHARES = (
    "CASE WHEN f.l_sharesbas * f.l_sharefactor > 0"
    " THEN f.l_sharesbas * f.l_sharefactor END"
)


def _bucket_cte(
    *,
    cutoff_op: str,
    spacing_days: float,
    n_buckets: int,
    offset_name: str,
    value_cols: str,
) -> str:
    """Bucketed history: latest known filing per (snapshot, offset)."""
    lo_days = round((n_buckets - 1) * spacing_days + BUCKET_SLACK_DAYS)
    delta = "(k.fund_reportperiod - f.reportperiod)"
    offset = f"round({delta} / {spacing_days})"
    return f"""
        keys AS (
            SELECT permaticker, snapshot_date, snapshot_kind,
                   fund_reportperiod
            FROM fund_base
            WHERE fund_reportperiod IS NOT NULL
        ),
        buckets AS (
            SELECT * EXCLUDE (rn) FROM (
                SELECT k.permaticker, k.snapshot_date, k.snapshot_kind,
                       CAST({offset} AS INTEGER) AS {offset_name},
                       {value_cols},
                       row_number() OVER (
                           PARTITION BY k.permaticker, k.snapshot_date,
                                        k.snapshot_kind, {offset}
                           ORDER BY f.datekey DESC, f.reportperiod DESC
                       ) AS rn
                FROM keys k
                JOIN sf1_filings f
                  ON f.permaticker = k.permaticker
                 AND f.datekey {cutoff_op} k.snapshot_date
                 AND f.reportperiod
                     BETWEEN k.fund_reportperiod - {lo_days}
                         AND k.fund_reportperiod
                 AND abs({delta} - {spacing_days} * {offset})
                     <= {BUCKET_SLACK_DAYS}
            ) WHERE rn = 1
        )"""


def build_fund_history_view(
    con: duckdb.DuckDBPyConnection,
    *,
    include_same_day_filings: bool = False,
) -> None:
    """Create `fund_history` and `div_history` from `fund_base` +
    `sf1_filings`. Same cutoff semantics as `build_fund_base_view`."""
    cutoff_op = "<=" if include_same_day_filings else "<"

    ctes = _bucket_cte(
        cutoff_op=cutoff_op,
        spacing_days=QUARTER_DAYS,
        n_buckets=HISTORY_QUARTERS,
        offset_name="qoff",
        value_cols=(
            "f.f_revenue AS revenue, f.l_tangibles AS tangibles, "
            "f.f_ncfo AS ncfo, f.f_netinc AS netinc, f.f_fcf AS fcf, "
            "f.l_equity AS equity, "
            "f.l_sharesbas * f.l_sharefactor AS shares, "
            "f.f_gp AS gp, f.f_ebit AS ebit, f.l_assets AS assets, "
            f"f.l_equity / ({_SHARES}) AS bvps, "
            "f.datekey AS bucket_datekey, "
            "f.reportperiod AS bucket_reportperiod"
        ),
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW fund_history AS
        WITH {ctes}
        SELECT *,
               lag(qoff) OVER w AS prev_qoff,
               lag(revenue) OVER w AS prev_revenue,
               lag(tangibles) OVER w AS prev_tangibles,
               lag(ncfo) OVER w AS prev_ncfo,
               lag(netinc) OVER w AS prev_netinc,
               lag(bvps) OVER w AS prev_bvps,
               lag(shares) OVER w AS prev_shares
        FROM buckets
        WINDOW w AS (
            PARTITION BY permaticker, snapshot_date, snapshot_kind
            ORDER BY qoff DESC
        )
        """
    )

    ctes = _bucket_cte(
        cutoff_op=cutoff_op,
        spacing_days=YEAR_DAYS,
        n_buckets=DIVIDEND_YEARS,
        offset_name="yoff",
        value_cols="-f.f_ncfdiv AS div_ttm",
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW div_history AS
        WITH {ctes},
        ordered AS (
            SELECT *,
                   row_number() OVER (
                       PARTITION BY permaticker, snapshot_date, snapshot_kind
                       ORDER BY yoff
                   ) AS rn_asc,
                   lag(yoff) OVER w AS prev_yoff,
                   lag(div_ttm) OVER w AS prev_div_ttm
            FROM buckets
            WINDOW w AS (
                PARTITION BY permaticker, snapshot_date, snapshot_kind
                ORDER BY yoff DESC
            )
        )
        SELECT * EXCLUDE (rn_asc),
               bool_and(coalesce(div_ttm > 0, FALSE) AND yoff = rn_asc - 1) OVER (
                   PARTITION BY permaticker, snapshot_date, snapshot_kind
                   ORDER BY yoff
                   ROWS UNBOUNDED PRECEDING
               ) AS streak_ok
        FROM ordered
        """
    )

    ctes = _bucket_cte(
        cutoff_op=cutoff_op,
        spacing_days=YEAR_DAYS,
        n_buckets=ANNUAL_YEARS + 1,
        offset_name="yoff",
        value_cols=(
            "f.f_netinc AS netinc, f.f_revenue AS revenue, "
            f"{_SHARES} AS shares, f.l_equity / ({_SHARES}) AS bvps"
        ),
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW annual_history AS
        WITH {ctes}
        SELECT * FROM buckets
        """
    )
