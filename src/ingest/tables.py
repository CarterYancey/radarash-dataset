"""Registry of the Sharadar tables this pipeline ingests.

Each table gets a :class:`TableSpec` describing how to read its CSV export
safely (column type overrides where DuckDB's sniffer could guess wrong) and
how to lay out the resulting parquet file (sort order chosen for the joins
downstream modules will run).
"""

from __future__ import annotations

from dataclasses import dataclass, field

PUBLISHER = "SHARADAR"


@dataclass(frozen=True)
class TableSpec:
    """How to download and store one Sharadar table."""

    name: str
    description: str
    # DuckDB type overrides applied on top of CSV sniffing. Only columns that
    # the sniffer could plausibly mis-type need to be listed (e.g. `ticker`
    # values like "TRUE", comma-separated code lists, Y/N flags).
    column_types: dict[str, str] = field(default_factory=dict)
    # ORDER BY for the parquet file. Sorting clusters row groups so DuckDB can
    # prune aggressively on the keys downstream joins filter on.
    sort_by: tuple[str, ...] = ()

    @property
    def qualified_name(self) -> str:
        """Datatable code as the Nasdaq Data Link API expects it."""
        return f"{PUBLISHER}/{self.name}"


_TICKER = {"ticker": "VARCHAR"}
_PRICE_TABLE_TYPES = {**_TICKER, "date": "DATE", "lastupdated": "DATE"}

TABLES: dict[str, TableSpec] = {
    spec.name: spec
    for spec in (
        TableSpec(
            name="TICKERS",
            description="Ticker metadata: permaticker, category, sector/industry, delisting flag.",
            column_types={
                **_TICKER,
                "permaticker": "BIGINT",
                "isdelisted": "VARCHAR",
                "cusips": "VARCHAR",
                "siccode": "VARCHAR",
                "relatedtickers": "VARCHAR",
                "scalemarketcap": "VARCHAR",
                "scalerevenue": "VARCHAR",
                "firstquarter": "DATE",
                "lastquarter": "DATE",
                "firstpricedate": "DATE",
                "lastpricedate": "DATE",
                "firstadded": "DATE",
                "lastupdated": "DATE",
            },
            sort_by=("table", "permaticker"),
        ),
        TableSpec(
            name="SF1",
            description="Fundamentals (quarterly/annual/TTM, as-reported and most-recent dimensions).",
            column_types={
                **_TICKER,
                "dimension": "VARCHAR",
                "calendardate": "DATE",
                "datekey": "DATE",
                "reportperiod": "DATE",
                "lastupdated": "DATE",
            },
            sort_by=("ticker", "dimension", "datekey"),
        ),
        TableSpec(
            name="SEP",
            description="Equity prices, daily, incl. closeadj (total-return adjusted).",
            column_types=_PRICE_TABLE_TYPES,
            sort_by=("ticker", "date"),
        ),
        TableSpec(
            name="SFP",
            description="Fund prices (SPY etc.) for benchmark labels.",
            column_types=_PRICE_TABLE_TYPES,
            sort_by=("ticker", "date"),
        ),
        TableSpec(
            name="ACTIONS",
            description="Corporate actions incl. delistings, mergers, splits.",
            column_types={
                **_TICKER,
                "date": "DATE",
                "action": "VARCHAR",
                "contraticker": "VARCHAR",
            },
            sort_by=("ticker", "date"),
        ),
        TableSpec(
            name="EVENTS",
            description="Company event codes (delisting events among them).",
            column_types={
                **_TICKER,
                "date": "DATE",
                # Comma-separated numeric codes; must never be sniffed as a number.
                "eventcodes": "VARCHAR",
            },
            sort_by=("ticker", "date"),
        ),
        TableSpec(
            name="SP500",
            description="S&P 500 constituent actions (added/removed/current/historical).",
            column_types={
                **_TICKER,
                "date": "DATE",
                "action": "VARCHAR",
                "contraticker": "VARCHAR",
            },
            sort_by=("ticker", "date"),
        ),
        TableSpec(
            name="DAILY",
            description="Daily-computed metrics: marketcap, ev, pe, pb, ps.",
            column_types=_PRICE_TABLE_TYPES,
            sort_by=("ticker", "date"),
        ),
    )
}

DEFAULT_TABLE_ORDER: tuple[str, ...] = (
    # Small metadata tables first so a fresh run fails fast on auth/plan
    # problems before committing to the multi-GB price downloads.
    "TICKERS",
    "ACTIONS",
    "EVENTS",
    "SP500",
    "SFP",
    "SF1",
    "DAILY",
    "SEP",
)


def resolve_tables(names: list[str] | None) -> list[TableSpec]:
    """Map user-supplied table names to specs, defaulting to all tables."""
    if not names:
        return [TABLES[name] for name in DEFAULT_TABLE_ORDER]
    specs = []
    for raw in names:
        name = raw.upper().removeprefix(f"{PUBLISHER}/")
        if name not in TABLES:
            known = ", ".join(sorted(TABLES))
            raise KeyError(f"unknown table {raw!r}; known tables: {known}")
        specs.append(TABLES[name])
    return specs
