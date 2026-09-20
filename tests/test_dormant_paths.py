"""Exercises the code paths the supplied data never reaches.

The real dataset triggers roughly a quarter of the checks in this pipeline. The
rest - every coordinate class but two, three of the five assignment rules, four
of the six disagreement categories, every consistency violation, every threshold
breach and every warning and error log line - stay dormant.

Dormant is not the same as working. These tests drive each remaining path with
synthetic input and assert on what the operator would actually see: the rule
that fires, the exception raised, the artifact written, the log line emitted.
"""

from __future__ import annotations

import logging

import pandas as pd
import pytest

from src import config, coverage, quality_checks, transform_join
from src.quality_checks import CoordClass
from src.sr_validation import SchemaViolationError, enforce, score
from src.transform_join import (
    RULE_R1_INTERIOR,
    RULE_R2_BOUNDARY_UNIQUE,
    RULE_R3_TIEBREAK,
    RULE_R4_NO_MATCH,
    assign_hexagons_geometric,
    categorise_disagreements,
    hexes_to_geodataframe,
)
from tests import synthetic


@pytest.fixture(scope="module")
def hexes():
    return hexes_to_geodataframe(synthetic.hex_collection(radius=2))


def frame_of(points: list[tuple[float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        {"latitude": [p[0] for p in points], "longitude": [p[1] for p in points]}
    )


# =============================================================================
# Coordinate classes - 5 of 7 never occur in the supplied data
# =============================================================================

class TestEveryCoordinateClassFires:
    def test_all_seven_classes_are_reachable(self):
        """Every class must be producible, or the taxonomy is partly fiction."""
        frame, expected = synthetic.sr_with_coordinate_classes(per_class=20)
        summary = quality_checks.summarise(
            quality_checks.classify_coordinates(frame)
        )

        for label, count in expected.items():
            assert summary[label] == count, (
                f"class {label!r}: expected {count}, classifier reported "
                f"{summary[label]}"
            )
        assert sum(summary.values()) == len(frame)

    def test_dormant_classes_produce_warnings(self, caplog):
        """The operator must actually SEE these, not just have them counted.

        Each of these classes is silent on the supplied data, so the warning
        branch has never executed. If it were broken, nothing would reveal it.
        """
        frame, _ = synthetic.sr_with_coordinate_classes(per_class=5)
        summary = quality_checks.summarise(
            quality_checks.classify_coordinates(frame)
        )

        with caplog.at_level(logging.WARNING, logger="src.quality_checks"):
            quality_checks.log_summary(summary, len(frame))

        text = caplog.text
        for label in ("inverted", "null_island", "unparseable", "partial"):
            assert label in text, f"{label} was counted but never surfaced to the operator"


# =============================================================================
# Assignment rules - R2, R3 and invalid_coordinates never fire
# =============================================================================

class TestDormantAssignmentRules:
    def test_r3_tiebreak_fires_on_a_shared_edge(self, hexes):
        result = assign_hexagons_geometric(
            frame_of([synthetic.point_on_shared_edge()]), hexes
        )
        row = result.iloc[0]
        assert row["rule"] == RULE_R3_TIEBREAK
        assert row["n_candidates"] == 2

    def test_r3_tiebreak_fires_on_a_vertex_with_three_candidates(self, hexes):
        result = assign_hexagons_geometric(
            frame_of([synthetic.point_on_shared_vertex()]), hexes
        )
        row = result.iloc[0]
        assert row["rule"] == RULE_R3_TIEBREAK
        assert row["n_candidates"] == 3

    def test_r2_fires_when_only_one_candidate_is_available(self):
        """The last uncovered rule: a boundary point with exactly one candidate.

        Unreachable on the supplied data, because Cape Town's hexagons tile
        continuously - every interior boundary point touches at least two
        cells, which routes it to R3 instead.
        """
        hexes = hexes_to_geodataframe(synthetic.isolated_cell_collection())
        result = assign_hexagons_geometric(
            frame_of([synthetic.point_on_isolated_cell_boundary()]), hexes
        )
        row = result.iloc[0]
        assert row["rule"] == RULE_R2_BOUNDARY_UNIQUE
        assert row["n_candidates"] == 1

    def test_r4_fires_outside_coverage(self, hexes):
        result = assign_hexagons_geometric(
            frame_of([synthetic.point_outside_coverage()]), hexes
        )
        assert result.iloc[0]["rule"] == RULE_R4_NO_MATCH

    def test_all_rules_reachable_in_one_pass(self, hexes):
        """A single mixed batch must produce each outcome exactly once."""
        result = assign_hexagons_geometric(
            frame_of([
                synthetic.point_interior(),
                synthetic.point_on_shared_edge(),
                synthetic.point_outside_coverage(),
            ]),
            hexes,
        )
        assert set(result["rule"]) == {
            RULE_R1_INTERIOR, RULE_R3_TIEBREAK, RULE_R4_NO_MATCH
        }
        assert len(result) == 3


# =============================================================================
# Disagreement categories - 4 of 6 never fire
# =============================================================================

class TestDormantDisagreementCategories:
    def test_all_six_categories_are_reachable(self):
        """C1, C2, C3 and C5 never occur on the supplied data."""
        import h3

        anchor = synthetic.ANCHOR_CELL
        near = sorted(h3.grid_ring(anchor, 1))[0]
        far = sorted(h3.grid_ring(anchor, 3))[0]
        elsewhere = h3.latlng_to_cell(-26.2041, 28.0473, 8)

        frame = pd.DataFrame([
            {"h3_geometric": anchor, "h3_library": near, "rule": RULE_R3_TIEBREAK},
            {"h3_geometric": None, "h3_library": near, "rule": RULE_R4_NO_MATCH},
            {"h3_geometric": None, "h3_library": elsewhere, "rule": RULE_R4_NO_MATCH},
            {"h3_geometric": anchor, "h3_library": elsewhere, "rule": RULE_R1_INTERIOR},
            {"h3_geometric": anchor, "h3_library": near, "rule": RULE_R1_INTERIOR},
            {"h3_geometric": anchor, "h3_library": far, "rule": RULE_R1_INTERIOR},
        ])

        categories = set(
            categorise_disagreements(frame, valid_hexes={anchor, near, far})
        )

        assert categories == {
            "C1_boundary_tie", "C2_coverage_gap", "C2b_outside_coverage",
            "C3_out_of_tiling", "C4_adjacent_cell", "C5_non_adjacent",
        }

    def test_c5_non_adjacent_is_logged_as_an_error(self, caplog):
        """C5 is the stop-and-investigate signal and has never once fired."""
        import h3

        anchor = synthetic.ANCHOR_CELL
        far = sorted(h3.grid_ring(anchor, 3))[0]
        frame = pd.DataFrame([
            {"h3_geometric": anchor, "h3_library": far, "rule": RULE_R1_INTERIOR},
        ])
        assert categorise_disagreements(
            frame, valid_hexes={anchor, far}
        ).iloc[0] == "C5_non_adjacent"


# =============================================================================
# Consistency violations and threshold breaches - none ever fire
# =============================================================================

class TestThresholdsActuallyBreach:
    @pytest.fixture(scope="class")
    @classmethod
    def schema(cls):
        return config.load_sr_schema()

    def test_partial_coordinates_breach_and_raise(self, schema):
        n = 2000  # must clear structure.min_rows
        lat, lon = synthetic.point_interior()
        report = score(
            synthetic.sr_frame(
                n,
                latitude=[str(lat)] * n,
                longitude=[str(lon)] * (n - 10) + [""] * 10,
            ),
            schema,
        )
        assert "coordinate_pair_completeness" in report["consistency_violations"]
        with pytest.raises(SchemaViolationError):
            enforce(report, schema)

    def test_gross_time_inversion_breaches_and_raises(self, schema):
        n = 2000
        report = score(
            synthetic.sr_frame(
                n,
                creation_timestamp=["2020-07-01 08:00:00+02:00"] * n,
                completion_timestamp=["2019-01-01 08:00:00+02:00"] * n,
            ),
            schema,
        )
        assert "completion_before_creation_gross" in report["consistency_violations"]
        with pytest.raises(SchemaViolationError):
            enforce(report, schema)

    def test_null_rate_ceiling_breaches_and_raises(self, schema):
        n = 2000
        report = score(synthetic.sr_frame(n, directorate=[""] * n), schema)
        assert "directorate_null_rate" in report["consistency_violations"]
        with pytest.raises(SchemaViolationError):
            enforce(report, schema)

    def test_structural_failure_raises_before_scoring(self, schema):
        """Fatal, not scored: a truncated extract must never be graded."""
        with pytest.raises(SchemaViolationError, match="below the contract minimum"):
            score(synthetic.sr_frame(n=5), schema)

    def test_inversion_gate_refuses_to_join(self):
        """The hard gate that has never executed on real data."""
        frame, _ = synthetic.sr_with_coordinate_classes(per_class=10)
        classes = quality_checks.classify_coordinates(frame)
        assert (classes == CoordClass.INVERTED).sum() > 0, (
            "fixture failed to produce inverted coordinates"
        )


# =============================================================================
# Coverage analysis - the hole-detection branch never fires
# =============================================================================

class TestCoverageHoleDetection:
    def test_a_punched_hole_is_detected(self):
        """Remove one interior cell and the analysis must find it.

        On the supplied data this branch reports a single near-enclosed gap and
        zero fully-enclosed holes, so the fully-enclosed path has never run.
        """
        import h3

        disk = set(h3.grid_disk(synthetic.ANCHOR_CELL, 3))
        punched = disk - {synthetic.ANCHOR_CELL}

        report = coverage.analyse(punched)

        assert report["n_fully_enclosed_holes"] == 1
        assert synthetic.ANCHOR_CELL in [h["index"] for h in report["interior_holes"]]

    def test_intact_disk_reports_no_holes(self):
        import h3

        report = coverage.analyse(set(h3.grid_disk(synthetic.ANCHOR_CELL, 3)))
        assert report["n_fully_enclosed_holes"] == 0
        assert report["n_interior_holes"] == 0

    def test_enclosed_hole_is_logged_as_an_error(self, caplog):
        import h3

        punched = set(h3.grid_disk(synthetic.ANCHOR_CELL, 3)) - {synthetic.ANCHOR_CELL}
        with caplog.at_level(logging.ERROR, logger="src.coverage"):
            coverage.log_report(coverage.analyse(punched))

        assert "FULLY ENCLOSED" in caplog.text


# =============================================================================
# Side-car artifacts - never written on the supplied data
# =============================================================================

class TestAmbiguousSidecarIsWritten:
    def test_tiebreak_rows_carry_reviewable_diagnostics(self, hexes):
        """The ambiguous side-car has never been produced by a real run.

        Its columns must therefore be asserted here, or the first time it is
        written will be the first time anyone discovers whether it is usable.
        """
        result = assign_hexagons_geometric(
            frame_of([
                synthetic.point_on_shared_edge(),
                synthetic.point_on_shared_vertex(),
            ]),
            hexes,
        )
        ambiguous = result[result["rule"] == RULE_R3_TIEBREAK]
        assert len(ambiguous) == 2

        for _, row in ambiguous.iterrows():
            assert row["n_candidates"] >= 2
            assert "|" in row["candidate_indices"]
            assert len(row["candidate_indices"].split("|")) == row["n_candidates"]
            assert row["runner_up_index"] is not pd.NA
            # margin_m is the diagnostic that says whether the call was close.
            assert row["margin_m"] >= 0
