# Optional subset, e.g.: make ingest TABLES="TICKERS SEP"
TABLES ?=

.PHONY: ingest identity labels test

ingest:
	uv run sharadar-ingest $(if $(TABLES),--tables $(TABLES))

identity:
	uv run sharadar-identity

labels:
	uv run sharadar-labels

test:
	uv run pytest
