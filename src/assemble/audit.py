"""Quarter-key audit of the rank columns (decision 0016).

Ranks are `percent_rank()` within (calendar quarter, snapshot_kind) and tied
values share one rank (decision 0008). A tied group's rank is therefore the
share of that quarter's cross-section sitting below the group — a constant
that belongs to the *quarter*, not the firm, and recurs in no other quarter.
Any rank column with sizeable tie groups (integer scores, counts, a mass at
zero) hands a tree model a lookup key for the calendar quarter; the
downstream era probe dated rows from four such columns with 0.92 accuracy
(docs/research/rank-quarter-keys.md).

This audit measures the property directly on the written parquet, per rank
column and snapshot kind:

    tie_mass          share of rows whose rank value is shared with at least
                      one other row of the same (quarter, kind)
    keyed_mass        share of rows in such tie groups whose rank value occurs
                      in exactly one quarter of that kind — rows carrying a
                      quarter identifier
    max_key_share     the largest keyed tie group as a share of its
                      (quarter, kind) cross-section — the size of the
                      heaviest single quarter constant the column emits
    key_quarter / key_rank_value / key_raw_value
                      where that largest keyed group sits: its quarter, the
                      rank value it shares, and the raw feature value behind
                      it — the raw value is what a registry fix needs (the
                      `pin_value` of a `pinned` policy, or `none` for an
                      integer-valued feature)
    distinct_values / distinct_quarter_value_pairs / quarters
                      the pair count of the brief: ten integer scores over
                      116 quarters give ~1160 pairs and ~1044 values

The gate is `max_key_share`, not `tie_mass`: an integer-valued but
fine-grained column (e.g. days of filing age, hundreds of values per quarter
in groups of a few rows) ties almost every row, yet its constants are too
light and too numerous for histogram binning to resolve. A group holding a
few percent of a cross-section is a resolvable constant. Pinned ranks
(decision 0016) put the mass at the same value in every quarter, so it is
tied but never keyed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from identity.source import sql_quote

logger = logging.getLogger(__name__)

# Default gate: flag a rank column when any (quarter, kind) cross-section has
# a quarter-specific tied rank value carried by more than 2% of its rows.
MAX_KEY_SHARE = 0.02

AUDIT_TABLE = "rank_audit"

AUDIT_COLUMNS: tuple[str, ...] = (
    "rank_column",
    "snapshot_kind",
    "n_rows",
    "quarters",
    "distinct_values",
    "distinct_quarter_value_pairs",
    "tie_mass",
    "keyed_mass",
    "max_key_share",
    "key_quarter",
    "key_rank_value",
    "key_raw_value",
)


def raw_column(rank_column: str) -> str:
    """`{name}_rank` / `{name}_secrank` -> `{name}`."""
    for suffix in ("_secrank", "_rank"):
        if rank_column.endswith(suffix):
            return rank_column[: -len(suffix)]
    raise ValueError(f"{rank_column!r} is not a rank column")


def build_rank_audit_table(
    con: duckdb.DuckDBPyConnection,
    *,
    dataset_parquet: Path,
    columns: tuple[str, ...],
) -> int:
    """Populate the temp table `rank_audit` from the written dataset parquet:
    one row per (rank column, snapshot_kind) with a non-NULL rank. Reads one
    column at a time (column-pruned parquet scans), so it never needs the
    wide table in memory. Returns the number of audit rows."""
    con.execute(f"DROP TABLE IF EXISTS {AUDIT_TABLE}")
    con.execute(
        f"""
        CREATE TEMP TABLE {AUDIT_TABLE} (
            rank_column VARCHAR,
            snapshot_kind VARCHAR,
            n_rows BIGINT,
            quarters BIGINT,
            distinct_values BIGINT,
            distinct_quarter_value_pairs BIGINT,
            tie_mass DOUBLE,
            keyed_mass DOUBLE,
            max_key_share DOUBLE,
            key_quarter DATE,
            key_rank_value DOUBLE,
            key_raw_value DOUBLE
        )
        """
    )
    src = sql_quote(str(dataset_parquet))
    for col in columns:
        raw = raw_column(col)
        con.execute(
            f"""
            INSERT INTO {AUDIT_TABLE}
            WITH g AS (
                SELECT snapshot_kind, quarter, {col} AS v, count(*) AS n,
                       min({raw}) AS raw_v
                FROM read_parquet({src})
                WHERE {col} IS NOT NULL
                GROUP BY ALL
            ), q AS (
                SELECT snapshot_kind, quarter, sum(n) AS n_q
                FROM g GROUP BY ALL
            ), vq AS (
                SELECT snapshot_kind, v, count(*) AS n_quarters
                FROM g GROUP BY ALL
            )
            SELECT {sql_quote(col)} AS rank_column,
                   g.snapshot_kind,
                   sum(g.n) AS n_rows,
                   count(DISTINCT g.quarter) AS quarters,
                   count(DISTINCT g.v) AS distinct_values,
                   count(*) AS distinct_quarter_value_pairs,
                   coalesce(sum(g.n) FILTER (WHERE g.n >= 2), 0)::DOUBLE
                       / sum(g.n) AS tie_mass,
                   coalesce(sum(g.n) FILTER (WHERE g.n >= 2
                                              AND vq.n_quarters = 1), 0)::DOUBLE
                       / sum(g.n) AS keyed_mass,
                   coalesce(max(g.n::DOUBLE / q.n_q)
                            FILTER (WHERE g.n >= 2 AND vq.n_quarters = 1), 0)
                       AS max_key_share,
                   CAST(arg_max(g.quarter, g.n::DOUBLE / q.n_q)
                        FILTER (WHERE g.n >= 2 AND vq.n_quarters = 1) AS DATE)
                       AS key_quarter,
                   arg_max(g.v, g.n::DOUBLE / q.n_q)
                        FILTER (WHERE g.n >= 2 AND vq.n_quarters = 1)
                       AS key_rank_value,
                   arg_max(g.raw_v, g.n::DOUBLE / q.n_q)
                        FILTER (WHERE g.n >= 2 AND vq.n_quarters = 1)
                       AS key_raw_value
            FROM g
            JOIN q USING (snapshot_kind, quarter)
            JOIN vq USING (snapshot_kind, v)
            GROUP BY ALL
            """
        )
    return int(con.execute(f"SELECT count(*) FROM {AUDIT_TABLE}").fetchone()[0])


def write_rank_audit(con: duckdb.DuckDBPyConnection, path: Path) -> None:
    """COPY the audit table to `path` (parquet, or CSV for a .csv path)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fmt = (
        "FORMAT CSV, HEADER"
        if path.suffix == ".csv"
        else "FORMAT PARQUET, COMPRESSION ZSTD"
    )
    con.execute(
        f"""
        COPY (SELECT * FROM {AUDIT_TABLE} ORDER BY rank_column, snapshot_kind)
        TO {sql_quote(str(path))} ({fmt})
        """
    )


def rank_audit_summary(
    con: duckdb.DuckDBPyConnection, *, max_key_share: float
) -> dict[str, object]:
    """Manifest-ready summary: the gate, the per-column worst case over the
    snapshot kinds, and the columns that fail the gate."""
    rows = con.execute(
        f"""
        SELECT rank_column,
               round(max(tie_mass), 4),
               round(max(keyed_mass), 4),
               round(max(max_key_share), 4)
        FROM {AUDIT_TABLE}
        GROUP BY rank_column
        ORDER BY rank_column
        """
    ).fetchall()
    columns = {
        name: {"tie_mass": tie, "keyed_mass": keyed, "max_key_share": share}
        for name, tie, keyed, share in rows
    }
    flagged = {
        name: stats["max_key_share"]
        for name, stats in columns.items()
        if stats["max_key_share"] > max_key_share
    }
    return {
        "max_key_share_threshold": max_key_share,
        "flagged": dict(sorted(flagged.items(), key=lambda kv: -kv[1])),
        "columns": columns,
    }


def flagged_detail(
    con: duckdb.DuckDBPyConnection, *, max_key_share: float
) -> list[tuple]:
    """One row per failing (rank column, kind), worst first:
    (rank_column, snapshot_kind, max_key_share, key_quarter,
    key_rank_value, key_raw_value) — the log/error detail."""
    return con.execute(
        f"""
        SELECT rank_column, snapshot_kind, max_key_share,
               key_quarter, key_rank_value, key_raw_value
        FROM {AUDIT_TABLE}
        WHERE max_key_share > ?
        ORDER BY max_key_share DESC, rank_column, snapshot_kind
        """,
        [max_key_share],
    ).fetchall()


def describe_flagged(detail: list[tuple]) -> list[str]:
    """One line per flagged rank column (worst kind), e.g.
    `gp_to_assets_rank: 19.3% of median 2009-Q2 share rank 0.412 at raw
    value 0` — the raw value says which registry fix applies."""
    lines: list[str] = []
    seen: set[str] = set()
    for col, kind, share, quarter, rank_v, raw_v in detail:
        if col in seen:
            continue
        seen.add(col)
        q = f"{quarter.year}-Q{(quarter.month - 1) // 3 + 1}" if quarter else "?"
        lines.append(
            f"{col}: {share:.1%} of {kind} {q} share rank {rank_v:.3f} "
            f"at raw value {raw_v:g}"
        )
    return lines


def rank_key_error(detail: list[tuple], *, max_key_share: float) -> str:
    lines = describe_flagged(detail)
    return (
        f"rank audit: {len(lines)} rank column(s) carry a calendar-quarter "
        f"key — a quarter-specific tied rank value held by more than "
        f"{max_key_share:.0%} of a cross-section (worst kind per column):\n  "
        + "\n  ".join(lines)
        + "\nThe dataset directory was not kept. Fix each feature's rank "
        f"policy in src/features/registry.py — a mass at one raw value ⇒ "
        f"rank='pinned' with pin_value = that value and pin_rank 0 / 0.5 / 1 "
        f"for a support above / around / below it, an integer-valued feature "
        f"⇒ rank='none' (decision 0016) — and rebuild; or pass "
        f"--allow-rank-keys to publish anyway (the keyed columns are then "
        f"listed in manifest.json['rank_audit']['flagged'])"
    )
