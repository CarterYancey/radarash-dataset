"""Raw table registry."""

from dataclasses import dataclass


@dataclass(frozen=True)
class TableSpec:
    name: str
    description: str
    sort_by: tuple[str, ...]

    @property
    def code(self) -> str:
        return f"SHARADAR/{self.name}"


TABLES = {
    spec.name: spec
    for spec in (
        TableSpec("TICKERS", "Ticker metadata and permanent identifiers.", ("table", "permaticker")),
        TableSpec("SF1", "Fundamentals, including as-reported dimensions.", ("ticker", "dimension", "datekey")),
        TableSpec("SEP", "Daily equity prices and adjusted closes.", ("ticker", "date")),
        TableSpec("SFP", "Daily fund prices used for benchmarks.", ("ticker", "date")),
        TableSpec("ACTIONS", "Corporate actions, including delistings and mergers.", ("ticker", "date")),
        TableSpec("EVENTS", "Company events, including delisting events.", ("ticker", "date")),
        TableSpec("DAILY", "Daily-computed valuation and market-cap metrics.", ("ticker", "date")),
    )
}


def table_spec(name: str) -> TableSpec:
    try:
        return TABLES[name.upper()]
    except KeyError as error:
        raise ValueError(f"Unknown table {name!r}; choose one of: {', '.join(TABLES)}") from error
