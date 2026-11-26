# Optional subset, e.g.: make ingest TABLES="TICKERS SEP"
TABLES ?=
# Dataset version, e.g.: make all VERSION=1.5.1 (decision 0021; default:
# DEFAULT_VERSION in src/assemble/cli.py)
VERSION ?=

.PHONY: ingest identity labels features splits dataset inference all qa test

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
	uv run sharadar-assemble $(if $(VERSION),--dataset-version $(VERSION))

# Label-free snapshot of today's stocks for a trained model to score
inference:
	uv run sharadar-inference

# End-to-end from an existing ingest: data/raw -> data/datasets/dataset_v$(VERSION)
all: identity labels features splits dataset

qa:
	uv run sharadar-qa coverage
	uv run sharadar-qa staleness
	uv run sharadar-qa daily-pit
	uv run sharadar-qa splits-diag

test:
	uv run pytest
