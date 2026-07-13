# Optional subset, e.g.: make ingest TABLES="TICKERS SEP"
TABLES ?=

.PHONY: ingest identity test

ingest:
	uv run sharadar-ingest $(if $(TABLES),--tables $(TABLES))

identity:
	uv run sharadar-identity

test:
	uv run pytest
