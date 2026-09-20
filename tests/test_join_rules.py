"""Tests for the hexagon assignment rule (docs/decisions.md section 1).

The point of these tests is the cases that are rare in the real data and
therefore poorly covered by validating against ``sr_hex.csv.gz``: points on a
shared edge, points on a vertex, and points outside coverage. Those are exactly
the cases where a one-to-many join would silently duplicate service requests.
"""

from __future__ import annotations

import h3
import pandas as pd
import pytest

from src.transform_join import (
    RULE_R1_INTERIOR,
    RULE_R3_TIEBREAK,
    RULE_R4_NO_MATCH,
    assign_hexagons_geometric,
    assign_hexagons_h3,
    hexes_to_geodataframe,
)


class TestExactlyOneResult:
    """The core guarantee: one input row yields exactly one output row."""

    def test_interior_point_resolves_to_one_hexagon(self, hexes, anchor_cell, points_frame):
        lat, lon = h3.cell_to_latlng(anchor_cell)
        result = assign_hexagons_geometric(points_frame([(lat, lon)]), hexes)

        assert len(result) == 1
        assert result.iloc[0]["h3_index"] == anchor_cell
        assert result.iloc[0]["rule"] == RULE_R1_INTERIOR

    def test_point_on_shared_edge_yields_one_row_not_two(
        self, hexes, shared_edge_midpoint, points_frame
    ):
        """A point on a shared edge is inside two polygons geometrically.

        Without the rule this produces two joined rows and duplicates the
        service request. It must produce exactly one.
        """
        result = assign_hexagons_geometric(points_frame([shared_edge_midpoint]), hexes)

        assert len(result) == 1
        assert result.iloc[0]["h3_index"] is not pd.NA
        assert result.iloc[0]["rule"] != RULE_R4_NO_MATCH

    def test_point_on_shared_vertex_yields_one_row_not_three(
        self, hexes, shared_vertex, points_frame
    ):
        """A cell corner is shared by THREE hexagons -- the worst case.

        Naively joined, one service request becomes three, inflating every
        downstream count by two. Exactly one row must come back.
        """
        result = assign_hexagons_geometric(points_frame([shared_vertex]), hexes)

        assert len(result) == 1
        row = result.iloc[0]
        assert row["rule"] == RULE_R3_TIEBREAK
        assert row["n_candidates"] == 3
        assert len(row["candidate_indices"].split("|")) == 3

    def test_every_input_row_appears_exactly_once(self, hexes, anchor_cell, points_frame):
        cells = [anchor_cell, *sorted(h3.grid_ring(anchor_cell, 1))]
        pairs = [h3.cell_to_latlng(c) for c in cells]
        frame = points_frame(pairs)

        result = assign_hexagons_geometric(frame, hexes)

        assert len(result) == len(frame)
        assert result.index.equals(frame.index)
        assert not result.index.duplicated().any()


class TestTiebreakDeterminism:
    """The tie-break must not depend on anything incidental."""

    def test_polygon_ordering_does_not_change_the_result(
        self, hex_features, shared_edge_midpoint, points_frame
    ):
        """Reversing feature order must not change the assignment.

        If the rule fell back on "first match wins", this test fails -- and the
        pipeline would be non-reproducible between runs for no visible reason.
        """
        frame = points_frame([shared_edge_midpoint])

        forward = assign_hexagons_geometric(frame, hexes_to_geodataframe(hex_features))
        reversed_ = assign_hexagons_geometric(
            frame, hexes_to_geodataframe(list(reversed(hex_features)))
        )

        assert forward.iloc[0]["h3_index"] == reversed_.iloc[0]["h3_index"]

    def test_repeated_runs_agree(self, hexes, shared_edge_midpoint, points_frame):
        frame = points_frame([shared_edge_midpoint])
        results = {
            assign_hexagons_geometric(frame, hexes).iloc[0]["h3_index"]
            for _ in range(5)
        }
        assert len(results) == 1

    def test_tiebreak_records_its_diagnostics(
        self, hexes, shared_edge_midpoint, points_frame
    ):
        """When the tie-break fires it must record enough to review the call."""
        result = assign_hexagons_geometric(points_frame([shared_edge_midpoint]), hexes)
        row = result.iloc[0]

        assert row["rule"] == RULE_R3_TIEBREAK
        assert row["n_candidates"] == 2
        assert row["candidate_indices"] and "|" in row["candidate_indices"]
        assert row["runner_up_index"] is not pd.NA
        # The margin is the diagnostic that says whether the tie-break mattered.
        assert row["margin_m"] >= 0


class TestNoMatch:
    def test_point_outside_all_polygons_is_flagged_not_silently_dropped(
        self, hexes, points_frame
    ):
        """An unmatched point must be reported as R4, never dropped.

        R4 is distinct from R0 (no geolocation). Conflating them would hide a
        genuine coverage failure inside a count of legitimately empty records.
        """
        result = assign_hexagons_geometric(points_frame([(-33.0, 19.5)]), hexes)

        assert len(result) == 1
        assert result.iloc[0]["rule"] == RULE_R4_NO_MATCH
        assert pd.isna(result.iloc[0]["h3_index"])
        assert result.iloc[0]["n_candidates"] == 0


class TestAgreementWithH3Library:
    def test_interior_points_agree_with_the_library(
        self, hexes, anchor_cell, points_frame
    ):
        """For unambiguous interior points the two methods must agree.

        Disagreement here would mean the polygons do not represent the cells
        they claim to, which invalidates the whole geometric route.
        """
        cells = [anchor_cell, *sorted(h3.grid_ring(anchor_cell, 1))]
        frame = points_frame([h3.cell_to_latlng(c) for c in cells])

        geometric = assign_hexagons_geometric(frame, hexes)["h3_index"]
        library = assign_hexagons_h3(frame)

        assert list(geometric) == list(library)
