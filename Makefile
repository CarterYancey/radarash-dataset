# Optional subset, e.g.: make ingest TABLES="TICKERS SEP"
TABLES ?=

.PHONY: ingest identity labels features qa test

ingest:
	uv run sharadar-ingest $(if $(TABLES),--tables $(TABLES))

identity:
	uv run sharadar-identity

labels:
	uv run sharadar-labels

features:
	uv run sharadar-features

qa:
	uv run sharadar-qa coverage
	uv run sharadar-qa staleness
	uv run sharadar-qa daily-pit
	uv run sharadar-qa splits-diag

test:
	uv run pytest
