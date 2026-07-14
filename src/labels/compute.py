"""Compute endpoint labels with delisting-aware terminal values."""

from dataclasses import dataclass
from pathlib import Path

import duckdb

from identity.sql import atomic_replace, literal

HORIZONS = (1, 2, 3, 5)
THRESHOLDS = (0, 5, 8, 10)


@dataclass(frozen=True)
class LabelStats:
    rows: int
    complete_1y: int
    complete_5y: int


def build_labels(raw_dir: Path, interim_dir: Path) -> LabelStats:
    paths = {
        "sep": raw_dir / "SEP.parquet",
        "sfp": raw_dir / "SFP.parquet",
        "actions": raw_dir / "ACTIONS.parquet",
        "snapshots": interim_dir / "snapshots.parquet",
        "universe": interim_dir / "universe.parquet",
    }
    for path in paths.values():
        if not path.exists():
            raise FileNotFoundError(f"Required table is missing: {path}")
    output, temporary = interim_dir / "labels.parquet", interim_dir / ".labels.parquet.tmp"
    temporary.unlink(missing_ok=True)
    pieces = {h: interim_dir / f".labels_{h}y.tmp.parquet" for h in HORIZONS}
    for path in pieces.values():
        path.unlink(missing_ok=True)
    con = duckdb.connect()
    con.execute(f"SET temp_directory={literal(interim_dir / '.duckdb-labels-tmp')}")
    try:
        con.execute(
            f"""CREATE TEMP TABLE stock_roll AS
                SELECT ticker,date,closeadj,
                       avg(closeadj) OVER w terminal_avg,
                       min(closeadj) OVER w terminal_min,
                       max(closeadj) OVER w terminal_max
                FROM read_parquet({literal(paths["sep"])})
                WHERE closeadj IS NOT NULL AND closeadj>0
                WINDOW w AS (PARTITION BY ticker ORDER BY date ROWS BETWEEN 20 PRECEDING AND CURRENT ROW)"""
        )
        con.execute(
            f"""CREATE TEMP TABLE spy_roll AS
                SELECT date,closeadj,
                       avg(closeadj) OVER w terminal_avg
                FROM read_parquet({literal(paths["sfp"])})
                WHERE ticker='SPY' AND closeadj IS NOT NULL AND closeadj>0
                WINDOW w AS (ORDER BY date ROWS BETWEEN 20 PRECEDING AND CURRENT ROW)"""
        )
        con.execute(
            f"""CREATE TEMP VIEW reasons AS
                SELECT ticker,lastpricedate,
                       coalesce(action,'delisted') reason
                FROM (
                    SELECT u.ticker,u.lastpricedate,a.action,
                           row_number() OVER (
                               PARTITION BY u.ticker
                               ORDER BY CASE a.action
                                   WHEN 'bankruptcyliquidation' THEN 1
                                   WHEN 'regulatorydelisting' THEN 2
                                   WHEN 'voluntarydelisting' THEN 3
                                   WHEN 'acquisitionby' THEN 4
                                   WHEN 'mergerto' THEN 5
                                   WHEN 'delisted' THEN 6 ELSE 7 END,
                                   abs(date_diff('day',u.lastpricedate,a.date))
                           ) rank
                    FROM read_parquet({literal(paths["universe"])}) u
                    LEFT JOIN read_parquet({literal(paths["actions"])}) a
                      ON a.ticker=u.ticker
                     AND a.action IN ('bankruptcyliquidation','regulatorydelisting',
                                      'voluntarydelisting','acquisitionby','mergerto','delisted')
                     AND a.date BETWEEN u.lastpricedate-INTERVAL 30 DAY
                                    AND u.lastpricedate+INTERVAL 30 DAY
                    WHERE u.isdelisted='Y'
                ) WHERE rank=1"""
        )
        for horizon in HORIZONS:
            _build_horizon(con, paths, pieces[horizon], horizon)
        joins = "\n".join(
            f"LEFT JOIN read_parquet({literal(pieces[h])}) h{h} USING(snapshot_id)"
            for h in HORIZONS
        )
        columns = ",\n".join(f"h{h}.* EXCLUDE(snapshot_id)" for h in HORIZONS)
        con.execute(
            f"""COPY (
                SELECT s.*,{columns}
                FROM read_parquet({literal(paths["snapshots"])}) s
                {joins}
                ORDER BY s.snapshot_id
            ) TO {literal(temporary)}
            (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 100000)"""
        )
        rows, complete_1y, complete_5y = con.execute(
            f"""SELECT count(*),count(fwd_1y_cagr),count(fwd_5y_cagr)
                FROM read_parquet({literal(temporary)})"""
        ).fetchone()
    finally:
        con.close()
        for path in pieces.values():
            path.unlink(missing_ok=True)
    atomic_replace(temporary, output)
    return LabelStats(int(rows), int(complete_1y), int(complete_5y))


def _build_horizon(con: duckdb.DuckDBPyConnection, paths: dict[str, Path],
                   output: Path, horizon: int) -> None:
    h = f"{horizon}y"
    threshold_columns = ",\n".join(
        f"(cagr >= {threshold / 100}) label_{h}_cagr_ge_{threshold}"
        for threshold in THRESHOLDS
    )
    con.execute(
        f"""COPY (
            WITH base AS (
                SELECT s.snapshot_id,s.ticker,s.snapshot_date,s.entry_closeadj,
                       s.snapshot_date+INTERVAL {horizon} YEAR target_date,
                       u.lastpricedate,u.isdelisted,r.reason,
                       u.isdelisted='Y' AND u.lastpricedate>=s.snapshot_date
                         AND u.lastpricedate<=s.snapshot_date+INTERVAL {horizon} YEAR delisted,
                       final.closeadj final_closeadj
                FROM read_parquet({literal(paths["snapshots"])}) s
                JOIN read_parquet({literal(paths["universe"])}) u USING(permaticker)
                LEFT JOIN reasons r
                  ON r.ticker=s.ticker AND r.lastpricedate=u.lastpricedate
                LEFT JOIN stock_roll final
                  ON final.ticker=u.ticker AND final.date=u.lastpricedate
            ), stock_endpoint AS (
                SELECT b.*,p.date endpoint_date,p.closeadj endpoint_p2p,
                       p.terminal_avg,p.terminal_min,p.terminal_max
                FROM base b ASOF LEFT JOIN stock_roll p
                  ON b.ticker=p.ticker AND b.target_date>=p.date
            ), with_spy_end AS (
                SELECT s.*,spy.closeadj spy_end
                FROM stock_endpoint s ASOF LEFT JOIN spy_roll spy
                  ON s.target_date>=spy.date
            ), endpoints AS (
                SELECT s.*,entry.closeadj spy_entry,
                       CASE WHEN delisted THEN final_closeadj
                            WHEN lastpricedate>=target_date THEN s.terminal_avg END terminal_value,
                       CASE WHEN delisted THEN final_closeadj
                            WHEN lastpricedate>=target_date THEN endpoint_p2p END p2p_value,
                       CASE WHEN delisted THEN final_closeadj
                            WHEN lastpricedate>=target_date THEN s.terminal_min END min_value,
                       CASE WHEN delisted THEN final_closeadj
                            WHEN lastpricedate>=target_date THEN s.terminal_max END max_value
                FROM with_spy_end s ASOF LEFT JOIN spy_roll entry
                  ON s.snapshot_date>=entry.date
            ), returns AS (
                SELECT *,
                       pow(terminal_value/entry_closeadj,1.0/{horizon})-1 cagr,
                       pow(p2p_value/entry_closeadj,1.0/{horizon})-1 cagr_p2p,
                       pow(min_value/entry_closeadj,1.0/{horizon})-1 min_cagr,
                       pow(max_value/entry_closeadj,1.0/{horizon})-1 max_cagr,
                       pow(spy_end/spy_entry,1.0/{horizon})-1 spy_cagr
                FROM endpoints
            )
            SELECT snapshot_id,
                   terminal_value fwd_{h}_closeadj_avg,
                   p2p_value fwd_{h}_closeadj_p2p,
                   min_value fwd_{h}_closeadj_min,
                   max_value fwd_{h}_closeadj_max,
                   cagr fwd_{h}_cagr,cagr_p2p fwd_{h}_cagr_p2p,
                   min_cagr fwd_{h}_min_cagr,max_cagr fwd_{h}_max_cagr,
                   spy_cagr fwd_{h}_spy_cagr,
                   cagr-spy_cagr fwd_{h}_excess_cagr,
                   {threshold_columns},
                   (cagr>spy_cagr) label_{h}_beat_spy,
                   CASE WHEN delisted THEN coalesce(reason,'delisted')
                        ELSE 'False' END delisted_in_window_{h}
            FROM returns
        ) TO {literal(output)}
        (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 100000)"""
    )
