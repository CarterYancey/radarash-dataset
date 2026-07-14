"""CLI for M1 identity artifacts."""

import argparse
from pathlib import Path

from .mapping import build_mapping
from .report import build_universe_counts
from .universe import build_universe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Sharadar identity and universe artifacts")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/interim"))
    parser.add_argument("--start-year", type=int, default=1998)
    args = parser.parse_args(argv)
    mapping = build_mapping(args.raw_dir, args.output_dir)
    universe = build_universe(args.raw_dir, args.output_dir)
    report = build_universe_counts(args.raw_dir, args.output_dir, start_year=args.start_year)
    print(f"mapping: {mapping.mappings:,}; reused: {mapping.reused_tickers}; "
          f"unresolved SEP/SF1 rows: {mapping.sep_unmatched_rows:,}/{mapping.sf1_unmatched_rows:,}")
    print(f"universe: {universe.entities:,}; excluded financials: {universe.excluded_financials:,}")
    print(f"annual counts: {report.first_year}-{report.last_year}; peak {report.peak_count:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
