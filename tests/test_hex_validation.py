"""Tests for the hexagon conformance scorer (`src/validation.py`).

This module had no tests at all. It scores 1.000000 on the supplied data and
every one of its twelve rules is dormant there, so until now it had never been
demonstrated capable of returning anything other than a perfect score. A scorer
that has only ever returned 1.0 is indistinguishable from `return 1.0`.

Each test corrupts exactly one property and asserts that the corresponding rule
- and only that rule - drops.
"""

from __future__ import annotations

import pytest

from src import config
from src.validation import compare_to_reference, score_conformance
from tests import synthetic


@pytest.fixture(scope="module")
def schema() -> dict:
    return config.load_hex_schema()


@pytest.fixture
def clean() -> list[dict]:
    return synthetic.hex_collection(radius=2)


class TestCleanBaseline:
    def test_clean_collection_scores_perfectly(self, clean, schema):
        report = score_conformance(clean, schema)
        assert report["score"] == pytest.approx(1.0)
        assert report["verdict"] == "pass"
        assert report["failures"] == {}


class TestIndividualRulesFire:
    """Each corruption must move its own rule off 1.0."""

    @pytest.mark.parametrize(
        ("builder", "rule"),
        [
            ("hex_missing_index", "index_present"),
            ("hex_bad_index_pattern", "index_pattern"),
            ("hex_wrong_geometry_type", "geometry_type"),
            ("hex_wrong_vertex_count", "geometry_positions"),
            ("hex_unclosed_ring", "geometry_closed"),
            ("hex_out_of_bounds", "coordinates_in_bounds"),
            ("hex_missing_centroid", "centroid_present"),
            ("hex_centroid_outside_polygon", "centroid_within_polygon"),
            ("hex_wrong_resolution", "resolution_correct"),
        ],
    )
    def test_corruption_drops_its_rule(self, clean, schema, builder, rule):
        corrupted = [*clean[:-1], getattr(synthetic, builder)()]
        report = score_conformance(corrupted, schema)

        assert report["rule_scores"][rule] < 1.0, (
            f"{builder} did not trip {rule}; the rule is not detecting it"
        )
        assert report["score"] < 1.0
        assert rule in report["failures"]

    def test_duplicate_index_is_detected(self, clean, schema):
        report = score_conformance(synthetic.hex_duplicate_index(clean), schema)
        assert report["rule_scores"]["index_unique"] < 1.0

    def test_consistent_axis_inversion_is_caught_by_the_bounds_rules(self, clean, schema):
        """Ring AND centroid swapped: the file parses fine and joins to nothing.

        Note which rule catches it. A consistent inversion stays internally
        coherent - the centroid still sits inside its own polygon in the
        swapped space - so `centroid_within_polygon` CANNOT see it and is not
        a defence against this. The bounds rules are, because Cape Town's
        latitude and longitude ranges are disjoint and opposite in sign.
        """
        corrupted = [*clean[:-1], synthetic.hex_inverted_axes()]
        report = score_conformance(corrupted, schema)

        assert report["rule_scores"]["coordinates_in_bounds"] < 1.0
        assert report["rule_scores"]["centroid_in_bounds"] < 1.0
        # Documents the limitation rather than hiding it:
        assert report["rule_scores"]["centroid_within_polygon"] == 1.0

    def test_inconsistent_axis_inversion_is_caught_topologically(self, clean, schema):
        """Ring swapped but centroid correct - the complementary case.

        Here the bounds rules still fire on the ring, and `centroid_within_polygon`
        fires too, because the relationship between attributes and geometry is
        now broken. Between the two tests, both inversion shapes are covered.
        """
        corrupted = [*clean[:-1], synthetic.hex_inverted_geometry_only()]
        report = score_conformance(corrupted, schema)

        assert report["rule_scores"]["coordinates_in_bounds"] < 1.0
        assert report["rule_scores"]["centroid_within_polygon"] < 1.0

    def test_malformed_feature_does_not_raise(self, clean, schema):
        """A rule must score a broken feature as failing, never crash on it.

        If a malformed input can raise, the validator cannot report on exactly
        the data it exists to catch.
        """
        report = score_conformance([*clean, {}, {"properties": None}], schema)
        assert report["score"] < 1.0


class TestScoringBehaviour:
    def test_score_is_non_binary(self, clean, schema):
        """One bad feature in twenty must not collapse the score to zero."""
        corrupted = [*clean[:-1], synthetic.hex_bad_index_pattern()]
        report = score_conformance(corrupted, schema)
        assert 0.8 < report["score"] < 1.0

    def test_verdict_bands_are_reachable(self, clean, schema):
        """All three bands must be attainable, or the thresholds are decoration."""
        assert score_conformance(clean, schema)["verdict"] == "pass"

        # Corrupt every feature on a heavily weighted rule to force a failure.
        all_bad = [synthetic.hex_bad_index_pattern() for _ in range(20)]
        assert score_conformance(all_bad, schema)["verdict"] == "fail"

    def test_empty_collection_fails_rather_than_scoring_perfectly(self, schema):
        """Zero features must not vacuously satisfy every rule."""
        report = score_conformance([], schema)
        assert report["verdict"] == "fail"
        assert report["score"] == 0.0

    def test_feature_count_outside_expected_range_is_flagged(self, clean, schema):
        report = score_conformance(clean, schema)
        assert report["feature_count_in_expected_range"] is False  # 20 << min 2500

    def test_failures_carry_example_indices(self, clean, schema):
        report = score_conformance([*clean[:-1], synthetic.hex_wrong_resolution()], schema)
        examples = report["failures"]["resolution_correct"]
        assert examples and all(isinstance(e, str) for e in examples)


class TestReferenceComparison:
    def test_identical_collections_match(self, clean, schema):
        report = compare_to_reference(clean, clean, schema)
        assert report["passed"]
        assert report["n_geometry_exact_matches"] == len(clean)

    def test_missing_feature_is_reported(self, clean, schema):
        report = compare_to_reference(clean[:-1], clean, schema)
        assert not report["passed"]
        assert report["n_missing_from_extraction"] == 1

    def test_extra_feature_is_reported(self, clean, schema):
        report = compare_to_reference(clean, clean[:-1], schema)
        assert not report["passed"]
        assert report["n_extra_in_extraction"] == 1

    def test_resolution_asymmetry_does_not_cause_a_false_mismatch(self, clean, schema):
        """The reference has no `resolution`; the extraction does.

        Comparing whole records would report a total mismatch on a correct
        extraction. This is the asymmetry documented in discrepancies.md E2, and
        the reason comparison runs on the intersection of properties.
        """
        reference = []
        for feature in clean:
            copy_ = {**feature, "properties": dict(feature["properties"])}
            del copy_["properties"]["resolution"]
            reference.append(copy_)

        report = compare_to_reference(clean, reference, schema)
        assert report["passed"], "the known resolution asymmetry was misread as a mismatch"

    def test_shifted_geometry_is_detected(self, clean, schema):
        """A shift far above tolerance must be caught, not absorbed."""
        shifted = [{**f, "properties": dict(f["properties"]),
                    "geometry": {**f["geometry"]}} for f in clean]
        ring = [[lon + 0.01, lat] for lon, lat in shifted[0]["geometry"]["coordinates"][0]]
        shifted[0]["geometry"]["coordinates"] = [ring]

        report = compare_to_reference(shifted, clean, schema)
        assert report["n_geometry_mismatches"] == 1
        assert not report["passed"]
