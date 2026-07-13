"""Universe counts per year — the M1 exit artifact, feeding V3.

For each calendar year, count the in-universe securities whose trading window
([firstpricedate, lastpricedate]) overlaps that year, split into stocks still
listed today vs. stocks that later delisted. The later-delisted share is the
survivorship depth the dataset exists to preserve; its behavior around
2000–2002 and 2008–2009 is what V3 checks against published statistics.

Outputs a parquet + CSV table and a PNG chart.
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from .source import sql_quote

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class YearCount:
    year: int
    still_listed: int
    later_delisted: int

    @property
    def total(self) -> int:
        return self.still_listed + self.later_delisted


def build_counts_view(
    con: duckdb.DuckDBPyConnection,
    *,
    start_year: int | None = None,
) -> None:
    """Create `universe_counts` from `universe`: one row per calendar year.

    A security counts toward a year if its price window overlaps any part of
    it. Stocks still listed (is_delisted = false) with a missing lastpricedate
    are treated as active through today; rows with no firstpricedate cannot be
    placed in time and are skipped (their count is logged).
    """
    unplaceable = con.execute(
        """
        SELECT count(*) FROM universe
        WHERE in_universe
          AND (firstpricedate IS NULL
               OR (lastpricedate IS NULL AND is_delisted))
        """
    ).fetchone()[0]
    if unplaceable:
        logger.warning(
            "universe counts: skipping %d in-universe securities with no "
            "usable price window",
            unplaceable,
        )

    start_clause = f"GREATEST(min_year, {int(start_year)})" if start_year else "min_year"
    con.execute(
        f"""
        CREATE OR REPLACE TEMP VIEW universe_counts AS
        WITH active AS (
            SELECT
                is_delisted,
                firstpricedate,
                coalesce(
                    lastpricedate,
                    CASE WHEN NOT is_delisted THEN current_date END
                ) AS last_active
            FROM universe
            WHERE in_universe AND firstpricedate IS NOT NULL
        ),
        bounds AS (
            SELECT extract(year FROM min(firstpricedate))::INT AS min_year
            FROM active
        ),
        years AS (
            SELECT unnest(range(
                (SELECT {start_clause} FROM bounds),
                extract(year FROM current_date)::INT + 1
            ))::INT AS year
        )
        SELECT
            y.year,
            count(*) FILTER (WHERE NOT a.is_delisted) AS still_listed,
            count(*) FILTER (WHERE a.is_delisted) AS later_delisted,
            count(*) AS total
        FROM years y
        JOIN active a
          ON a.firstpricedate <= make_date(y.year, 12, 31)
         AND a.last_active >= make_date(y.year, 1, 1)
        GROUP BY y.year
        ORDER BY y.year
        """
    )


def write_counts_tables(
    con: duckdb.DuckDBPyConnection,
    interim_dir: Path,
) -> list[YearCount]:
    """Write the per-year counts as parquet and CSV; return them."""
    interim_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = interim_dir / "universe_counts_by_year.parquet"
    con.execute(
        f"""
        COPY (SELECT * FROM universe_counts)
        TO {sql_quote(str(parquet_path))} (FORMAT PARQUET, COMPRESSION ZSTD)
        """
    )
    rows = con.execute(
        "SELECT year, still_listed, later_delisted FROM universe_counts"
    ).fetchall()
    counts = [YearCount(*row) for row in rows]

    csv_path = interim_dir / "universe_counts_by_year.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["year", "still_listed", "later_delisted", "total"])
        writer.writerows(
            (c.year, c.still_listed, c.later_delisted, c.total) for c in counts
        )
    logger.info("universe counts: %d years -> %s", len(counts), parquet_path)
    return counts


# Reference dataviz palette (light mode), validated: worst adjacent CVD
# ΔE 73.6. The aqua slot is sub-3:1 on the light surface, so the counts
# also ship as a CSV/parquet table (relief rule).
_SURFACE = "#fcfcfb"
_INK_PRIMARY = "#0b0b0b"
_INK_SECONDARY = "#52514e"
_INK_MUTED = "#898781"
_GRIDLINE = "#e1e0d9"
_BASELINE = "#c3c2b7"
_SERIES_STILL_LISTED = "#2a78d6"  # categorical slot 1 (blue)
_SERIES_LATER_DELISTED = "#1baf7a"  # categorical slot 2 (aqua)


def plot_universe_counts(counts: list[YearCount], png_path: Path) -> Path:
    """Render the stacked per-year bar chart to `png_path`."""
    if not counts:
        raise ValueError("no universe counts to plot")
    png_path.parent.mkdir(parents=True, exist_ok=True)

    years = [c.year for c in counts]
    still = [c.still_listed for c in counts]
    delisted = [c.later_delisted for c in counts]

    fig, ax = plt.subplots(figsize=(10, 5.5), dpi=150)
    fig.patch.set_facecolor(_SURFACE)
    ax.set_facecolor(_SURFACE)

    bar_kwargs = {"width": 0.82, "edgecolor": _SURFACE, "linewidth": 0.8}
    ax.bar(
        years,
        still,
        color=_SERIES_STILL_LISTED,
        label="Still listed today",
        **bar_kwargs,
    )
    ax.bar(
        years,
        delisted,
        bottom=still,
        color=_SERIES_LATER_DELISTED,
        label="Later delisted",
        **bar_kwargs,
    )

    ax.set_axisbelow(True)
    ax.grid(axis="y", color=_GRIDLINE, linewidth=0.8)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(_BASELINE)
    ax.tick_params(colors=_INK_MUTED, labelcolor=_INK_MUTED, length=0)
    ax.margins(x=0.01)

    ax.set_title(
        "In-universe securities per year",
        loc="left",
        color=_INK_PRIMARY,
        fontsize=13,
        fontweight="bold",
        pad=32,
    )
    ax.set_ylabel("Securities", color=_INK_SECONDARY, fontsize=10)
    # Legend above the plot area: the tall dot-com-era bars sit upper-left,
    # so an in-axes legend would collide with the data.
    legend = ax.legend(
        loc="lower left",
        bbox_to_anchor=(0, 1.0),
        ncols=2,
        frameon=False,
        fontsize=10,
        labelcolor=_INK_SECONDARY,
        borderaxespad=0,
    )
    for handle in legend.legend_handles:
        handle.set_linewidth(0)

    fig.tight_layout()
    fig.savefig(png_path, facecolor=_SURFACE)
    plt.close(fig)
    logger.info("universe counts plot -> %s", png_path)
    return png_path
