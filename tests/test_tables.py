import pytest

from ingest.tables import TABLES, table_spec


def test_milestone_tables_are_registered():
    assert set(TABLES) == {"TICKERS", "SF1", "SEP", "SFP", "ACTIONS", "EVENTS", "DAILY"}
    assert table_spec("sep").code == "SHARADAR/SEP"


def test_unknown_table_has_actionable_error():
    with pytest.raises(ValueError, match="Unknown table"):
        table_spec("prices")
