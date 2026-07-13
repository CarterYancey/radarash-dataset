"""Universe construction per README §3.

In: `Domestic Common Stock` and `Domestic Common Stock Primary Class`,
including delisted stocks (the survivorship-bias point of Sharadar) and REITs.
Out (v1): banks and insurance companies, identified by SIC 6000–6499.

Every permaticker from the source table keeps a row here — exclusion is
expressed as flag columns plus a final `in_universe` verdict, so audits
(V3, V5) can inspect what was excluded and why, and the SIC rule can be
cross-checked against Sharadar's own sector labels before being trusted.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb

from .source import sql_quote

logger = logging.getLogger(__name__)

INCLUDED_CATEGORIES = (
    "Domestic Common Stock",
    "Domestic Common Stock Primary Class",
)

# Banks 6000–6199, brokers/exchanges 6200–6299, insurance 6300–6499.
# REITs are SIC 6798 and therefore stay in. NULL SIC does not exclude:
# a missing code is a data-quality flag (`siccode_missing`), not evidence
# the company is a bank.
FINANCIAL_SIC_RANGE = (6000, 6499)


def build_universe_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create the `universe` view from `tickers_deduped`."""
    categories = ", ".join(sql_quote(c) for c in INCLUDED_CATEGORIES)
    sic_lo, sic_hi = FINANCIAL_SIC_RANGE
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW universe AS
        SELECT
            permaticker,
            ticker,
            name,
            exchange,
            category,
            sector,
            industry,
            famaindustry,
            siccode,
            scalemarketcap,
            is_delisted,
            firstpricedate,
            lastpricedate,
            category IN ({categories}) AS is_common_stock,
            coalesce(siccode BETWEEN {sic_lo} AND {sic_hi}, false)
                AS is_financial_sic,
            sector = 'Financial Services' AS is_financial_sector,
            siccode IS NULL AS siccode_missing,
            category IN ({categories})
                AND NOT coalesce(siccode BETWEEN {sic_lo} AND {sic_hi}, false)
                AS in_universe
        FROM tickers_deduped
        """
    )


def write_universe_table(
    con: duckdb.DuckDBPyConnection,
    interim_dir: Path,
) -> dict[str, int]:
    """Write universe.parquet; return summary counts."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    universe_path = interim_dir / "universe.parquet"
    rows = con.execute(
        f"""
        COPY (SELECT * FROM universe ORDER BY permaticker)
        TO {sql_quote(str(universe_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    ).fetchone()[0]

    summary = con.execute(
        """
        SELECT
            count(*) FILTER (in_universe) AS in_universe,
            count(*) FILTER (in_universe AND is_delisted) AS in_universe_delisted,
            count(*) FILTER (is_common_stock AND is_financial_sic) AS excluded_financials,
            count(*) FILTER (in_universe AND siccode_missing) AS missing_sic,
            count(*) FILTER (in_universe AND is_financial_sector) AS financial_sector_kept
        FROM universe
        """
    ).fetchone()
    counts = {
        "universe_rows": int(rows),
        "in_universe": int(summary[0]),
        "in_universe_delisted": int(summary[1]),
        "excluded_financials": int(summary[2]),
        "in_universe_missing_sic": int(summary[3]),
        "in_universe_financial_sector": int(summary[4]),
    }
    logger.info(
        "universe: %(in_universe)d in-universe (%(in_universe_delisted)d delisted), "
        "%(excluded_financials)d financials excluded by SIC, "
        "%(in_universe_missing_sic)d kept with missing SIC, "
        "%(in_universe_financial_sector)d kept despite 'Financial Services' sector "
        "(V5 cross-check)",
        counts,
    )
    return counts
