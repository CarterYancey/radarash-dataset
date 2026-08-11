"""Index-membership family: was the stock in a major index at the snapshot?

Three sources, three fidelities (ADR 0015 — read it before changing any
rule here):

- **S&P 500** — genuinely point-in-time, from the `SHARADAR/SP500`
  constituent-action table (`added` / `removed` / `historical` / `current`).
  Events are folded into membership *spells* per permaticker; a ticker whose
  earliest event is not an `added` is treated as a member from the table's
  first date (it was already in the index when the table starts), which
  left-censors `days_in_sp500` but never invents a non-membership.
- **Dow 30** — from the constituent-change history checked in at
  `reference/dow_membership.csv` (Sharadar ships no Dow table). Exact, but
  hand-maintained: it covers 1999-11-01 onward and is verified through
  :data:`DOW_VERIFIED_THROUGH`; membership is carried forward past that date
  with a logged warning.
- **Russell 1000/2000/3000** — a **proxy**, not the real index (no
  licence-free constituent history exists). Every June reconstitution is
  approximated by ranking all common stocks — financials included, so the
  universe exclusion does not distort the boundary — on market cap at the
  last trading day on or before May 31, then holding that membership from
  the first trading day of July until the next reconstitution: top 1000 =
  `in_russell1000`, 1001-3000 = `in_russell2000`, top 3000 =
  `in_russell3000`. Real reconstitutions use banded rules, IPO additions
  mid-year, and float-adjusted caps; treat the boundary as approximate.

Snapshots before an index's coverage start get NULL, never false — the
absence of history is not evidence of non-membership. Missing market cap at
a reconstitution reads as "outside the top 3000" (false), as does any stock
we can price but cannot rank.
"""

from __future__ import annotations

import csv
import logging
from datetime import date
from pathlib import Path

import duckdb

from identity.source import sql_quote

logger = logging.getLogger(__name__)

DOW_MEMBERSHIP_PATH = Path(__file__).resolve().parent / "reference" / "dow_membership.csv"
# Last Dow change encoded in that file (NVDA/SHW in, INTC/DOW out).
DOW_VERIFIED_THROUGH = date(2024, 11, 8)

# Membership dates may fall outside a reused ticker's price-coverage window
# (a removal is usually announced around the delisting or merger close).
MEMBERSHIP_GRACE_DAYS = 366

# Russell proxy calendar and breakpoints (see the module docstring).
RUSSELL_RANK_DAY = (5, 31)
RUSSELL_EFFECTIVE_DAY = (7, 1)
RUSSELL_LARGE_CAP_COUNT = 1000
RUSSELL_TOTAL_COUNT = 3000

FAR_FUTURE = "DATE '9999-12-31'"


def load_dow_spells(path: Path = DOW_MEMBERSHIP_PATH) -> tuple[tuple[str, str, str], ...]:
    """Parse the Dow membership file into (ticker, member_from, member_to).

    Open-ended spells come back with an explicit far-future end date so the
    SQL below never has to special-case NULL.
    """
    lines = [
        line
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    spells = []
    for row in csv.DictReader(lines):
        ticker = (row["ticker"] or "").strip()
        member_from = (row["member_from"] or "").strip()
        member_to = (row["member_to"] or "").strip() or "9999-12-31"
        if not ticker or not member_from:
            raise ValueError(f"{path}: row missing ticker/member_from: {row!r}")
        if member_to < member_from:
            raise ValueError(f"{path}: {ticker} spell ends before it starts: {row!r}")
        spells.append((ticker, member_from, member_to))
    if not spells:
        raise ValueError(f"{path}: no membership spells")
    return tuple(spells)


def dow_coverage_start(spells: tuple[tuple[str, str, str], ...]) -> str:
    return min(spell[1] for spell in spells)


def _spells_from_events(events_view: str, index_name: str) -> str:
    """SQL folding a member/non-member event stream into membership spells.

    Gaps-and-islands: each island starts at a `is_member` event that follows
    a non-member (or nothing) and runs to the day before the island's first
    non-member event.
    """
    return f"""
        WITH seq AS (
            SELECT permaticker, event_date, is_member,
                   lag(is_member) OVER (
                       PARTITION BY permaticker ORDER BY event_date
                   ) AS prev_member
            FROM {events_view}
        ),
        islands AS (
            SELECT *, sum(
                       CASE WHEN is_member AND NOT coalesce(prev_member, false)
                            THEN 1 ELSE 0 END
                   ) OVER (
                       PARTITION BY permaticker ORDER BY event_date
                       ROWS UNBOUNDED PRECEDING
                   ) AS island
            FROM seq
        )
        SELECT {sql_quote(index_name)} AS index_name,
               permaticker,
               min(event_date) AS member_from,
               coalesce(
                   min(event_date) FILTER (WHERE NOT is_member) - 1,
                   {FAR_FUTURE}
               ) AS member_to
        FROM islands
        WHERE island >= 1
        GROUP BY permaticker, island
    """


def build_sp500_spell_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create `sp500_spells` from the raw SP500 action table (`sp500_raw`)."""
    grace = MEMBERSHIP_GRACE_DAYS
    # Same ticker->permaticker rule as the rest of the pipeline: unambiguous
    # tickers resolve unconditionally, reused tickers go to the permaticker
    # whose price-coverage window (widened by the grace) covers the event.
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW sp500_events_resolved AS
        WITH ev AS (
            SELECT ticker, date AS event_date, lower(trim(action)) AS action
            FROM sp500_raw
            WHERE ticker IS NOT NULL AND date IS NOT NULL AND action IS NOT NULL
        ),
        matched AS (
            SELECT m.permaticker, ev.event_date, ev.action,
                   row_number() OVER (
                       PARTITION BY ev.ticker, ev.event_date, ev.action
                       ORDER BY CASE
                           WHEN ev.event_date
                                BETWEEN coalesce(m.firstpricedate, DATE '0001-01-01')
                                    AND coalesce(m.lastpricedate, {FAR_FUTURE})
                           THEN 0
                           ELSE least(
                               abs(ev.event_date - coalesce(m.firstpricedate, ev.event_date)),
                               abs(ev.event_date - coalesce(m.lastpricedate, ev.event_date))
                           )
                       END
                   ) AS rn
            FROM ev
            JOIN price_mapping m
              ON ev.ticker = m.ticker
             AND (NOT m.ticker_is_reused
                  OR (ev.event_date >= coalesce(m.firstpricedate - {grace},
                                                DATE '0001-01-01')
                      AND ev.event_date <= coalesce(m.lastpricedate + {grace},
                                                    {FAR_FUTURE})))
        )
        SELECT permaticker, event_date, action FROM matched WHERE rn = 1
        """
    )
    # One event per (permaticker, date); a removal on a date wins over any
    # membership marker sharing it.
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW sp500_events AS
        SELECT permaticker, event_date,
               bool_and(action <> 'removed') AS is_member
        FROM sp500_events_resolved
        GROUP BY permaticker, event_date
        """
    )
    # Seeding: only an `added` event dates a membership precisely. A ticker
    # whose earliest event is `removed`/`historical`/`current` was already a
    # constituent when the table's history begins.
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW sp500_events_seeded AS
        WITH coverage AS (SELECT min(event_date) AS start FROM sp500_events),
        firsts AS (
            SELECT permaticker, min(event_date) AS first_date
            FROM sp500_events_resolved GROUP BY permaticker
        ),
        first_actions AS (
            SELECT r.permaticker, bool_or(r.action = 'added') AS starts_with_add
            FROM sp500_events_resolved r
            JOIN firsts f
              ON f.permaticker = r.permaticker AND r.event_date = f.first_date
            GROUP BY r.permaticker
        ),
        seeded AS (
            SELECT permaticker, (SELECT start FROM coverage) AS event_date,
                   true AS is_member
            FROM first_actions WHERE NOT starts_with_add
        )
        SELECT permaticker, event_date, bool_and(is_member) AS is_member
        FROM (SELECT * FROM sp500_events UNION ALL SELECT * FROM seeded)
        GROUP BY permaticker, event_date
        """
    )
    con.execute(
        "CREATE OR REPLACE TEMP VIEW sp500_spells AS "
        + _spells_from_events("sp500_events_seeded", "sp500")
    )


def build_dow_spell_view(
    con: duckdb.DuckDBPyConnection,
    spells: tuple[tuple[str, str, str], ...] | None = None,
) -> None:
    """Create `dow_spells` from the checked-in constituent history."""
    spells = spells if spells is not None else load_dow_spells()
    values = ", ".join(
        f"({sql_quote(ticker)}, DATE {sql_quote(start)}, DATE {sql_quote(end)})"
        for ticker, start, end in spells
    )
    grace = MEMBERSHIP_GRACE_DAYS
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW dow_membership_static AS
        SELECT * FROM (VALUES {values}) AS t(ticker, member_from, member_to)
        """
    )
    # A spell resolves to the permaticker whose price-coverage window
    # overlaps it most — that is what separates the two companies that held
    # the ticker `T` (AT&T Corp, then AT&T Inc.).
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW dow_spells AS
        SELECT 'dow' AS index_name, permaticker, member_from, member_to
        FROM (
            SELECT m.permaticker, d.member_from, d.member_to,
                   row_number() OVER (
                       PARTITION BY d.ticker, d.member_from
                       ORDER BY least(d.member_to,
                                      coalesce(m.lastpricedate, {FAR_FUTURE}))
                              - greatest(d.member_from,
                                         coalesce(m.firstpricedate,
                                                  DATE '0001-01-01')) DESC,
                                m.permaticker
                   ) AS rn
            FROM dow_membership_static d
            JOIN price_mapping m
              ON m.ticker = d.ticker
             AND coalesce(m.firstpricedate - {grace}, DATE '0001-01-01')
                 <= d.member_to
             AND coalesce(m.lastpricedate + {grace}, {FAR_FUTURE})
                 >= d.member_from
        ) WHERE rn = 1
        """
    )


def build_russell_spell_views(con: duckdb.DuckDBPyConnection) -> None:
    """Create `russell_reconstitutions` and the proxy `russell_spells`."""
    rank_month, rank_day = RUSSELL_RANK_DAY
    eff_month, eff_day = RUSSELL_EFFECTIVE_DAY
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW russell_reconstitutions AS
        WITH years AS (SELECT DISTINCT year(date) AS y FROM trading_calendar),
        days AS (
            SELECT y,
                   (SELECT max(c.date) FROM trading_calendar c
                     WHERE c.date <= make_date(y, {rank_month}, {rank_day}))
                       AS rank_day,
                   (SELECT min(c.date) FROM trading_calendar c
                     WHERE c.date >= make_date(y, {eff_month}, {eff_day}))
                       AS effective_from
            FROM years
        ),
        present AS (
            SELECT * FROM days
            WHERE rank_day IS NOT NULL AND effective_from IS NOT NULL
        )
        SELECT y, rank_day, effective_from,
               coalesce(lead(effective_from) OVER (ORDER BY y) - 1,
                        {FAR_FUTURE}) AS effective_to
        FROM present
        """
    )
    # Market cap on the rank day, built the ADR 0007 way (close x shares from
    # the last filing public before the rank day) over *all* common stocks,
    # financials included: the Russell breakpoints are set on the whole
    # market, not on this dataset's universe.
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW russell_rank_caps AS
        SELECT x.effective_from, x.effective_to, x.permaticker,
               x.close * f.l_sharesbas * f.l_sharefactor AS marketcap
        FROM (
            SELECT r.rank_day, r.effective_from, r.effective_to,
                   p.permaticker, p.close
            FROM russell_reconstitutions r
            JOIN sep_common p ON p.date = r.rank_day
        ) x
        ASOF JOIN sf1_filings_latest f
          ON x.permaticker = f.permaticker AND x.rank_day > f.datekey
        WHERE f.l_sharesbas * f.l_sharefactor > 0
        """
    )
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW russell_ranked AS
        SELECT *, row_number() OVER (
                   PARTITION BY effective_from
                   ORDER BY marketcap DESC, permaticker
               ) AS cap_rank
        FROM russell_rank_caps
        """
    )
    large, total = RUSSELL_LARGE_CAP_COUNT, RUSSELL_TOTAL_COUNT
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW russell_spells AS
        SELECT 'russell1000' AS index_name, permaticker,
               effective_from AS member_from, effective_to AS member_to
        FROM russell_ranked WHERE cap_rank <= {large}
        UNION ALL
        SELECT 'russell2000', permaticker, effective_from, effective_to
        FROM russell_ranked WHERE cap_rank > {large} AND cap_rank <= {total}
        UNION ALL
        SELECT 'russell3000', permaticker, effective_from, effective_to
        FROM russell_ranked WHERE cap_rank <= {total}
        """
    )


def build_index_spell_views(con: duckdb.DuckDBPyConnection) -> None:
    """Create `index_spells` and `index_coverage` from all three sources."""
    dow = load_dow_spells()
    build_sp500_spell_view(con)
    build_dow_spell_view(con, dow)
    build_russell_spell_views(con)
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW index_spells AS
        SELECT * FROM sp500_spells
        UNION ALL SELECT * FROM dow_spells
        UNION ALL SELECT * FROM russell_spells
        """
    )
    # Coverage start per index: before it, membership is unknown (NULL).
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW index_coverage AS
        SELECT 'sp500' AS index_name,
               (SELECT min(event_date) FROM sp500_events_seeded) AS coverage_start
        UNION ALL SELECT 'dow', DATE {sql_quote(dow_coverage_start(dow))}
        UNION ALL SELECT 'russell',
               (SELECT min(effective_from) FROM russell_reconstitutions)
        """
    )


def log_index_coverage(con: duckdb.DuckDBPyConnection) -> None:
    """Log spell counts per index and warn when the Dow file looks stale."""
    for index_name, spells, permatickers, start in con.execute(
        """
        SELECT index_name, count(*), count(DISTINCT permaticker), min(member_from)
        FROM index_spells GROUP BY index_name ORDER BY index_name
        """
    ).fetchall():
        logger.info(
            "index %s: %d membership spells across %d permatickers (from %s)",
            index_name, spells, permatickers, start,
        )
    if con.execute("SELECT count(*) FROM sp500_events_seeded").fetchone()[0] == 0:
        logger.warning(
            "no SP500 constituent actions available — in_sp500/days_in_sp500 "
            "will be NULL everywhere (run `sharadar-ingest --tables SP500`)"
        )
    last_snapshot = con.execute("SELECT max(snapshot_date) FROM snapshots").fetchone()[0]
    if last_snapshot is not None and last_snapshot > DOW_VERIFIED_THROUGH:
        logger.warning(
            "Dow membership file is verified through %s but snapshots run to "
            "%s — membership is carried forward; append any later index "
            "changes to %s",
            DOW_VERIFIED_THROUGH, last_snapshot, DOW_MEMBERSHIP_PATH,
        )


def build_index_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_index` view from `snapshots` × `index_spells`."""
    build_index_spell_views(con)
    con.execute(
        """
        CREATE OR REPLACE TEMP VIEW features_index AS
        WITH cov AS (
            SELECT
                max(coverage_start) FILTER (WHERE index_name = 'sp500')
                    AS sp500_start,
                max(coverage_start) FILTER (WHERE index_name = 'dow')
                    AS dow_start,
                max(coverage_start) FILTER (WHERE index_name = 'russell')
                    AS russell_start
            FROM index_coverage
        ),
        member AS (
            SELECT s.permaticker, s.snapshot_date, s.snapshot_kind,
                   max(sp.member_from) FILTER (WHERE sp.index_name = 'sp500')
                       AS sp500_from,
                   max(sp.member_from) FILTER (WHERE sp.index_name = 'dow')
                       AS dow_from,
                   bool_or(sp.index_name = 'russell1000') AS r1000,
                   bool_or(sp.index_name = 'russell2000') AS r2000,
                   bool_or(sp.index_name = 'russell3000') AS r3000
            FROM snapshots s
            JOIN index_spells sp
              ON sp.permaticker = s.permaticker
             AND s.snapshot_date BETWEEN sp.member_from AND sp.member_to
            GROUP BY s.permaticker, s.snapshot_date, s.snapshot_kind
        ),
        flags AS (
            SELECT s.permaticker, s.snapshot_date, s.snapshot_kind,
                   CASE WHEN s.snapshot_date >= cov.sp500_start
                        THEN m.sp500_from IS NOT NULL END AS in_sp500,
                   CASE WHEN s.snapshot_date >= cov.sp500_start
                        THEN (s.snapshot_date - m.sp500_from)::DOUBLE
                        END AS days_in_sp500,
                   CASE WHEN s.snapshot_date >= cov.dow_start
                        THEN m.dow_from IS NOT NULL END AS in_dow,
                   CASE WHEN s.snapshot_date >= cov.dow_start
                        THEN (s.snapshot_date - m.dow_from)::DOUBLE
                        END AS days_in_dow,
                   CASE WHEN s.snapshot_date >= cov.russell_start
                        THEN coalesce(m.r1000, false) END AS in_russell1000,
                   CASE WHEN s.snapshot_date >= cov.russell_start
                        THEN coalesce(m.r2000, false) END AS in_russell2000,
                   CASE WHEN s.snapshot_date >= cov.russell_start
                        THEN coalesce(m.r3000, false) END AS in_russell3000
            FROM snapshots s
            CROSS JOIN cov
            LEFT JOIN member m
              USING (permaticker, snapshot_date, snapshot_kind)
        )
        SELECT permaticker, snapshot_date, snapshot_kind,
               in_sp500, days_in_sp500, in_dow, days_in_dow,
               in_russell1000, in_russell2000, in_russell3000,
               CASE
                   WHEN coalesce(in_sp500, false) OR coalesce(in_dow, false)
                        OR coalesce(in_russell3000, false) THEN true
                   WHEN in_sp500 IS NULL AND in_dow IS NULL
                        AND in_russell3000 IS NULL THEN NULL
                   ELSE false
               END AS in_major_index
        FROM flags
        """
    )
    log_index_coverage(con)
