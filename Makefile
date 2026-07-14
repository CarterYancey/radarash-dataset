.PHONY: ingest identity labels test

ingest:
	uv run sharadar-ingest download

identity:
	uv run sharadar-identity

labels:
	uv run sharadar-labels

test:
	uv run pytest
