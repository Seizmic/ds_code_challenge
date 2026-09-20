"""Section 2: assign each service request to exactly one H3 resolution-8 hexagon.

Two routes are computed over the full dataset and compared:

* **Method G (geometric)** -- spatial join against the supplied polygons, using
  the R0-R4 rule documented in ``docs/decisions.md``.
* **Method H (library)** -- ``h3.latlng_to_cell``, which is O(1) per point and
  has no boundary ambiguity by construction.

Method G is primary because it is what the challenge asks for and it is the only
route that can surface coverage gaps in the supplied polygons. Method H is an
independent oracle; the disagreements between them are a deliverable in their
own right.
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from shapely.geometry import Polygon

from src import config, quality_checks
from src.logging_setup import MANIFEST, timed
from src.quality_checks import CoordClass

logger = logging.getLogger(__name__)

WGS84 = "EPSG:4326"

# Outcome classes for the assignment rule -- see docs/decisions.md section 1.
RULE_R0_NO_GEOLOCATION = "R0_no_geolocation"
RULE_R1_INTERIOR = "R1_interior"
RULE_R2_BOUNDARY_UNIQUE = "R2_boundary_unique"
RULE_R3_TIEBREAK = "R3_tiebreak"
RULE_R4_NO_MATCH = "R4_no_match"
RULE_INVALID_COORDS = "invalid_coordinates"


def hexes_to_geodataframe(features: list[dict[str, Any]]) -> gpd.GeoDataFrame:
    """Build a GeoDataFrame of hexagons from GeoJSON features."""
    records = []
    geometries = []
    for feature in features:
        props = feature["properties"]
        records.append({
            "h3_index": props["index"],
            "centroid_lat": props["centroid_lat"],
            "centroid_lon": props["centroid_lon"],
        })
        geometries.append(Polygon(feature["geometry"]["coordinates"][0]))
    return gpd.GeoDataFrame(records, geometry=geometries, crs=WGS84)


def assign_hexagons_geometric(
    points: pd.DataFrame,
    hexes: gpd.GeoDataFrame,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
) -> pd.DataFrame:
    """Assign each *unique* coordinate pair to exactly one hexagon.

    Expects a frame of distinct coordinate pairs with numeric lat/lon columns.
    Returns one row per input row with ``h3_index``, ``rule``, and tie-break
    diagnostics.

    The three-step structure exists because H3 polygons share edges exactly:
    a point lying on a shared edge is geometrically inside two hexagons, and one
    on a vertex is inside three. Using ``within`` first keeps the unambiguous
    interior case clean and unique, and pushes only genuine boundary cases into
    the more expensive tie-break path.
    """
    geometry = gpd.points_from_xy(points[lon_col], points[lat_col], crs=WGS84)
    points_gdf = gpd.GeoDataFrame(points.copy(), geometry=geometry, crs=WGS84)

    result = pd.DataFrame(
        {"h3_index": pd.Series(pd.NA, index=points.index, dtype="object"),
         "rule": pd.Series(pd.NA, index=points.index, dtype="object"),
         "n_candidates": 0,
         "candidate_indices": pd.Series(pd.NA, index=points.index, dtype="object"),
         "runner_up_index": pd.Series(pd.NA, index=points.index, dtype="object"),
         "margin_m": np.nan},
        index=points.index,
    )

    # --- R1: strict interior ---------------------------------------------------
    interior = gpd.sjoin(
        points_gdf, hexes[["h3_index", "geometry"]], how="inner", predicate="within"
    )
    # A point cannot be strictly inside two hexagons, but guard anyway: if the
    # source polygons ever overlap, we want that visible rather than silently
    # producing duplicate service requests.
    interior_counts = interior.index.value_counts()
    overlapping = interior_counts[interior_counts > 1].index
    if len(overlapping):
        logger.warning(
            "%d point(s) fell strictly inside more than one polygon -- the "
            "supplied hexagons overlap. Routing these through the tie-break.",
            len(overlapping),
        )
        interior = interior[~interior.index.isin(overlapping)]

    result.loc[interior.index, "h3_index"] = interior["h3_index"].to_numpy()
    result.loc[interior.index, "rule"] = RULE_R1_INTERIOR
    result.loc[interior.index, "n_candidates"] = 1

    # --- R2/R3: boundary cases -------------------------------------------------
    unresolved = result.index[result["h3_index"].isna()]
    if len(unresolved):
        boundary = gpd.sjoin(
            points_gdf.loc[unresolved],
            hexes[["h3_index", "centroid_lat", "centroid_lon", "geometry"]],
            how="inner",
            predicate="intersects",
        )
        if len(boundary):
            counts = boundary.index.value_counts()

            # R2: exactly one candidate.
            single = counts[counts == 1].index
            if len(single):
                rows = boundary.loc[boundary.index.isin(single)]
                result.loc[rows.index, "h3_index"] = rows["h3_index"].to_numpy()
                result.loc[rows.index, "rule"] = RULE_R2_BOUNDARY_UNIQUE
                result.loc[rows.index, "n_candidates"] = 1

            # R3: two or more candidates -> deterministic tie-break.
            multiple = counts[counts > 1].index
            if len(multiple):
                resolved = _tiebreak(
                    boundary.loc[boundary.index.isin(multiple)],
                    points_gdf.loc[multiple],
                    lat_col, lon_col,
                )
                for column in resolved.columns:
                    result.loc[resolved.index, column] = resolved[column]

    # --- R4: no match ----------------------------------------------------------
    unmatched = result.index[result["h3_index"].isna()]
    result.loc[unmatched, "rule"] = RULE_R4_NO_MATCH
    result.loc[unmatched, "n_candidates"] = 0

    return result


def _tiebreak(
    candidates: pd.DataFrame,
    points_gdf: gpd.GeoDataFrame,
    lat_col: str,
    lon_col: str,
) -> pd.DataFrame:
    """Resolve multi-candidate points deterministically.

    Rule, in order (docs/decisions.md section 1):
      1. nearest hexagon centroid by great-circle distance;
      2. on a tie, the lexicographically smallest H3 index.

    Criterion 1 approximates what ``h3.latlng_to_cell`` itself does, so the
    tie-break agrees with the library we validate against instead of fighting
    it. Criterion 2 exists solely to make the outcome independent of feature
    ordering, thread scheduling and platform float behaviour -- the same input
    must always produce the same output.
    """
    work = candidates.copy()
    point_lat = points_gdf[lat_col].reindex(work.index).to_numpy(dtype=float)
    point_lon = points_gdf[lon_col].reindex(work.index).to_numpy(dtype=float)

    work["distance_m"] = quality_checks.haversine_metres(
        point_lat, point_lon,
        work["centroid_lat"].to_numpy(dtype=float),
        work["centroid_lon"].to_numpy(dtype=float),
    )

    # Sort so the winner is first within each point: nearest centroid, then
    # lexicographic index as the deterministic secondary key.
    work = work.sort_values(
        ["distance_m", "h3_index"], ascending=[True, True], kind="stable"
    )
    grouped = work.groupby(level=0, sort=False)

    winners = grouped.head(1)
    runners = grouped.nth(1)

    out = pd.DataFrame(index=winners.index)
    out["h3_index"] = winners["h3_index"]
    out["rule"] = RULE_R3_TIEBREAK
    out["n_candidates"] = grouped.size().reindex(winners.index).to_numpy()
    out["candidate_indices"] = (
        work.groupby(level=0, sort=False)["h3_index"]
        .apply(lambda s: "|".join(sorted(s)))
        .reindex(winners.index)
    )
    out["runner_up_index"] = runners["h3_index"].reindex(winners.index)
    out["margin_m"] = (
        runners["distance_m"].reindex(winners.index).to_numpy()
        - winners["distance_m"].to_numpy()
    )
    return out


def assign_hexagons_h3(
    points: pd.DataFrame,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    resolution: int = config.TARGET_RESOLUTION,
) -> pd.Series:
    """Method H: assign via the H3 library directly."""
    lat = points[lat_col].to_numpy(dtype=float)
    lon = points[lon_col].to_numpy(dtype=float)
    return pd.Series(
        [h3.latlng_to_cell(a, o, resolution) for a, o in zip(lat, lon)],
        index=points.index,
        dtype="object",
    )


def categorise_disagreements(
    comparison: pd.DataFrame,
    valid_hexes: set[str],
) -> pd.Series:
    """Bucket each geometric/library disagreement -- see docs/decisions.md section 4.

    Categories, in precedence order:
      C2 coverage gap      -- library returns a cell the polygon file lacks
      C3 out of tiling     -- geometric matched, library's cell not in the file
      C1 boundary tie      -- the tie-break fired and picked a different candidate
      C4 adjacent cell     -- both valid and H3-adjacent (precision drift)
      C5 non-adjacent      -- both valid, not adjacent: NOT a rounding artifact
    """
    result = pd.Series("", index=comparison.index, dtype="object")

    geo = comparison["h3_geometric"]
    lib = comparison["h3_library"]

    lib_in_file = lib.isin(valid_hexes)
    geo_missing = geo.isna() | (geo == config.NO_GEOLOCATION_INDEX)

    result[geo_missing & lib_in_file] = "C2_coverage_gap"
    result[(~geo_missing) & (~lib_in_file)] = "C3_out_of_tiling"

    both = (~geo_missing) & lib_in_file & (result == "")
    if both.any():
        tie = both & (comparison["rule"] == RULE_R3_TIEBREAK)
        result[tie] = "C1_boundary_tie"

        rest = both & (result == "")
        if rest.any():
            adjacent = pd.Series(
                [
                    h3.are_neighbor_cells(a, b)
                    for a, b in zip(geo[rest].to_numpy(), lib[rest].to_numpy())
                ],
                index=comparison.index[rest],
            )
            result[comparison.index[rest][adjacent.to_numpy()]] = "C4_adjacent_cell"
            result[comparison.index[rest][~adjacent.to_numpy()]] = "C5_non_adjacent"

    return result
