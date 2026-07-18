# Optional subset, e.g.: make ingest TABLES="TICKERS SEP"
TABLES ?=

.PHONY: ingest identity labels features splits dataset all qa test

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

dataset:
	uv run sharadar-assemble

# End-to-end from an existing ingest: data/raw -> data/datasets/dataset_v1.0
all: identity labels features splits dataset

qa:
	uv run sharadar-qa coverage
	uv run sharadar-qa staleness
	uv run sharadar-qa daily-pit
	uv run sharadar-qa splits-diag

test:
	uv run pytest
