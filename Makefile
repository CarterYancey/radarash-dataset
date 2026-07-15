# Optional subset, e.g.: make ingest TABLES="TICKERS SEP"
TABLES ?=

.PHONY: ingest identity labels features splits qa test

ingest:
	uv run sharadar-ingest $(if $(TABLES),--tables $(TABLES))

identity:
	uv run sharadar-identity

labels:
	uv run sharadar-labels

features:
	uv run sharadar-features

splits:
	uv run sharadar-splits

qa:
	uv run sharadar-qa coverage
	uv run sharadar-qa staleness
	uv run sharadar-qa daily-pit

test:
	uv run pytest
