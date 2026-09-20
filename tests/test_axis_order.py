"""Latitude/longitude ordering, end to end.

Latitude and longitude arrive as two independent **text columns**, not as a
geometry type. Nothing in the file format binds them together or records which
is which - the association exists only in the column names and in every line of
code that consumes them. A swap is therefore always possible, from an upstream
export change, a renamed column, or an argument transposed in our own code.

Two libraries in this pipeline take the pair in *opposite* orders:

* ``shapely`` / ``geopandas.points_from_xy(x, y)`` -> **(longitude, latitude)**
* ``h3.latlng_to_cell(lat, lng, res)``             -> **(latitude, longitude)**

Transposing either is a one-character edit that raises no error and produces a
plausible-looking result. These tests pin both orders, and pin the detection of
swapped input data.

Cape Town makes this checkable: longitude runs +18 to +19 and latitude -34 to
-33, so the ranges are disjoint and opposite in sign. A swapped pair cannot
masquerade as a valid one.
"""

from __future__ import annotations

import h3
import pandas as pd
import pytest
from shapely.geometry import Point

from src import config, quality_checks
from src.quality_checks import CoordClass
from src.transform_join import (
    assign_hexagons_geometric,
    assign_hexagons_h3,
    hexes_to_geodataframe,
)
from src.validation import rule_axis_order, score_conformance
from tests import synthetic

CAPE_TOWN_LAT = -33.9249
CAPE_TOWN_LON = 18.4241


class TestLibraryArgumentOrder:
    """The two libraries disagree on order; both call sites must be right."""

    def test_h3_takes_latitude_first(self):
        """`h3.latlng_to_cell(lat, lng)`. Transposing yields a cell elsewhere."""
        correct = h3.latlng_to_cell(CAPE_TOWN_LAT, CAPE_TOWN_LON, 8)
        transposed = h3.latlng_to_cell(CAPE_TOWN_LON, CAPE_TOWN_LAT, 8)
        assert correct != transposed

        back_lat, back_lon = h3.cell_to_latlng(correct)
        assert back_lat == pytest.approx(CAPE_TOWN_LAT, abs=0.01)
        assert back_lon == pytest.approx(CAPE_TOWN_LON, abs=0.01)

    def test_shapely_takes_longitude_first(self):
        """`Point(x, y)` is (longitude, latitude) - the opposite of h3."""
        point = Point(CAPE_TOWN_LON, CAPE_TOWN_LAT)
        assert point.x == CAPE_TOWN_LON
        assert point.y == CAPE_TOWN_LAT

    def test_our_h3_call_site_uses_the_right_order(self):
        """Guards `assign_hexagons_h3` against a transposed argument."""
        frame = pd.DataFrame(
            {"latitude": [CAPE_TOWN_LAT], "longitude": [CAPE_TOWN_LON]}
        )
        assert (
            assign_hexagons_h3(frame).iloc[0]
            == h3.latlng_to_cell(CAPE_TOWN_LAT, CAPE_TOWN_LON, 8)
        )

    def test_our_geometric_call_site_uses_the_right_order(self):
        """Guards `points_from_xy` in `assign_hexagons_geometric`.

        If longitude and latitude were transposed there, the constructed point
        would land near (-33.9 E, 18.4 N) - in the Atlantic off West Africa -
        and match no Cape Town hexagon at all.
        """
        hexes = hexes_to_geodataframe(synthetic.hex_collection(radius=2))
        lat, lon = h3.cell_to_latlng(synthetic.ANCHOR_CELL)

        result = assign_hexagons_geometric(
            pd.DataFrame({"latitude": [lat], "longitude": [lon]}), hexes
        )
        assert result.iloc[0]["h3_index"] == synthetic.ANCHOR_CELL

    def test_both_methods_agree_which_means_neither_is_transposed(self):
        """The strongest available guard on our own call sites.

        The two libraries take opposite orders, so a transposition in either
        one breaks agreement. Agreement across many points means both are right.
        """
        hexes = hexes_to_geodataframe(synthetic.hex_collection(radius=2))
        cells = sorted(h3.grid_disk(synthetic.ANCHOR_CELL, 1))
        frame = pd.DataFrame(
            [{"latitude": la, "longitude": lo}
             for la, lo in (h3.cell_to_latlng(c) for c in cells)]
        )

        geometric = assign_hexagons_geometric(frame, hexes)["h3_index"]
        library = assign_hexagons_h3(frame)
        assert list(geometric) == list(library)


class TestSwappedInputIsDetected:
    """The columns are plain text, so the data itself may arrive swapped."""

    def test_swapped_service_request_row_is_classified_inverted(self):
        swapped = pd.DataFrame(
            {"latitude": [str(CAPE_TOWN_LON)], "longitude": [str(CAPE_TOWN_LAT)]}
        )
        assert quality_checks.classify_coordinates(swapped).iloc[0] == CoordClass.INVERTED

    def test_wholesale_column_swap_is_caught_for_every_row(self):
        """A renamed or transposed column upstream affects all rows at once.

        The gate must fire on the whole file, not merely flag a few outliers.
        """
        lat, lon = h3.cell_to_latlng(synthetic.ANCHOR_CELL)
        n = 500
        swapped = pd.DataFrame(
            {"latitude": [str(lon)] * n, "longitude": [str(lat)] * n}
        )
        classes = quality_checks.classify_coordinates(swapped)
        assert (classes == CoordClass.INVERTED).all()

    def test_swap_is_not_mistaken_for_out_of_bounds(self):
        """Inversion must be its own class, not lumped in with bad coordinates.

        Both are "not valid", but only one tells you the cause. Misclassifying
        a swap as out-of-bounds sends the reader looking for a geocoding fault
        rather than a transposed column.
        """
        swapped = pd.DataFrame(
            {"latitude": [str(CAPE_TOWN_LON)], "longitude": [str(CAPE_TOWN_LAT)]}
        )
        johannesburg = pd.DataFrame({"latitude": ["-26.2041"], "longitude": ["28.0473"]})

        assert quality_checks.classify_coordinates(swapped).iloc[0] == CoordClass.INVERTED
        assert (
            quality_checks.classify_coordinates(johannesburg).iloc[0]
            == CoordClass.OUT_OF_BOUNDS
        )

    def test_ranges_are_disjoint_so_a_swap_is_always_detectable(self):
        """The property the whole detection strategy rests on.

        If the latitude and longitude ranges ever overlapped, a swapped pair
        could look valid and no check could tell. Asserted explicitly so that
        widening the bounds in config cannot quietly break detection.
        """
        b = config.CCT_BOUNDS
        assert b["lat_max"] < b["lon_min"], (
            "CCT_BOUNDS latitude and longitude ranges now overlap; coordinate "
            "inversion is no longer reliably detectable"
        )


class TestGeoJsonAxisOrder:
    """The polygon file can arrive inverted too."""

    def test_inverted_geojson_fails_the_axis_rule(self):
        schema = config.load_hex_schema()
        assert rule_axis_order(synthetic.hex_feature(), schema) is True
        assert rule_axis_order(synthetic.hex_inverted_geometry_only(), schema) is False

    def test_inverted_geojson_drops_the_conformance_score(self):
        schema = config.load_hex_schema()
        clean = synthetic.hex_collection(radius=2)
        inverted = [synthetic.hex_inverted_geometry_only() for _ in clean]

        assert score_conformance(clean, schema)["score"] == pytest.approx(1.0)
        assert score_conformance(inverted, schema)["verdict"] == "fail"
