# Optional subset, e.g.: make ingest TABLES="TICKERS SEP"
TABLES ?=

.PHONY: ingest test

ingest:
	uv run sharadar-ingest $(if $(TABLES),--tables $(TABLES))

test:
	uv run pytest
