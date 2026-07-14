.PHONY: ingest identity test

ingest:
	uv run sharadar-ingest download

identity:
	uv run sharadar-identity

test:
	uv run pytest
