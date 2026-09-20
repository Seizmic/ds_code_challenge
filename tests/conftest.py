"""Shared test fixtures.

Hexagons are built from the H3 library itself rather than hand-written
coordinates, so the edge and vertex cases under test are genuine shared
boundaries with exactly the floating-point representation the real data has.
Fabricated polygons would test the tie-break against a situation that cannot
actually occur.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import h3  # noqa: E402
import pandas as pd  # noqa: E402

from src.transform_join import hexes_to_geodataframe  # noqa: E402

# A cell over Cape Town, so fixtures sit inside the bounds the config declares.
ANCHOR_CELL = h3.latlng_to_cell(-33.9249, 18.4241, 8)


def _feature(cell: str) -> dict:
    """Build a GeoJSON feature for a cell, matching the source file's schema."""
    boundary = h3.cell_to_boundary(cell)          # [(lat, lon), ...]
    ring = [[lon, lat] for lat, lon in boundary]  # GeoJSON is [lon, lat]
    ring.append(ring[0])                          # close the ring
    lat, lon = h3.cell_to_latlng(cell)
    return {
        "properties": {
            "index": cell,
            "centroid_lat": lat,
            "centroid_lon": lon,
            "resolution": 8,
        },
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


@pytest.fixture(scope="session")
def anchor_cell() -> str:
    return ANCHOR_CELL


@pytest.fixture(scope="session")
def neighbour_cell(anchor_cell: str) -> str:
    """A cell sharing an edge with the anchor."""
    return sorted(h3.grid_ring(anchor_cell, 1))[0]


@pytest.fixture(scope="session")
def hex_features(anchor_cell: str) -> list[dict]:
    """The anchor cell plus its full ring of six neighbours."""
    cells = [anchor_cell, *sorted(h3.grid_ring(anchor_cell, 1))]
    return [_feature(c) for c in cells]


@pytest.fixture(scope="session")
def hexes(hex_features: list[dict]):
    return hexes_to_geodataframe(hex_features)


def _shared_vertices(cell_a: str, cell_b: str) -> list[tuple[float, float]]:
    """Vertices common to two adjacent cells, compared EXACTLY.

    Rounding here would defeat the purpose. H3 emits bit-identical coordinates
    for a shared vertex from either cell, so exact comparison finds them -- but
    rounding shifts the derived point fractionally off the boundary and it then
    falls strictly inside one polygon, quietly bypassing the very ambiguity
    these fixtures exist to create.
    """
    b = set(h3.cell_to_boundary(cell_b))
    return [p for p in h3.cell_to_boundary(cell_a) if p in b]


@pytest.fixture(scope="session")
def shared_edge_midpoint(anchor_cell: str) -> tuple[float, float]:
    """A point on an edge shared by two cells -- inside both polygons.

    Picks a neighbour whose edge midpoint genuinely intersects two polygons;
    for some edges the midpoint of the two endpoints lands marginally inside
    one cell due to floating-point curvature, which is not the case under test.
    """
    for neighbour in sorted(h3.grid_ring(anchor_cell, 1)):
        shared = _shared_vertices(anchor_cell, neighbour)
        if len(shared) != 2:
            continue
        (lat1, lon1), (lat2, lon2) = shared
        midpoint = ((lat1 + lat2) / 2.0, (lon1 + lon2) / 2.0)
        if _n_intersecting(anchor_cell, midpoint) >= 2:
            return midpoint
    pytest.skip("no shared edge midpoint intersected two polygons")


@pytest.fixture(scope="session")
def shared_vertex(anchor_cell: str) -> tuple[float, float]:
    """A point on a cell corner -- inside THREE polygons.

    The worst case for a naive join: one input row becomes three output rows.
    """
    vertex = h3.cell_to_boundary(anchor_cell)[0]
    assert _n_intersecting(anchor_cell, vertex) == 3, (
        "expected a corner shared by three cells"
    )
    return vertex


def _n_intersecting(anchor: str, point: tuple[float, float]) -> int:
    """How many of the anchor's local cluster contain the point."""
    from shapely.geometry import Point, Polygon as ShapelyPolygon

    lat, lon = point
    shapely_point = Point(lon, lat)
    count = 0
    for cell in [anchor, *h3.grid_ring(anchor, 1)]:
        ring = [[lo, la] for la, lo in h3.cell_to_boundary(cell)]
        ring.append(ring[0])
        if ShapelyPolygon(ring).intersects(shapely_point):
            count += 1
    return count


@pytest.fixture
def points_frame():
    """Build a points DataFrame with numeric lat/lon columns."""
    def _build(pairs: list[tuple[float, float]]) -> pd.DataFrame:
        return pd.DataFrame(
            {"latitude": [p[0] for p in pairs], "longitude": [p[1] for p in pairs]}
        )
    return _build
