"""As-of fundamentals resolution: the `fund_base` foundation view.

For every snapshot row this resolves, per PLAN §2 and the registry
conventions in docs/features.md:

- **T0** — the freshest as-reported filing with `datekey < snapshot_date`
  (strictly before: a filing is usable the first trading day after
  `datekey`). "Freshest" is by `datekey`, matching the convention the QA
  staleness report used to produce ADR 0006's numbers; when two filings
  share a datekey the most recent fiscal period wins. Snapshots with no
  prior filing keep NULL fundamentals (ADR 0006 — never dropped).
- **T1/T2/T3 lags** (ADR 0004) — the filing whose `reportperiod` falls in
  `fund_reportperiod - 365*k ± 30` days, taking the latest
  `datekey < snapshot_date` version (the version of history known at
  snapshot time; amendments published later are invisible). No partner in
  the window => NULL, never a positional LAG.

Columns: the snapshot key + `fund_datekey`/`fund_reportperiod` +
`l_<field>`/`f_<field>` (T0 ARQ levels / ART flows, see source.py) +
`l{k}_<field>`/`f{k}_<field>` lag columns for the fields the growth and
quality families need.
"""

from __future__ import annotations

import duckdb

from .source import ARQ_LEVEL_FIELDS, ART_FLOW_FIELDS

# ADR 0004: the lag-k partner's reportperiod window is 365*k ± 30 days.
LAG_WINDOW_SLACK_DAYS = 30

# Lag fields per depth, kept to what registry formulas actually read.
LAG_LEVEL_FIELDS: dict[int, tuple[str, ...]] = {
    1: ("assets", "assetsc", "liabilitiesc", "receivables", "ppnenet",
        "debt", "debtnc", "sharesbas", "sharefactor"),
    2: ("assets",),
    3: ("assets",),
}
LAG_FLOW_FIELDS: dict[int, tuple[str, ...]] = {
    1: ("revenue", "gp", "netinc", "epsdil", "depamor", "sgna"),
    2: ("revenue", "gp", "netinc"),
    3: ("revenue", "netinc"),
}

LAG_DEPTHS: tuple[int, ...] = (1, 2, 3)


def _lag_cte(k: int) -> str:
    cols = ", ".join(
        [f"f.l_{x} AS l{k}_{x}" for x in LAG_LEVEL_FIELDS.get(k, ())]
        + [f"f.f_{x} AS f{k}_{x}" for x in LAG_FLOW_FIELDS.get(k, ())]
    )
    lo = 365 * k + LAG_WINDOW_SLACK_DAYS
    hi = 365 * k - LAG_WINDOW_SLACK_DAYS
    return f"""
        lag{k} AS (
            SELECT * EXCLUDE (rn) FROM (
                SELECT t0.permaticker, t0.snapshot_date, t0.snapshot_kind,
                       {cols},
                       row_number() OVER (
                           PARTITION BY t0.permaticker, t0.snapshot_date,
                                        t0.snapshot_kind
                           ORDER BY f.datekey DESC, f.reportperiod DESC
                       ) AS rn
                FROM t0
                JOIN sf1_filings f
                  ON f.permaticker = t0.permaticker
                 AND f.datekey < t0.snapshot_date
                 AND f.reportperiod
                     BETWEEN t0.fund_reportperiod - {lo}
                         AND t0.fund_reportperiod - {hi}
            ) WHERE rn = 1
        )"""


def build_fund_base_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `fund_base` view from `snapshots` and `sf1_filings`."""
    t0_cols = "".join(
        [f", f.l_{x}" for x in ARQ_LEVEL_FIELDS]
        + [f", f.f_{x}" for x in ART_FLOW_FIELDS]
    )
    lag_ctes = ",".join(_lag_cte(k) for k in LAG_DEPTHS)
    lag_joins = "".join(
        f"""
        LEFT JOIN lag{k}
          USING (permaticker, snapshot_date, snapshot_kind)"""
        for k in LAG_DEPTHS
    )
    lag_select = "".join(
        f", lag{k}.l{k}_{x}"
        for k in LAG_DEPTHS
        for x in LAG_LEVEL_FIELDS.get(k, ())
    ) + "".join(
        f", lag{k}.f{k}_{x}"
        for k in LAG_DEPTHS
        for x in LAG_FLOW_FIELDS.get(k, ())
    )
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW fund_base AS
        WITH t0 AS (
            SELECT s.permaticker, s.snapshot_date, s.snapshot_kind,
                   s.quarter, s.entry_closeadj,
                   f.datekey AS fund_datekey,
                   f.reportperiod AS fund_reportperiod
                   {t0_cols}
            FROM snapshots s
            ASOF LEFT JOIN sf1_filings_latest f
              ON s.permaticker = f.permaticker
             AND s.snapshot_date > f.datekey
        ),{lag_ctes}
        SELECT t0.*{lag_select}
        FROM t0{lag_joins}
        """
    )
