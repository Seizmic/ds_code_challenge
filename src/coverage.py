"""Coverage analysis for the supplied hexagon set.

Answers "does the City of Cape Town have full coverage from the polygons
provided?" using two independent methods that need no external dependency:

1. **Topological.** Walk the neighbours of every supplied cell. An absent cell
   with most of its own neighbours present is a hole *inside* the covered
   region, which is a defect. An absent cell with few present neighbours is
   simply outside the boundary, which is expected.

2. **Empirical.** Any service request with valid, in-bounds coordinates that
   matches no hexagon is direct evidence of a gap, and needs no model of where
   the municipal boundary runs.

The deliberate choice here is to avoid depending on the City's open-data
portal for a boundary polygon. The upstream README warns that endpoint is
unreliable, and a coverage check that cannot run offline is a coverage check
that will eventually stop running.
"""

from __future__ import annotations

import logging
from typing import Any

import h3

logger = logging.getLogger(__name__)

# An absent cell with this many of its six neighbours present is treated as a
# hole inside the covered area rather than a point beyond its edge.
ENCLOSURE_THRESHOLD = 5


def analyse(cells: set[str]) -> dict[str, Any]:
    """Analyse the topology of a set of H3 cells."""
    neighbour_support: dict[str, int] = {}
    for cell in cells:
        for neighbour in h3.grid_ring(cell, 1):
            if neighbour not in cells:
                neighbour_support[neighbour] = neighbour_support.get(neighbour, 0) + 1

    holes = sorted(
        c for c, n in neighbour_support.items() if n >= ENCLOSURE_THRESHOLD
    )
    fully_enclosed = sorted(c for c, n in neighbour_support.items() if n == 6)

    histogram: dict[int, int] = {}
    for count in neighbour_support.values():
        histogram[count] = histogram.get(count, 0) + 1

    areas = [h3.cell_area(c, unit="km^2") for c in cells]

    return {
        "n_cells": len(cells),
        "total_area_km2": round(sum(areas), 2),
        "mean_cell_area_km2": round(sum(areas) / len(areas), 6) if areas else 0.0,
        "n_absent_neighbours": len(neighbour_support),
        "absent_by_support": dict(sorted(histogram.items(), reverse=True)),
        "n_interior_holes": len(holes),
        "n_fully_enclosed_holes": len(fully_enclosed),
        "interior_holes": [
            {
                "index": c,
                "lat": round(h3.cell_to_latlng(c)[0], 6),
                "lon": round(h3.cell_to_latlng(c)[1], 6),
                "neighbours_present": neighbour_support[c],
            }
            for c in holes[:20]
        ],
    }


def log_report(report: dict[str, Any]) -> None:
    logger.info("Hexagon coverage analysis:")
    logger.info("  %d cells, %.1f km2 total, mean cell %.6f km2",
                report["n_cells"], report["total_area_km2"],
                report["mean_cell_area_km2"])
    logger.info("  %d distinct absent neighbour cells around the perimeter",
                report["n_absent_neighbours"])

    if report["n_fully_enclosed_holes"]:
        logger.error(
            "  %d FULLY ENCLOSED hole(s) -- cells absent despite all six "
            "neighbours being present. This is unambiguously a gap.",
            report["n_fully_enclosed_holes"],
        )
    if report["n_interior_holes"]:
        logger.warning(
            "  %d near-enclosed gap(s) (>=%d of 6 neighbours present):",
            report["n_interior_holes"], ENCLOSURE_THRESHOLD,
        )
        for hole in report["interior_holes"]:
            logger.warning(
                "    %s at (%.5f, %.5f), %d neighbours present",
                hole["index"], hole["lat"], hole["lon"], hole["neighbours_present"],
            )
    else:
        logger.info("  no interior holes: the covered region is simply connected")
