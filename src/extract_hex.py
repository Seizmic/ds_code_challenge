"""Section 1: extract H3 resolution-8 hexagons via AWS S3 Select.

Reads the resolution-8 subset out of ``city-hex-polygons-8-10.geojson`` (108 MB)
without transferring the whole object, validates the result against
``city-hex-polygons-8.geojson``, and scores schema conformance.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import Any

from src import config, s3_io, validation
from src.logging_setup import MANIFEST, human_bytes, timed

logger = logging.getLogger(__name__)

OUTPUT_PATH = config.PROCESSED_DIR / "city-hex-polygons-8-extracted.geojson"


def extract_via_s3_select(client) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Pull resolution-8 features using server-side filtering."""
    with timed("section1.s3_select_extraction", logger):
        features, stats = s3_io.s3_select_json(
            client, config.KEY_HEX_8_10, config.S3_SELECT_EXPRESSION
        )
    return features, stats


def extract_via_naive_download(client) -> list[dict[str, Any]]:
    """Baseline: download the whole object and filter locally.

    Exists purely so the S3 Select saving is a measured comparison rather than
    an assertion. Off by default because it transfers 108 MB.

    Deliberately BYPASSES the download cache. The point of this baseline is to
    measure what the naive approach costs, which is dominated by transferring
    108 MB. Reading a warm cache from local disk measures nothing of the sort,
    and on a second run made S3 Select look 0.5x "faster" than a baseline that
    never touched the network. A cached baseline is not a baseline.
    """
    with timed("section1.naive_baseline", logger):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / config.KEY_HEX_8_10
            logger.info("Baseline: downloading the full object (cache bypassed)...")
            client.download_file(config.S3_BUCKET, config.KEY_HEX_8_10, str(path))
            with path.open("r", encoding="utf-8") as handle:
                collection = json.load(handle)
            features = [
                f for f in collection["features"]
                if (f.get("properties") or {}).get("resolution")
                == config.TARGET_RESOLUTION
            ]
    logger.info("Naive baseline extracted %d features from the full document",
                len(features))
    return features


def load_reference(client) -> list[dict[str, Any]]:
    """Load the resolution-8 reference file used to validate the extraction."""
    with timed("section1.load_reference", logger):
        path = s3_io.download_cached(client, config.KEY_HEX_8)
        with path.open("r", encoding="utf-8") as handle:
            collection = json.load(handle)
    return collection["features"]


def write_output(features: list[dict[str, Any]], path: Path = OUTPUT_PATH) -> Path:
    """Write the extracted features as a GeoJSON FeatureCollection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    collection = {
        "type": "FeatureCollection",
        "name": "city-hex-polygons-8",
        "crs": {
            "type": "name",
            "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"},
        },
        "features": [
            {"type": "Feature", "properties": f["properties"], "geometry": f["geometry"]}
            for f in features
        ],
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(collection, handle)
    logger.info("Wrote %d features to %s (%s)",
                len(features), path, human_bytes(path.stat().st_size))
    return path


def run(client=None, run_baseline: bool = False) -> dict[str, Any]:
    """Execute Section 1 end to end. Returns the extracted features and reports."""
    client = client or s3_io.make_s3_client()
    schema = config.load_hex_schema()

    features, stats = extract_via_s3_select(client)
    if not features:
        raise RuntimeError(
            "S3 Select returned no features. Check the filter expression in "
            "config.S3_SELECT_EXPRESSION against the source schema."
        )

    # --- Efficiency metrics --------------------------------------------------
    object_size = client.head_object(
        Bucket=config.S3_BUCKET, Key=config.KEY_HEX_8_10
    )["ContentLength"]
    bytes_returned = stats.get("BytesReturned", 0)
    reduction = 1.0 - (bytes_returned / object_size) if object_size else 0.0

    MANIFEST.record_metric("section1.source_object_bytes", object_size)
    MANIFEST.record_metric("section1.bytes_scanned", stats.get("BytesScanned"))
    MANIFEST.record_metric("section1.bytes_returned", bytes_returned)
    MANIFEST.record_metric("section1.transfer_reduction_pct", round(reduction * 100, 3))
    MANIFEST.record_metric("section1.n_features_extracted", len(features))

    logger.info(
        "Transfer reduction: %s returned from a %s object (%.2f%% less data)",
        human_bytes(bytes_returned), human_bytes(object_size), reduction * 100,
    )

    # --- Schema conformance --------------------------------------------------
    with timed("section1.conformance_scoring", logger):
        conformance = validation.score_conformance(features, schema)
    validation.log_conformance(conformance, schema)
    MANIFEST.record_metric("section1.conformance", conformance)
    MANIFEST.record_verdict(
        "section1.schema_conformance",
        conformance["verdict"] != "fail",
        f"score={conformance['score']} verdict={conformance['verdict']}",
    )

    if conformance["verdict"] == "fail":
        raise ValueError(
            f"Schema conformance {conformance['score']:.6f} is below the failure "
            f"threshold {schema['scoring']['thresholds']['warn']}. "
            "See the rule breakdown above."
        )

    # --- Polygon overlap (collection-level) ----------------------------------
    # Checks the CAUSE in the input rather than the symptom in the output. The
    # join already guards against a point landing inside two polygons, but that
    # only fires where a service request happens to be; an overlap in an area
    # with no requests is invisible to it.
    with timed("section1.overlap_check", logger):
        overlaps = validation.check_overlaps(features, schema)
    validation.log_overlaps(overlaps)
    MANIFEST.record_metric("section1.polygon_overlaps", overlaps)
    MANIFEST.record_verdict(
        "section1.no_overlapping_polygons",
        overlaps["n_overlapping"] == 0,
        f"{overlaps['n_overlapping']} overlapping of "
        f"{overlaps['n_pairs_checked']} adjacent pairs",
    )

    if overlaps["n_overlapping"]:
        raise ValueError(
            f"{overlaps['n_overlapping']} pair(s) of supplied polygons overlap "
            "with positive area. Overlapping hexagons make a point match more "
            "than one cell, which duplicates service requests downstream. "
            "Refusing to proceed on a tiling that is not a partition."
        )

    # --- Validation against the reference file -------------------------------
    reference = load_reference(client)
    with timed("section1.reference_comparison", logger):
        comparison = validation.compare_to_reference(features, reference, schema)

    MANIFEST.record_metric("section1.reference_comparison", comparison)
    MANIFEST.record_verdict(
        "section1.reference_match", comparison["passed"],
        f"{comparison['n_common']} common of {comparison['n_reference']} reference features",
    )

    if comparison["passed"]:
        logger.info(
            "Reference validation PASSED: %d features match exactly "
            "(%d geometries byte-identical)",
            comparison["n_common"], comparison["n_geometry_exact_matches"],
        )
    else:
        logger.error(
            "Reference validation FAILED: %d missing, %d extra, "
            "%d property mismatches, %d geometry mismatches",
            comparison["n_missing_from_extraction"],
            comparison["n_extra_in_extraction"],
            comparison["n_property_mismatches"],
            comparison["n_geometry_mismatches"],
        )
        for kind, examples in comparison["examples"].items():
            if examples:
                logger.error("  %s e.g. %s", kind, ", ".join(map(str, examples)))

    # --- Optional baseline ---------------------------------------------------
    if run_baseline:
        baseline_features = extract_via_naive_download(client)
        agree = len(baseline_features) == len(features)
        MANIFEST.record_metric("section1.baseline_n_features", len(baseline_features))
        MANIFEST.record_verdict(
            "section1.baseline_agrees_with_select", agree,
            f"select={len(features)} baseline={len(baseline_features)}",
        )
        timings = MANIFEST.data["timings_seconds"]
        if "section1.naive_baseline" in timings and timings["section1.s3_select_extraction"]:
            speedup = timings["section1.naive_baseline"] / timings["section1.s3_select_extraction"]
            MANIFEST.record_metric("section1.select_vs_baseline_speedup", round(speedup, 2))
            logger.info("S3 Select was %.1fx faster than the naive baseline", speedup)

    write_output(features)

    return {
        "features": features,
        "conformance": conformance,
        "comparison": comparison,
        "stats": stats,
    }
