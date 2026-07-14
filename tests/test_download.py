from unittest.mock import patch

import duckdb

from ingest.download import ingest_table
from ingest.tables import table_spec


def test_existing_raw_table_is_kept_without_api_call(tmp_path):
    path = tmp_path / "TICKERS.parquet"
    duckdb.sql(
        "COPY (SELECT 'SEP' AS table, 1 AS permaticker) TO ? (FORMAT PARQUET)",
        params=[str(path)],
    )
    with patch("ingest.download.wait_for_export") as request:
        result, stats, changed = ingest_table(table_spec("TICKERS"), tmp_path, "unused")
    assert result == path
    assert stats.rows == 1
    assert stats.columns == ("table", "permaticker")
    assert changed is False
    request.assert_not_called()
