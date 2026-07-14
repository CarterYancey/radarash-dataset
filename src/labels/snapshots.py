"""Select low, discrete-median, and high price dates in every quarter."""

from dataclasses import dataclass
from pathlib import Path

import duckdb

from identity.sql import atomic_replace, literal


@dataclass(frozen=True)
class SnapshotStats:
    quarters: int
    snapshots: int
    first_date: str
    last_date: str


def build_snapshots(raw_dir: Path, interim_dir: Path, *, start_year: int = 1998) -> SnapshotStats:
    sep, universe = raw_dir / "SEP.parquet", interim_dir / "universe.parquet"
    for path in (sep, universe):
        if not path.exists():
            raise FileNotFoundError(f"Required table is missing: {path}")
    output = interim_dir / "snapshots.parquet"
    temporary = interim_dir / ".snapshots.parquet.tmp"
    temporary.unlink(missing_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""COPY (
                WITH prices AS (
                    SELECT u.permaticker,s.ticker,s.date,s.closeadj,
                           date_trunc('quarter',s.date)::DATE quarter_start
                    FROM read_parquet({literal(sep)}) s
                    JOIN read_parquet({literal(universe)}) u USING(ticker)
                    WHERE s.closeadj IS NOT NULL AND s.closeadj>0
                      AND year(s.date)>={start_year}
                      AND s.date BETWEEN u.firstpricedate AND u.lastpricedate
                ), stats AS (
                    SELECT permaticker,ticker,quarter_start,count(*)::INTEGER quarter_trading_days,
                           min(closeadj) low_price,
                           quantile_disc(closeadj,0.5 ORDER BY closeadj) median_price,
                           max(closeadj) high_price
                    FROM prices GROUP BY permaticker,ticker,quarter_start
                ), selected AS (
                    SELECT p.permaticker,p.ticker,p.quarter_start,s.quarter_trading_days,
                           min(p.date) FILTER (WHERE p.closeadj=s.low_price) low_date,
                           min(p.date) FILTER (WHERE p.closeadj=s.median_price) median_date,
                           min(p.date) FILTER (WHERE p.closeadj=s.high_price) high_date,
                           s.low_price,s.median_price,s.high_price
                    FROM prices p JOIN stats s USING(permaticker,ticker,quarter_start)
                    GROUP BY p.permaticker,p.ticker,p.quarter_start,s.quarter_trading_days,
                             s.low_price,s.median_price,s.high_price
                ), snapshots AS (
                    SELECT permaticker,ticker,quarter_start,quarter_trading_days,
                           low_date snapshot_date,'low'::VARCHAR snapshot_kind,low_price entry_closeadj
                    FROM selected
                    UNION ALL
                    SELECT permaticker,ticker,quarter_start,quarter_trading_days,
                           median_date,'median',median_price FROM selected
                    UNION ALL
                    SELECT permaticker,ticker,quarter_start,quarter_trading_days,
                           high_date,'high',high_price FROM selected
                )
                SELECT row_number() OVER (
                           ORDER BY permaticker,quarter_start,
                           CASE snapshot_kind WHEN 'low' THEN 1 WHEN 'median' THEN 2 ELSE 3 END
                       )::BIGINT snapshot_id,
                       permaticker,ticker,quarter_start AS "quarter",quarter_trading_days,
                       snapshot_date,snapshot_kind,entry_closeadj
                FROM snapshots
                ORDER BY snapshot_id
            ) TO {literal(temporary)}
            (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 100000)"""
        )
        quarters, snapshots, first, last = con.execute(
            f"""SELECT count(DISTINCT (permaticker,"quarter")),count(*),
                       min(snapshot_date)::VARCHAR,max(snapshot_date)::VARCHAR
                FROM read_parquet({literal(temporary)})"""
        ).fetchone()
        if int(snapshots) != int(quarters) * 3:
            raise RuntimeError("Snapshot build did not emit exactly three rows per stock-quarter")
    finally:
        con.close()
    atomic_replace(temporary, output)
    return SnapshotStats(int(quarters), int(snapshots), first, last)
