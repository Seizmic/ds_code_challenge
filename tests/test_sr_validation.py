"""Tests for the service request data contract.

These tests feed the validator *deliberately broken* data. The supplied dataset
is clean, so validating only against it proves nothing about whether the checks
would actually fire. Each test below corresponds to a way a different source
could be malformed while still looking superficially fine.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src import config
from src.sr_validation import SchemaViolationError, check_structure, enforce, score


@pytest.fixture(scope="module")
def schema() -> dict:
    return config.load_sr_schema()


def make_frame(n: int = 2000, **overrides) -> pd.DataFrame:
    """A minimal clean frame, with named columns overridable to break it."""
    base = {
        "notification_number": [f"{i:012d}" for i in range(n)],
        "reference_number": [f"9{i:09d}" for i in range(n)],
        "creation_timestamp": ["2020-07-01 08:00:00+02:00"] * n,
        "completion_timestamp": ["2020-07-02 08:00:00+02:00"] * n,
        "directorate": ["URBAN MOBILITY"] * n,
        "department": ["Roads"] * n,
        "branch": ["RIM"] * n,
        "section": ["District"] * n,
        "code_group": ["TD"] * n,
        "code": ["Pothole"] * n,
        "cause_code_group": [""] * n,
        "cause_code": [""] * n,
        "official_suburb": ["MONTAGUE GARDENS"] * n,
        "latitude": ["-33.9249"] * n,
        "longitude": ["18.4241"] * n,
    }
    base.update(overrides)
    return pd.DataFrame(base, dtype="string")


class TestStructuralContract:
    """Structural failure is fatal, not scored."""

    def test_missing_column_is_fatal(self, schema):
        frame = make_frame().drop(columns=["latitude"])
        with pytest.raises(SchemaViolationError, match="missing required column"):
            check_structure(frame, schema)

    def test_truncated_input_is_fatal(self, schema):
        """A near-empty input must not be scored as if it were complete.

        Ten rows could score 1.0 on every rule while being a catastrophically
        broken extract. Row count is checked before anything is measured.
        """
        with pytest.raises(SchemaViolationError, match="below the contract minimum"):
            check_structure(make_frame(n=10), schema)

    def test_extra_columns_are_tolerated(self, schema):
        frame = make_frame()
        frame["some_new_upstream_column"] = "x"
        check_structure(frame, schema)  # must not raise


class TestConsistencyChecks:
    """Cross-column rules -- individually valid data that is jointly incoherent."""

    def test_partial_coordinates_are_caught(self, schema):
        """One ordinate present and the other absent.

        Without this rule the record is treated as ungeolocated, silently
        assigned index 0, and the fault disappears into the expected
        no-geolocation count. Nothing downstream would ever reveal it.
        """
        n = 2000
        lat = ["-33.9249"] * n
        lon = ["18.4241"] * (n - 100) + [""] * 100  # 100 half-populated rows
        report = score(make_frame(n, latitude=lat, longitude=lon), schema)

        assert report["rule_scores"]["coordinate_pair_completeness"] < 1.0
        assert "coordinate_pair_completeness" in report["consistency_violations"]
        with pytest.raises(SchemaViolationError, match="consistency"):
            enforce(report, schema)

    def test_duplicate_identifiers_are_caught(self, schema):
        n = 2000
        ids = [f"{i:012d}" for i in range(n - 50)] + [f"{0:012d}"] * 50
        report = score(make_frame(n, notification_number=ids), schema)
        assert report["rule_scores"]["notification_number_unique"] < 1.0

    def test_gross_time_inversion_fails_but_clock_skew_does_not(self, schema):
        """The magnitude split is the point of this rule.

        Seconds backwards is clock skew between two recording systems and is
        normal. Days backwards means swapped columns or a timezone fault. A
        single threshold cannot tell these apart, so they are separate rules.
        """
        n = 2000
        created = ["2020-07-01 08:00:00+02:00"] * n

        skewed = ["2020-07-01 07:59:56+02:00"] * n          # 4 seconds early
        skew_report = score(
            make_frame(n, creation_timestamp=created, completion_timestamp=skewed),
            schema,
        )
        assert skew_report["rule_scores"]["completion_after_creation_gross"] == 1.0
        assert "completion_before_creation_gross" not in skew_report["consistency_violations"]

        gross = ["2020-06-01 08:00:00+02:00"] * n            # a month early
        gross_report = score(
            make_frame(n, creation_timestamp=created, completion_timestamp=gross),
            schema,
        )
        assert gross_report["rule_scores"]["completion_after_creation_gross"] < 1.0
        assert "completion_before_creation_gross" in gross_report["consistency_violations"]

    def test_column_going_entirely_null_is_caught(self, schema):
        """A weighted mean can absorb one dead column; the ceiling cannot.

        directorate at 100% null still leaves an aggregate above the pass
        threshold, because its weight is deliberately low. The per-column null
        ceiling is what actually catches it.
        """
        n = 2000
        report = score(make_frame(n, directorate=[""] * n), schema)

        assert "directorate_null_rate" in report["consistency_violations"]
        with pytest.raises(SchemaViolationError):
            enforce(report, schema)


class TestCleanDataPasses:
    def test_clean_frame_scores_perfectly_and_enforces_cleanly(self, schema):
        report = score(make_frame(), schema)

        assert report["score"] == pytest.approx(1.0)
        assert report["verdict"] == "pass"
        assert report["consistency_violations"] == {}
        enforce(report, schema)  # must not raise

    def test_out_of_range_coordinates_are_caught(self, schema):
        n = 2000
        report = score(make_frame(n, latitude=["-26.2041"] * n,
                                  longitude=["28.0473"] * n), schema)
        assert report["rule_scores"]["latitude_in_range"] < 1.0
        assert report["rule_scores"]["longitude_in_range"] < 1.0
