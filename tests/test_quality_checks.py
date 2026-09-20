"""Tests for coordinate classification and the inversion gate."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.quality_checks import CoordClass, classify_coordinates, haversine_metres, summarise

CAPE_TOWN = (-33.9249, 18.4241)


def frame(pairs: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(
        {"latitude": [str(p[0]) for p in pairs],
         "longitude": [str(p[1]) for p in pairs]}
    )


class TestClassification:
    def test_valid_cape_town_coordinates(self):
        result = classify_coordinates(frame([CAPE_TOWN]))
        assert result.iloc[0] == CoordClass.VALID

    def test_inverted_coordinates_are_detected(self):
        """Swapped axes must be caught, not treated as out-of-bounds.

        This is the whole point of the gate: inverted coordinates produce a join
        that matches almost nothing, which reads as a coverage problem and sends
        you looking in the wrong place.
        """
        result = classify_coordinates(frame([(18.4241, -33.9249)]))
        assert result.iloc[0] == CoordClass.INVERTED

    def test_null_island_is_distinct_from_missing(self):
        """(0, 0) is a geocoding failure, not an absent coordinate.

        The spec assigns index 0 to *empty* coordinates. A record that geocoded
        to null island has coordinates -- wrong ones -- and must not be quietly
        folded into the legitimate-missing bucket.
        """
        result = classify_coordinates(frame([(0, 0)]))
        assert result.iloc[0] == CoordClass.NULL_ISLAND

    @pytest.mark.parametrize("token", ["", "nan", "NULL", "  ", "N/A", "none"])
    def test_textual_null_spellings_count_as_missing(self, token):
        df = pd.DataFrame({"latitude": [token], "longitude": [token]})
        assert classify_coordinates(df).iloc[0] == CoordClass.MISSING

    def test_unparseable_is_not_missing(self):
        df = pd.DataFrame({"latitude": ["not-a-number"], "longitude": ["18.4"]})
        assert classify_coordinates(df).iloc[0] == CoordClass.UNPARSEABLE

    def test_out_of_bounds_coordinates(self):
        """Johannesburg: valid coordinates, wrong city."""
        result = classify_coordinates(frame([(-26.2041, 28.0473)]))
        assert result.iloc[0] == CoordClass.OUT_OF_BOUNDS

    def test_classes_are_mutually_exclusive_and_total(self):
        pairs = [CAPE_TOWN, (18.4241, -33.9249), (0, 0), (-26.2041, 28.0473)]
        df = frame(pairs)
        df = pd.concat([df, pd.DataFrame({"latitude": [""], "longitude": [""]})],
                       ignore_index=True)

        result = classify_coordinates(df)

        assert len(result) == len(df)
        assert result.notna().all()
        assert sum(summarise(result).values()) == len(df)


class TestSummary:
    def test_zero_counts_are_retained(self):
        """A class with no occurrences must still be reported.

        "Checked for inversion, found none" is a result. Dropping the row makes
        it indistinguishable from never having checked.
        """
        summary = summarise(classify_coordinates(frame([CAPE_TOWN])))
        assert str(CoordClass.INVERTED) in summary
        assert summary[str(CoordClass.INVERTED)] == 0


class TestHaversine:
    def test_zero_distance(self):
        d = haversine_metres(np.array([-33.9]), np.array([18.4]),
                             np.array([-33.9]), np.array([18.4]))
        assert d[0] == pytest.approx(0.0, abs=1e-6)

    def test_known_distance_is_plausible(self):
        """Cape Town to Johannesburg is roughly 1,260 km."""
        d = haversine_metres(np.array([-33.9249]), np.array([18.4241]),
                             np.array([-26.2041]), np.array([28.0473]))
        assert 1_250_000 < d[0] < 1_290_000

    def test_symmetry(self):
        a = haversine_metres(np.array([-33.9]), np.array([18.4]),
                             np.array([-34.0]), np.array([18.5]))
        b = haversine_metres(np.array([-34.0]), np.array([18.5]),
                             np.array([-33.9]), np.array([18.4]))
        assert a[0] == pytest.approx(b[0])
