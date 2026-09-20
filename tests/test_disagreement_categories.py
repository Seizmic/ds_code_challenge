"""Tests for the method-disagreement categoriser (docs/decisions.md section 4).

Every disagreement must land in exactly one named category. An uncategorised
row is worse than a wrong one: it is silently dropped from the summary counts,
so a real finding can disappear without anything looking broken. That is
exactly what happened on the first full run -- two genuine outside-coverage
records were reported under an empty category name.
"""

from __future__ import annotations

import h3
import pandas as pd
import pytest

from src.transform_join import RULE_R1_INTERIOR, RULE_R4_NO_MATCH, categorise_disagreements

ANCHOR = h3.latlng_to_cell(-33.9249, 18.4241, 8)
NEIGHBOUR = sorted(h3.grid_ring(ANCHOR, 1))[0]
FAR_AWAY = h3.latlng_to_cell(-26.2041, 28.0473, 8)  # Johannesburg


def comparison_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


class TestTotality:
    """The property that matters most: no row escapes categorisation."""

    def test_every_row_gets_a_non_empty_category(self):
        frame = comparison_frame([
            # geometric matched, library disagrees with an adjacent cell
            {"h3_geometric": ANCHOR, "h3_library": NEIGHBOUR, "rule": RULE_R1_INTERIOR},
            # geometric matched nothing, library's cell IS in the file
            {"h3_geometric": None, "h3_library": NEIGHBOUR, "rule": RULE_R4_NO_MATCH},
            # geometric matched nothing, library's cell is NOT in the file
            {"h3_geometric": None, "h3_library": FAR_AWAY, "rule": RULE_R4_NO_MATCH},
            # geometric matched, library's cell is NOT in the file
            {"h3_geometric": ANCHOR, "h3_library": FAR_AWAY, "rule": RULE_R1_INTERIOR},
        ])

        result = categorise_disagreements(frame, valid_hexes={ANCHOR, NEIGHBOUR})

        assert len(result) == len(frame)
        assert (result != "").all(), f"uncategorised rows: {list(result[result == ''].index)}"

    def test_categories_are_the_documented_ones(self):
        frame = comparison_frame([
            {"h3_geometric": ANCHOR, "h3_library": NEIGHBOUR, "rule": RULE_R1_INTERIOR},
            {"h3_geometric": None, "h3_library": NEIGHBOUR, "rule": RULE_R4_NO_MATCH},
            {"h3_geometric": None, "h3_library": FAR_AWAY, "rule": RULE_R4_NO_MATCH},
        ])

        result = categorise_disagreements(frame, valid_hexes={ANCHOR, NEIGHBOUR})

        known = {
            "C1_boundary_tie", "C2_coverage_gap", "C2b_outside_coverage",
            "C3_out_of_tiling", "C4_adjacent_cell", "C5_non_adjacent",
        }
        assert set(result) <= known


class TestSpecificCategories:
    def test_coverage_gap_is_distinct_from_outside_coverage(self):
        """A hole inside the covered area is not the same as being beyond it.

        C2 means the polygon file is missing a cell it should have -- a defect.
        C2b means the request happened outside the area the file covers, which
        may be entirely legitimate. Conflating them turns a scope question into
        a phantom data-quality bug.
        """
        frame = comparison_frame([
            {"h3_geometric": None, "h3_library": NEIGHBOUR, "rule": RULE_R4_NO_MATCH},
            {"h3_geometric": None, "h3_library": FAR_AWAY, "rule": RULE_R4_NO_MATCH},
        ])

        result = categorise_disagreements(frame, valid_hexes={ANCHOR, NEIGHBOUR})

        assert result.iloc[0] == "C2_coverage_gap"
        assert result.iloc[1] == "C2b_outside_coverage"

    def test_adjacent_cells_are_separated_from_non_adjacent(self):
        """C5 is the alarming one and must not absorb ordinary drift."""
        far_neighbour = sorted(h3.grid_ring(ANCHOR, 3))[0]
        frame = comparison_frame([
            {"h3_geometric": ANCHOR, "h3_library": NEIGHBOUR, "rule": RULE_R1_INTERIOR},
            {"h3_geometric": ANCHOR, "h3_library": far_neighbour, "rule": RULE_R1_INTERIOR},
        ])

        result = categorise_disagreements(
            frame, valid_hexes={ANCHOR, NEIGHBOUR, far_neighbour}
        )

        assert result.iloc[0] == "C4_adjacent_cell"
        assert result.iloc[1] == "C5_non_adjacent"

    def test_empty_input_is_handled(self):
        frame = pd.DataFrame(columns=["h3_geometric", "h3_library", "rule"])
        assert len(categorise_disagreements(frame, valid_hexes={ANCHOR})) == 0
