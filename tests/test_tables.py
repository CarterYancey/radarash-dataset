import pytest

from ingest.tables import DEFAULT_TABLE_ORDER, TABLES, resolve_tables


def test_registry_covers_all_readme_tables():
    assert set(TABLES) == {
        "SF1", "SEP", "SFP", "TICKERS", "ACTIONS", "EVENTS", "DAILY", "SP500",
    }
    assert set(DEFAULT_TABLE_ORDER) == set(TABLES)


def test_every_table_forces_ticker_to_varchar():
    # Tickers like "TRUE" or "ONE" must never be sniffed as bool/number.
    for spec in TABLES.values():
        assert spec.column_types.get("ticker") == "VARCHAR", spec.name


def test_eventcodes_is_text():
    # eventcodes is a comma-separated numeric list; sniffing it as a number
    # on single-code rows would corrupt multi-code rows.
    assert TABLES["EVENTS"].column_types["eventcodes"] == "VARCHAR"


def test_qualified_name():
    assert TABLES["SF1"].qualified_name == "SHARADAR/SF1"


def test_resolve_tables_default_is_everything():
    assert [s.name for s in resolve_tables(None)] == list(DEFAULT_TABLE_ORDER)


def test_resolve_tables_accepts_case_and_prefix():
    specs = resolve_tables(["sep", "SHARADAR/SF1"])
    assert [s.name for s in specs] == ["SEP", "SF1"]


def test_resolve_tables_rejects_unknown():
    with pytest.raises(KeyError, match="unknown table 'NOPE'"):
        resolve_tables(["NOPE"])
