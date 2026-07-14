# V2 — ticker reuse and identifier resolution

Status: accepted for M1 (2026-07-13 source snapshot)

Every non-null current ticker in Sharadar TICKERS/SEP maps to exactly one
permaticker: 21,913 canonical mappings and zero reused current tickers.

The relatedtickers column is not ticker history. It groups related securities
and share classes and produces highly ambiguous mappings when exploded. It must
not be used to resolve SEP or SF1.

An exact join leaves two non-null SEP symbols (2,469 rows) and 58 SF1 symbols
(5,973 rows) unresolved. They are persisted in unresolved_tickers.parquet and
are never assigned heuristically.

## Resolution rule

- Permaticker is the canonical entity key.
- Resolve through ticker_permaticker.parquet with an exact ticker match.
- For SEP, additionally require date between valid_from and valid_to.
- Fail if a future snapshot maps one canonical ticker to several permatickers.

This makes ambiguity observable and prevents silent cross-company joins.
