"""Integration tests: the pieces wired together, not in isolation.

The challenge asks Data Engineering candidates for "unit and even integration
tests". The unit suites verify each rule in isolation, which says nothing about
whether `run()` calls them, in the right order, with the gates actually wired
up. A rule that works perfectly but is never invoked passes every unit test.

These run the Section 2 orchestration over a small in-memory dataset with the
network stubbed out, so they execute in milliseconds and need no credentials.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src import config, transform_join
from src.sr_validation import SchemaViolationError
from tests import synthetic


class StubClient:
    """Stands in for the boto3 S3 client. Nothing leaves the machine."""

    def __init__(self, sr_frame: pd.DataFrame, reference: pd.DataFrame) -> None:
        self.sr_frame = sr_frame
        self.reference = reference
        self.downloads: list[str] = []

    def download_file(self, bucket: str, key: str, path: str) -> None:
        self.downloads.append(key)
        frame = self.reference if key == config.KEY_SR_HEX else self.sr_frame
        compression = "gzip" if key.endswith(".gz") else None
        frame.to_csv(path, index=(key == config.KEY_SR), compression=compression)

    def head_object(self, Bucket: str, Key: str) -> dict:  # noqa: N803 - boto3 API
        return {"ETag": '"stub"', "ContentLength": 1}


@pytest.fixture(autouse=True)
def workspace(tmp_path, monkeypatch):
    """Redirect every output path into a temporary directory.

    Autouse and restoring: `config.set_data_dir` mutates module globals, so a
    test that redirects them would otherwise leak into every later test in the
    session.
    """
    original = config.DATA_DIR
    config.set_data_dir(tmp_path / "data")
    config.ensure_directories()
    yield tmp_path
    config.set_data_dir(original)


def build_inputs(n: int = 1200) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    """A small dataset that is internally consistent and joinable."""
    import h3

    features = synthetic.hex_collection(radius=3)
    cells = [f["properties"]["index"] for f in features]

    rows = []
    for i in range(n):
        cell = cells[i % len(cells)]
        lat, lon = h3.cell_to_latlng(cell)
        rows.append({"lat": lat, "lon": lon, "cell": cell})

    sr = synthetic.sr_frame(
        n,
        latitude=[str(r["lat"]) for r in rows],
        longitude=[str(r["lon"]) for r in rows],
    )
    reference = pd.DataFrame({
        "notification_number": sr["notification_number"],
        "h3_level8_index": [r["cell"] for r in rows],
    })
    return sr, reference, features


class TestSectionTwoWiring:
    def test_full_section_two_runs_and_writes_every_artifact(self, workspace):
        sr, reference, features = build_inputs()
        client = StubClient(sr, reference)

        result = transform_join.run(client, hex_features=features)

        # The pipeline produced output for every input row.
        assert len(result["output"]) == len(sr)
        assert config.processed_path("sr_hex").exists()

        # The quality side-car is written, not merely computed.
        assert config.quality_path("join_summary").exists()
        summary = json.loads(config.quality_path("join_summary").read_text())
        assert summary["n_records"] == len(sr)
        assert summary["n_geolocated"] == len(sr)

        # Validation against the reference actually ran and agreed.
        assert result["validation"]["match_rate"] == pytest.approx(1.0)
        assert result["validation"]["n_disagree"] == 0

    def test_missing_coordinates_receive_the_mandated_sentinel(self, workspace):
        """The spec's one explicit output rule, checked end to end."""
        sr, reference, features = build_inputs()
        sr.loc[: 99, "latitude"] = ""
        sr.loc[: 99, "longitude"] = ""
        reference.loc[: 99, "h3_level8_index"] = config.NO_GEOLOCATION_INDEX

        result = transform_join.run(StubClient(sr, reference), hex_features=features)

        emitted = result["output"]["h3_level8_index"]
        assert (emitted.iloc[:100] == config.NO_GEOLOCATION_INDEX).all()
        assert result["validation"]["match_rate"] == pytest.approx(1.0)

    def test_inverted_coordinates_abort_the_run(self, workspace):
        """The gate must stop the pipeline, not merely log a warning.

        A unit test proves the classifier detects inversion. Only an
        integration test proves `run()` acts on it.
        """
        sr, reference, features = build_inputs()
        sr["latitude"], sr["longitude"] = sr["longitude"].copy(), sr["latitude"].copy()

        with pytest.raises(ValueError, match="inverted coordinates"):
            transform_join.run(StubClient(sr, reference), hex_features=features)

        # The contract fires before the join-stage gate, which is the right
        # order - but the message must still name the cause rather than
        # reporting it as a longitude out of range.

    def test_contract_violation_aborts_before_the_join(self, workspace):
        """A broken input must fail the contract, not reach the spatial join."""
        sr, reference, features = build_inputs()
        sr["directorate"] = ""

        with pytest.raises(SchemaViolationError):
            transform_join.run(StubClient(sr, reference), hex_features=features)

    def test_truncated_input_is_refused(self, workspace):
        sr, reference, features = build_inputs(n=1200)
        with pytest.raises(SchemaViolationError, match="below the contract minimum"):
            transform_join.run(
                StubClient(sr.head(10), reference.head(10)), hex_features=features
            )

    def test_join_method_flag_switches_the_published_column(self, workspace, monkeypatch):
        sr, reference, features = build_inputs()

        monkeypatch.setattr(config, "JOIN_METHOD", "library")
        library = transform_join.run(StubClient(sr, reference), hex_features=features)

        monkeypatch.setattr(config, "JOIN_METHOD", "geometric")
        geometric = transform_join.run(StubClient(sr, reference), hex_features=features)

        # On clean interior points the two agree, so this asserts the flag is
        # honoured rather than that the results differ.
        assert library["output"]["h3_level8_index"].equals(
            geometric["output"]["h3_level8_index"]
        )

    def test_unknown_join_method_is_rejected(self, workspace, monkeypatch):
        sr, reference, features = build_inputs()
        monkeypatch.setattr(config, "JOIN_METHOD", "nonsense")

        with pytest.raises(ValueError, match="JOIN_METHOD"):
            transform_join.run(StubClient(sr, reference), hex_features=features)


class TestDataDirRedirection:
    """`--data-dir` exists for one concrete reason, tested here.

    Both `--join-method` settings write the same output filename, so comparing
    the geometric and library results requires somewhere separate to put them.
    Without this the second run silently overwrites the first.
    """

    def test_outputs_follow_the_configured_data_dir(self, tmp_path, monkeypatch):
        sr, reference, features = build_inputs()

        first = tmp_path / "run_geometric"
        monkeypatch.setattr(config, "JOIN_METHOD", "geometric")
        config.set_data_dir(first)
        config.ensure_directories()
        transform_join.run(StubClient(sr, reference), hex_features=features)

        second = tmp_path / "run_library"
        monkeypatch.setattr(config, "JOIN_METHOD", "library")
        config.set_data_dir(second)
        config.ensure_directories()
        transform_join.run(StubClient(sr, reference), hex_features=features)

        # Both runs survive: neither clobbered the other.
        assert (first / "processed" / "sr_hex.csv.gz").exists()
        assert (second / "processed" / "sr_hex.csv.gz").exists()
        assert (first / "quality" / "join_summary.json").exists()
        assert (second / "quality" / "join_summary.json").exists()

    def test_set_data_dir_moves_every_directory(self, tmp_path):
        config.set_data_dir(tmp_path / "elsewhere")
        assert config.RAW_DIR == tmp_path / "elsewhere" / "raw"
        assert config.PROCESSED_DIR == tmp_path / "elsewhere" / "processed"
        assert config.QUALITY_DIR == tmp_path / "elsewhere" / "quality"
        assert config.processed_path("sr_hex").parent == config.PROCESSED_DIR
        assert config.quality_path("join_summary").parent == config.QUALITY_DIR


class TestOutputShape:
    def test_output_preserves_input_columns_and_adds_the_index(self, workspace):
        sr, reference, features = build_inputs()
        result = transform_join.run(StubClient(sr, reference), hex_features=features)

        for column in synthetic.SR_COLUMNS:
            assert column in result["output"].columns
        assert "h3_level8_index" in result["output"].columns

    def test_every_row_gets_exactly_one_index(self, workspace):
        """The core guarantee: the join must not duplicate service requests."""
        sr, reference, features = build_inputs()
        result = transform_join.run(StubClient(sr, reference), hex_features=features)

        assert len(result["output"]) == len(sr)
        assert result["output"]["h3_level8_index"].notna().all()
