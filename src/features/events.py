"""Corporate-events family (ADR 0024): trailing 8-K item counts from EVENTS.

Sharadar EVENTS lists, per (ticker, date), the item codes of the 8-K filed
that day (item X.0Y -> code XY). Fundamentals describe a company through
its accounts; these are the things management had to announce *between*
the accounts — a restatement, an auditor change, a delisting notice, an
impairment, an unregistered share sale. They are the classic value-trap
markers and no other family carries them.

Each feature is the number of distinct **event dates** carrying the code
in the 365 calendar days before the snapshot:

    snapshot_date − 365 <= event date < snapshot_date

(strictly before: an 8-K filed on the snapshot day may postdate the close;
`<=` for the inference dataset, ADR 0014 — the same cutoff as fundamentals).
`events_8k_days_12m` counts every event date, whatever its codes.

Missing vs. none: counts are NULL when the 365-day window reaches back
before the first date in the EVENTS export (no coverage ⇒ unknown, never
0). Inside coverage a stock with no row simply has no such 8-K: 0. A
company that files no 8-Ks at all (e.g. a 20-F filer) is 0 across the
family, `events_8k_days_12m` included — that column is the context.

Foundation view `event_window` (snapshot × event date × code) is built by
`build_event_window_view`; `build_events_view` aggregates it.
"""

from __future__ import annotations

import duckdb

WINDOW_DAYS = 365

# feature-name stem -> 8-K item code (item X.0Y -> XY), registry order.
EVENT_CODES: dict[str, int] = {
    "earnings_release": 22,  # 2.02 results of operations
    "bankruptcy": 13,  # 1.03 bankruptcy or receivership
    "acquisition": 21,  # 2.01 completion of acquisition / disposition
    "new_obligation": 23,  # 2.03 creation of a direct financial obligation
    "obligation_trigger": 24,  # 2.04 acceleration / default trigger
    "exit_costs": 25,  # 2.05 exit or disposal (restructuring) costs
    "impairment": 26,  # 2.06 material impairments
    "delisting_notice": 31,  # 3.01 notice of delisting / listing-rule failure
    "unregistered_sales": 32,  # 3.02 unregistered sales of equity
    "auditor_change": 41,  # 4.01 change in certifying accountant
    "non_reliance": 42,  # 4.02 non-reliance on issued financials
    "control_change": 51,  # 5.01 change in control
    "officer_change": 52,  # 5.02 departure / appointment of officers
}


def build_event_window_view(
    con: duckdb.DuckDBPyConnection,
    *,
    include_same_day_filings: bool = False,
) -> None:
    """Create `event_window` from `snapshots` and `events_resolved`. Same
    cutoff semantics as `base.build_fund_base_view`."""
    cutoff_op = "<=" if include_same_day_filings else "<"
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW event_window AS
        SELECT s.permaticker, s.snapshot_date, s.snapshot_kind,
               e.date AS event_date, e.code
        FROM snapshots s
        JOIN events_resolved e
          ON e.permaticker = s.permaticker
         AND e.date >= s.snapshot_date - {WINDOW_DAYS}
         AND e.date {cutoff_op} s.snapshot_date
        """
    )


def build_events_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `features_events` view."""
    counts = ",\n                   ".join(
        ["count(DISTINCT w.event_date) AS events_8k_days_12m"]
        + [
            f"count(DISTINCT w.event_date) FILTER (WHERE w.code = {code})"
            f" AS events_{name}_12m"
            for name, code in EVENT_CODES.items()
        ]
    )
    names = ["events_8k_days_12m"] + [
        f"events_{name}_12m" for name in EVENT_CODES
    ]
    out = ",\n               ".join(
        f"CASE WHEN c.covered THEN coalesce(n.{name}, 0) END AS {name}"
        for name in names
    )
    key = "permaticker, snapshot_date, snapshot_kind"
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW features_events AS
        WITH c AS (
            SELECT s.permaticker, s.snapshot_date, s.snapshot_kind,
                   coalesce(s.snapshot_date - {WINDOW_DAYS} >= v.first_date,
                            FALSE) AS covered
            FROM snapshots s
            CROSS JOIN events_coverage v
        ),
        n AS (
            SELECT w.permaticker, w.snapshot_date, w.snapshot_kind,
                   {counts}
            FROM event_window w
            GROUP BY w.permaticker, w.snapshot_date, w.snapshot_kind
        )
        SELECT c.permaticker, c.snapshot_date, c.snapshot_kind,
               {out}
        FROM c
        LEFT JOIN n USING ({key})
        """
    )
