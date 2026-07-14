import duckdb

from identity.mapping import build_mapping


def test_mapping_is_exact_and_unmatched_symbols_are_audited(tmp_path):
    raw, output = tmp_path / "raw", tmp_path / "interim"
    raw.mkdir()
    duckdb.sql(
        """COPY (
            SELECT 'SEP'::VARCHAR "table",100::BIGINT permaticker,'A'::VARCHAR ticker,
                   DATE '2020-01-01' firstpricedate,DATE '2022-12-31' lastpricedate,
                   'Y'::VARCHAR isdelisted,DATE '2023-01-01' lastupdated
            UNION ALL SELECT 'SEP',200,'B',DATE '2021-01-01',DATE '2024-12-31','N',DATE '2025-01-01'
        ) TO ? (FORMAT PARQUET)""",
        params=[str(raw / "TICKERS.parquet")],
    )
    duckdb.sql(
        """COPY (
            SELECT 'A'::VARCHAR ticker,DATE '2020-01-02' date
            UNION ALL SELECT 'OLD',DATE '2019-12-31'
        ) TO ? (FORMAT PARQUET)""",
        params=[str(raw / "SEP.parquet")],
    )
    duckdb.sql(
        """COPY (
            SELECT 'B'::VARCHAR ticker,DATE '2022-02-01' datekey
            UNION ALL SELECT 'LEGACY',DATE '2018-02-01'
        ) TO ? (FORMAT PARQUET)""",
        params=[str(raw / "SF1.parquet")],
    )

    stats = build_mapping(raw, output)

    assert stats.mappings == 2
    assert stats.reused_tickers == 0
    assert (stats.sep_unmatched_symbols, stats.sep_unmatched_rows) == (1, 1)
    assert (stats.sf1_unmatched_symbols, stats.sf1_unmatched_rows) == (1, 1)
    assert duckdb.sql(
        "SELECT ticker,permaticker FROM read_parquet(?) ORDER BY ticker",
        params=[str(output / "ticker_permaticker.parquet")],
    ).fetchall() == [("A", 100), ("B", 200)]
    assert duckdb.sql(
        "SELECT source_table,ticker FROM read_parquet(?) ORDER BY source_table",
        params=[str(output / "unresolved_tickers.parquet")],
    ).fetchall() == [("SEP", "OLD"), ("SF1", "LEGACY")]
