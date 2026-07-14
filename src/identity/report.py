"""Annual survivorship-depth table and M1 exit chart."""

import os
from dataclasses import dataclass
from pathlib import Path

import duckdb

from .sql import atomic_replace, literal


@dataclass(frozen=True)
class ReportStats:
    first_year: int
    last_year: int
    peak_count: int


def build_universe_counts(raw_dir: Path, output_dir: Path, *, start_year: int = 1998) -> ReportStats:
    universe, sep = output_dir / "universe.parquet", raw_dir / "SEP.parquet"
    for path in (universe, sep):
        if not path.exists():
            raise FileNotFoundError(f"Required table is missing: {path}")
    reports = output_dir / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    output = output_dir / "universe_counts_by_year.parquet"
    temporary = output_dir / ".universe_counts_by_year.parquet.tmp"
    temporary.unlink(missing_ok=True)
    con = duckdb.connect()
    try:
        max_date = con.execute(f"SELECT max(date) FROM read_parquet({literal(sep)})").fetchone()[0]
        if max_date is None:
            raise ValueError("SEP contains no dates")
        max_sql = literal(max_date)
        con.execute(
            f"""COPY (
                WITH years AS (
                    SELECT year,least(make_date(year,12,31),DATE {max_sql}) as_of_date
                    FROM generate_series({start_year},year(DATE {max_sql})) y(year)
                ), active AS (
                    SELECT y.year,y.as_of_date,u.* FROM years y
                    JOIN read_parquet({literal(universe)}) u
                      ON u.firstpricedate<=y.as_of_date AND u.lastpricedate>=y.as_of_date
                )
                SELECT year,as_of_date,count(*)::INTEGER total,
                       count(*) FILTER (WHERE isdelisted='Y')::INTEGER delisted_later,
                       count(*) FILTER (WHERE isdelisted='N')::INTEGER survives_snapshot
                FROM active GROUP BY year,as_of_date ORDER BY year
            ) TO {literal(temporary)} (FORMAT PARQUET,COMPRESSION ZSTD)"""
        )
    finally:
        con.close()
    atomic_replace(temporary, output)
    return _plot_counts(output, reports / "universe_counts_by_year.png")


def _plot_counts(counts: Path, destination: Path) -> ReportStats:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = duckdb.sql(
        "SELECT year,total,delisted_later,survives_snapshot FROM read_parquet(?) ORDER BY year",
        params=[str(counts)],
    ).fetchall()
    if not rows:
        raise ValueError("Universe-count report contains no years")
    years, total, delisted, survivors = map(list, zip(*rows, strict=True))
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.plot(years, total, color="#172554", linewidth=2.5, label="Total universe")
    ax.fill_between(years, 0, delisted, color="#dc2626", alpha=.28,
                    label="Delisted at/after as-of date")
    ax.fill_between(years, delisted, [d+s for d,s in zip(delisted,survivors,strict=True)],
                    color="#2563eb", alpha=.22, label="Survives source snapshot")
    ax.set(title="Sharadar non-financial U.S. common-stock universe",
           xlabel="Calendar year end (latest source date for partial current year)",
           ylabel="Eligible securities")
    ax.grid(axis="y", color="#cbd5e1", linewidth=.7, alpha=.7)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, ncols=3, loc="upper left")
    fig.text(.01,.01,"Includes delisted stocks; excludes SIC 6000–6499 and Sharadar Financial Services.",
             fontsize=8,color="#475569")
    fig.tight_layout(rect=(0,.04,1,1))
    temporary = destination.with_name(f".{destination.name}.tmp.png")
    fig.savefig(temporary,dpi=160)
    plt.close(fig)
    os.replace(temporary,destination)
    return ReportStats(int(years[0]),int(years[-1]),int(max(total)))
