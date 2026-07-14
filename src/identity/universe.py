"""Construct the M1 equity universe from Sharadar metadata."""

from dataclasses import dataclass
from pathlib import Path

import duckdb

from .sql import atomic_replace, literal

CATEGORIES = ("Domestic Common Stock", "Domestic Common Stock Primary Class")


@dataclass(frozen=True)
class UniverseStats:
    entities: int
    excluded_financials: int
    earliest_price_date: str
    latest_price_date: str


def build_universe(raw_dir: Path, output_dir: Path) -> UniverseStats:
    tickers = raw_dir / "TICKERS.parquet"
    if not tickers.exists():
        raise FileNotFoundError(f"Required raw table is missing: {tickers}")
    output_dir.mkdir(parents=True, exist_ok=True)
    output, temporary = output_dir / "universe.parquet", output_dir / ".universe.parquet.tmp"
    temporary.unlink(missing_ok=True)
    categories = ", ".join(literal(item) for item in CATEGORIES)
    con = duckdb.connect()
    try:
        con.execute(
            f"""CREATE TEMP VIEW candidates AS
                SELECT *,coalesce(siccode BETWEEN 6000 AND 6499,false)
                         OR lower(coalesce(sector,''))='financial services' is_financial
                FROM read_parquet({literal(tickers)})
                WHERE "table"='SEP' AND category IN ({categories})
                  AND permaticker IS NOT NULL AND ticker IS NOT NULL"""
        )
        duplicates = int(con.execute(
            "SELECT count(*) FROM (SELECT permaticker FROM candidates GROUP BY 1 HAVING count(*)>1)"
        ).fetchone()[0])
        if duplicates:
            raise ValueError(f"Universe contains {duplicates} duplicate permatickers")
        con.execute(
            f"""COPY (
                SELECT permaticker,ticker,name,exchange,isdelisted,category,siccode,
                       sicsector,sicindustry,famaindustry,sector,industry,scalemarketcap,
                       scalerevenue,currency,location,firstpricedate,lastpricedate,
                       firstquarter,lastquarter,lastupdated
                FROM candidates WHERE NOT is_financial ORDER BY permaticker
            ) TO {literal(temporary)} (FORMAT PARQUET,COMPRESSION ZSTD)"""
        )
        entities, earliest, latest = con.execute(
            "SELECT count(*),min(firstpricedate)::VARCHAR,max(lastpricedate)::VARCHAR "
            "FROM candidates WHERE NOT is_financial"
        ).fetchone()
        excluded = con.execute("SELECT count(*) FROM candidates WHERE is_financial").fetchone()[0]
    finally:
        con.close()
    atomic_replace(temporary, output)
    return UniverseStats(int(entities), int(excluded), earliest, latest)
