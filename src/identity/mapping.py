"""Build the canonical ticker-to-permaticker mapping and V2 audit."""

from dataclasses import dataclass
from pathlib import Path

import duckdb

from .sql import atomic_replace, literal


@dataclass(frozen=True)
class MappingStats:
    mappings: int
    reused_tickers: int
    sep_unmatched_symbols: int
    sep_unmatched_rows: int
    sf1_unmatched_symbols: int
    sf1_unmatched_rows: int


def build_mapping(raw_dir: Path, output_dir: Path) -> MappingStats:
    """Persist exact canonical mappings; never infer history from relatedtickers."""
    tickers, sep, sf1 = (raw_dir / f"{name}.parquet" for name in ("TICKERS", "SEP", "SF1"))
    for path in (tickers, sep, sf1):
        if not path.exists():
            raise FileNotFoundError(f"Required raw table is missing: {path}")
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = {
        "mapping": output_dir / "ticker_permaticker.parquet",
        "reuse": output_dir / "ticker_reuse.parquet",
        "unresolved": output_dir / "unresolved_tickers.parquet",
    }
    temps = {key: path.with_name(f".{path.name}.tmp") for key, path in outputs.items()}
    for path in temps.values():
        path.unlink(missing_ok=True)
    con = duckdb.connect()
    try:
        con.execute(
            f"""CREATE TEMP VIEW canonical AS SELECT *
                FROM read_parquet({literal(tickers)})
                WHERE "table"='SEP' AND ticker IS NOT NULL AND permaticker IS NOT NULL"""
        )
        con.execute(
            """CREATE TEMP VIEW reuse AS
               SELECT ticker, count(DISTINCT permaticker)::INTEGER permaticker_count,
                      list(DISTINCT permaticker ORDER BY permaticker) permatickers
               FROM canonical GROUP BY ticker
               HAVING count(DISTINCT permaticker)>1"""
        )
        reused = int(con.execute("SELECT count(*) FROM reuse").fetchone()[0])
        if reused:
            raise ValueError(f"{reused} canonical tickers map to multiple permatickers")
        con.execute(
            f"""COPY (SELECT ticker,permaticker,firstpricedate valid_from,
                       lastpricedate valid_to,isdelisted,lastupdated
                       FROM canonical ORDER BY ticker)
                TO {literal(temps["mapping"])} (FORMAT PARQUET,COMPRESSION ZSTD)"""
        )
        con.execute(
            f"COPY (SELECT * FROM reuse ORDER BY ticker) TO {literal(temps['reuse'])} "
            "(FORMAT PARQUET,COMPRESSION ZSTD)"
        )
        con.execute(
            f"""CREATE TEMP VIEW unresolved AS
                SELECT 'SEP'::VARCHAR source_table,ticker,min(date) first_source_date,
                       max(date) last_source_date,count(*)::BIGINT row_count
                FROM read_parquet({literal(sep)}) s
                WHERE ticker IS NULL OR NOT EXISTS
                      (SELECT 1 FROM canonical m WHERE m.ticker=s.ticker)
                GROUP BY ticker
                UNION ALL
                SELECT 'SF1',ticker,min(datekey),max(datekey),count(*)::BIGINT
                FROM read_parquet({literal(sf1)}) s
                WHERE ticker IS NULL OR NOT EXISTS
                      (SELECT 1 FROM canonical m WHERE m.ticker=s.ticker)
                GROUP BY ticker"""
        )
        con.execute(
            f"""COPY (SELECT * FROM unresolved ORDER BY source_table,ticker NULLS LAST)
                TO {literal(temps["unresolved"])} (FORMAT PARQUET,COMPRESSION ZSTD)"""
        )
        mappings = int(con.execute("SELECT count(*) FROM canonical").fetchone()[0])
        unmatched = {
            row[0]: (int(row[1]), int(row[2]))
            for row in con.execute(
                """SELECT source_table,count(*) FILTER (WHERE ticker IS NOT NULL),
                          coalesce(sum(row_count),0)
                   FROM unresolved GROUP BY source_table"""
            ).fetchall()
        }
    finally:
        con.close()
    for key in outputs:
        atomic_replace(temps[key], outputs[key])
    sep_stats, sf1_stats = unmatched.get("SEP", (0, 0)), unmatched.get("SF1", (0, 0))
    return MappingStats(mappings, reused, sep_stats[0], sep_stats[1], sf1_stats[0], sf1_stats[1])
