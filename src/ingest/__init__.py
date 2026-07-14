"""Bulk download and Parquet ingestion for Sharadar source tables."""

from .download import ingest_table
from .tables import TABLES, TableSpec

__all__ = ["TABLES", "TableSpec", "ingest_table"]
