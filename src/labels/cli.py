"""CLI for quarterly snapshots and forward labels."""

import argparse
from pathlib import Path

from .compute import build_labels
from .snapshots import build_snapshots


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build quarterly price snapshots and labels")
    parser.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    parser.add_argument("--interim-dir", type=Path, default=Path("data/interim"))
    parser.add_argument("--start-year", type=int, default=1998)
    parser.add_argument("--snapshots-only", action="store_true")
    args = parser.parse_args(argv)
    snapshots = build_snapshots(args.raw_dir, args.interim_dir, start_year=args.start_year)
    print(f"snapshots: {snapshots.snapshots:,} across {snapshots.quarters:,} stock-quarters")
    if not args.snapshots_only:
        labels = build_labels(args.raw_dir, args.interim_dir)
        print(f"labels: {labels.rows:,}; complete 1y/5y: "
              f"{labels.complete_1y:,}/{labels.complete_5y:,}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
