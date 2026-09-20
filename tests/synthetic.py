"""Synthetic fixtures that deliberately trigger every dormant code path.

The supplied data exercises roughly a quarter of the checks in this pipeline.
Everything else - axis inversion, null island, boundary ties, schema violations,
threshold breaches, the side-car artifacts, the error logging - never fires,
which means it has never been shown to work.

A check that has never fired is indistinguishable from a check that is broken.
These builders construct the inputs the real data does not contain, so that the
remaining paths can be executed and asserted on rather than assumed.

Each builder is named for the single path it targets.
"""

from __future__ import annotations

import copy
from typing import Any

import h3
import pandas as pd

# A cell over Cape Town, so fixtures fall inside the configured bounds.
ANCHOR_CELL = h3.latlng_to_cell(-33.9249, 18.4241, 8)


# =============================================================================
# Hexagon features
# =============================================================================

def hex_feature(cell: str = ANCHOR_CELL) -> dict[str, Any]:
    """A well-formed feature matching the source file's schema exactly."""
    boundary = h3.cell_to_boundary(cell)
    ring = [[lon, lat] for lat, lon in boundary]
    ring.append(ring[0])
    lat, lon = h3.cell_to_latlng(cell)
    return {
        "type": "Feature",
        "properties": {
            "index": cell,
            "centroid_lat": lat,
            "centroid_lon": lon,
            "resolution": 8,
        },
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def hex_collection(radius: int = 2) -> list[dict[str, Any]]:
    """A clean, COMPLETE disk of cells centred on the anchor.

    Returns the whole disk rather than a slice of it. Truncating to an
    arbitrary count can omit one of the three cells meeting at a vertex, and a
    vertex fixture then silently produces two candidates instead of three -
    the tie-break test passes while testing the weaker case.
    """
    return [hex_feature(c) for c in sorted(h3.grid_disk(ANCHOR_CELL, radius))]


# --- Single-rule corruptions -------------------------------------------------

def hex_missing_index() -> dict[str, Any]:
    f = hex_feature()
    del f["properties"]["index"]
    return f


def hex_bad_index_pattern() -> dict[str, Any]:
    f = hex_feature()
    f["properties"]["index"] = "not-an-h3-index"
    return f


def hex_wrong_geometry_type() -> dict[str, Any]:
    f = hex_feature()
    f["geometry"]["type"] = "MultiPolygon"
    return f


def hex_wrong_vertex_count() -> dict[str, Any]:
    """A ring with 5 positions instead of 7 - a truncated or clipped polygon."""
    f = hex_feature()
    f["geometry"]["coordinates"][0] = f["geometry"]["coordinates"][0][:5]
    return f


def hex_unclosed_ring() -> dict[str, Any]:
    """First position != last. Valid-looking, but not a closed polygon."""
    f = hex_feature()
    ring = f["geometry"]["coordinates"][0]
    ring[-1] = [ring[-1][0] + 0.001, ring[-1][1]]
    return f


def hex_inverted_axes() -> dict[str, Any]:
    """Coordinates written [lat, lon] instead of [lon, lat].

    The single most consequential GeoJSON defect: it produces a file that
    parses cleanly, looks plausible, and joins to nothing.
    """
    f = hex_feature()
    f["geometry"]["coordinates"][0] = [
        [lat, lon] for lon, lat in f["geometry"]["coordinates"][0]
    ]
    f["properties"]["centroid_lat"], f["properties"]["centroid_lon"] = (
        f["properties"]["centroid_lon"], f["properties"]["centroid_lat"]
    )
    return f


def hex_inverted_geometry_only() -> dict[str, Any]:
    """Ring axes swapped but the centroid left correct - an INCONSISTENT inversion.

    Distinct from :func:`hex_inverted_axes`, and caught by a different rule.
    A consistent inversion (both ring and centroid swapped) stays internally
    coherent, so the centroid still sits inside its own polygon in the swapped
    space and only the bounds rules can see it. An inconsistent one breaks that
    relationship, which is what `centroid_within_polygon` exists to detect.
    """
    f = hex_feature()
    f["geometry"]["coordinates"][0] = [
        [lat, lon] for lon, lat in f["geometry"]["coordinates"][0]
    ]
    return f


def hex_out_of_bounds() -> dict[str, Any]:
    """A geometrically valid cell in the wrong city (Johannesburg)."""
    return hex_feature(h3.latlng_to_cell(-26.2041, 28.0473, 8))


def hex_missing_centroid() -> dict[str, Any]:
    f = hex_feature()
    del f["properties"]["centroid_lat"]
    return f


def hex_centroid_outside_polygon() -> dict[str, Any]:
    """Centroid present and in range, but not inside its own polygon.

    Catches a mismatched join between attributes and geometry - the kind of
    fault where two datasets were merged on the wrong key.
    """
    f = hex_feature()
    other = sorted(h3.grid_ring(ANCHOR_CELL, 2))[0]
    lat, lon = h3.cell_to_latlng(other)
    f["properties"]["centroid_lat"] = lat
    f["properties"]["centroid_lon"] = lon
    return f


def hex_wrong_resolution() -> dict[str, Any]:
    f = hex_feature()
    f["properties"]["resolution"] = 9
    return f


def hex_duplicate_index(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Re-issue the first feature's index on the second."""
    out = copy.deepcopy(features)
    out[1]["properties"]["index"] = out[0]["properties"]["index"]
    return out


# =============================================================================
# Service request frames
# =============================================================================

SR_COLUMNS = [
    "notification_number", "reference_number", "creation_timestamp",
    "completion_timestamp", "directorate", "department", "branch", "section",
    "code_group", "code", "cause_code_group", "cause_code", "official_suburb",
    "latitude", "longitude",
]


def sr_frame(n: int = 2000, **overrides: Any) -> pd.DataFrame:
    """A clean service request frame; pass column overrides to break it."""
    lat, lon = h3.cell_to_latlng(ANCHOR_CELL)
    base: dict[str, Any] = {
        "notification_number": [f"{i:012d}" for i in range(n)],
        "reference_number": [f"9{i:09d}" for i in range(n)],
        "creation_timestamp": ["2020-07-01 08:00:00+02:00"] * n,
        "completion_timestamp": ["2020-07-02 08:00:00+02:00"] * n,
        "directorate": ["URBAN MOBILITY"] * n,
        "department": ["Roads Infrastructure Management"] * n,
        "branch": ["RIM Area Central"] * n,
        "section": ["District: Blaauwberg"] * n,
        "code_group": ["TD Customer complaint groups"] * n,
        "code": ["Pothole"] * n,
        "cause_code_group": [""] * n,
        "cause_code": [""] * n,
        "official_suburb": ["MONTAGUE GARDENS"] * n,
        "latitude": [f"{lat}"] * n,
        "longitude": [f"{lon}"] * n,
    }
    base.update(overrides)
    return pd.DataFrame(base, dtype="string")


def sr_with_coordinate_classes(per_class: int = 20) -> tuple[pd.DataFrame, dict[str, int]]:
    """A frame containing EVERY coordinate class, with expected counts.

    Returns the frame and the count expected per class, so a test can assert
    the classifier's totals rather than merely that it did not crash.
    """
    lat, lon = h3.cell_to_latlng(ANCHOR_CELL)
    rows: list[tuple[str, str]] = []
    expected: dict[str, int] = {}

    def add(label: str, pair: tuple[str, str], count: int) -> None:
        rows.extend([pair] * count)
        expected[label] = count

    add("valid", (f"{lat}", f"{lon}"), per_class)
    add("missing", ("", ""), per_class)
    add("partial", (f"{lat}", ""), per_class)                 # lat only
    add("inverted", (f"{lon}", f"{lat}"), per_class)          # axes swapped
    add("null_island", ("0", "0"), per_class)
    add("out_of_bounds", ("-26.2041", "28.0473"), per_class)  # Johannesburg
    add("unparseable", ("not-a-number", "also-not"), per_class)

    frame = sr_frame(
        n=len(rows),
        latitude=[r[0] for r in rows],
        longitude=[r[1] for r in rows],
    )
    return frame, expected


# =============================================================================
# Points that exercise the join rules
# =============================================================================

def point_interior() -> tuple[float, float]:
    """Strictly inside one hexagon -> R1."""
    return h3.cell_to_latlng(ANCHOR_CELL)


def point_on_shared_edge() -> tuple[float, float]:
    """On an edge shared by two cells -> R3 with 2 candidates.

    Uses EXACT H3 vertices. Rounding shifts the derived point fractionally
    inside one polygon and silently bypasses the ambiguity being constructed.
    """
    for neighbour in sorted(h3.grid_ring(ANCHOR_CELL, 1)):
        shared = [
            p for p in h3.cell_to_boundary(ANCHOR_CELL)
            if p in set(h3.cell_to_boundary(neighbour))
        ]
        if len(shared) == 2:
            (lat1, lon1), (lat2, lon2) = shared
            return ((lat1 + lat2) / 2.0, (lon1 + lon2) / 2.0)
    raise RuntimeError("no shared edge found")


def point_on_shared_vertex() -> tuple[float, float]:
    """On a cell corner -> R3 with 3 candidates."""
    return h3.cell_to_boundary(ANCHOR_CELL)[0]


def point_on_isolated_cell_boundary() -> tuple[float, float]:
    """An exact vertex of a cell, to be used with a set containing ONLY that cell.

    Gives R2: `within` is False because the point is on the boundary rather
    than the interior, so it falls through to the `intersects` pass, where
    exactly one polygon is available and it resolves uniquely.

    Constructed this way rather than from an outer rim edge. A straight-line
    midpoint between two vertices does not lie exactly on the polygon edge
    once curvature is accounted for, and on an outer rim it lands fractionally
    OUTSIDE with no neighbouring cell to catch it - producing R4, not R2.
    An exact vertex is on the boundary by construction.
    """
    return h3.cell_to_boundary(ANCHOR_CELL)[0]


def isolated_cell_collection() -> list[dict[str, Any]]:
    """A set containing a single cell, for the R2 path."""
    return [hex_feature(ANCHOR_CELL)]


def point_outside_coverage() -> tuple[float, float]:
    """Inside the configured bounds but matching no supplied hexagon -> R4."""
    return (-33.55, 18.95)
