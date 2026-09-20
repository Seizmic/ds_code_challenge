"""Coordinate quality classification and inversion detection.

Runs as a gate *before* the spatial join. Axis inversion is the failure mode
that matters most here: swapped latitude and longitude produce a join that
returns almost no matches, which looks like a coverage problem rather than a
coordinate problem and wastes a lot of time being diagnosed as one.

Detection is reliable because Cape Town's latitude and longitude ranges are
disjoint and opposite in sign -- latitude ~-34 to -33, longitude ~+18 to +19 --
so a swapped pair cannot masquerade as a valid one.
"""

from __future__ import annotations

import logging
from enum import StrEnum

import numpy as np
import pandas as pd

from src import config

logger = logging.getLogger(__name__)


class CoordClass(StrEnum):
    """Mutually exclusive classification of a record's coordinates."""

    MISSING = "missing"            # no coordinates -> index 0 per the spec (R0)
    VALID = "valid"                # parseable and inside the CoCT bounding box
    INVERTED = "inverted"          # latitude and longitude appear swapped
    NULL_ISLAND = "null_island"    # exactly (0, 0) -- a classic geocoding failure
    OUT_OF_BOUNDS = "out_of_bounds"  # parseable, but outside Cape Town
    UNPARSEABLE = "unparseable"    # present but not a number


def classify_coordinates(
    df: pd.DataFrame,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
) -> pd.Series:
    """Classify every row's coordinates. Returns a Series of :class:`CoordClass`.

    Operates on the raw string columns so that "empty" is distinguished from
    "zero" -- reading these as floats first collapses both to NaN and loses the
    distinction the spec depends on.
    """
    bounds = config.CCT_BOUNDS

    raw_lat = df[lat_col].astype("string").fillna("").str.strip()
    raw_lon = df[lon_col].astype("string").fillna("").str.strip()

    # Treat common textual null spellings as missing, not as unparseable.
    null_tokens = {"", "nan", "none", "null", "na", "n/a"}
    missing = raw_lat.str.lower().isin(null_tokens) | raw_lon.str.lower().isin(null_tokens)

    lat = pd.to_numeric(raw_lat, errors="coerce")
    lon = pd.to_numeric(raw_lon, errors="coerce")

    result = pd.Series(CoordClass.OUT_OF_BOUNDS, index=df.index, dtype="object")

    unparseable = (~missing) & (lat.isna() | lon.isna())
    null_island = (~missing) & (lat == 0) & (lon == 0)
    in_bounds = (
        lat.between(bounds["lat_min"], bounds["lat_max"])
        & lon.between(bounds["lon_min"], bounds["lon_max"])
    )
    # Swapped: the value in `latitude` sits in the longitude range and vice versa.
    inverted = (
        lat.between(bounds["lon_min"], bounds["lon_max"])
        & lon.between(bounds["lat_min"], bounds["lat_max"])
    )

    result[in_bounds] = CoordClass.VALID
    result[inverted] = CoordClass.INVERTED
    result[null_island] = CoordClass.NULL_ISLAND
    result[unparseable] = CoordClass.UNPARSEABLE
    result[missing] = CoordClass.MISSING

    return result


def summarise(classes: pd.Series) -> dict[str, int]:
    """Count rows per class, including classes with zero occurrences.

    Zero counts are kept deliberately: "we checked for inverted coordinates and
    found none" is a result, and omitting the row makes it look unchecked.
    """
    counts = classes.value_counts().to_dict()
    return {str(c): int(counts.get(c, 0)) for c in CoordClass}


def log_summary(summary: dict[str, int], total: int) -> None:
    logger.info("Coordinate quality over %d records:", total)
    for name, count in summary.items():
        if count == 0:
            continue
        logger.info("  %-14s %9d  (%5.2f%%)", name, count, 100.0 * count / total)

    for name in (CoordClass.INVERTED, CoordClass.NULL_ISLAND, CoordClass.UNPARSEABLE):
        if summary.get(str(name), 0):
            logger.warning(
                "  %d record(s) classified as %s -- these are excluded from the "
                "join and counted as failures, not silently corrected",
                summary[str(name)], name,
            )

    if summary.get(str(CoordClass.INVERTED), 0) == 0:
        logger.info("  no axis inversion detected")


def haversine_metres(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray
) -> np.ndarray:
    """Great-circle distance in metres between paired coordinate arrays.

    Used for the nearest-centroid tie-break, where the quantity of interest is
    the *margin* between the two closest candidates rather than an absolute
    distance, so a spherical approximation is ample.
    """
    radius = 6_371_000.0
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dp = p2 - p1
    dl = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dp / 2.0) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dl / 2.0) ** 2
    return 2.0 * radius * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
