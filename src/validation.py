"""Schema conformance scoring and reference validation for the hexagon dataset.

The conformance score is non-binary in two distinct senses, both of which the
challenge asks for:

1. Each rule scores the *fraction* of features satisfying it, in ``[0, 1]`` --
   not a pass/fail flag. One bad feature in 3,000 scores 0.9997, not 0.
2. The aggregate is a weighted mean of rule scores, graded against pass / warn /
   fail bands rather than a single cutoff, so a marginal result stays visible
   instead of being rounded to a verdict.

Rules are driven entirely by ``config/hex_schema.yaml``; none are hard-coded here.
"""

from __future__ import annotations

import logging
import re

import numpy as np
from typing import Any, Callable

from shapely import STRtree, area, intersection
from shapely.geometry import Polygon

logger = logging.getLogger(__name__)

Feature = dict[str, Any]
RuleFn = Callable[[Feature, dict[str, Any]], bool]


# --- Individual rules --------------------------------------------------------
# Each returns True when the feature satisfies the rule. Rules must never raise
# on malformed input -- a malformed feature is a rule failure, not a crash.

def _props(feature: Feature) -> dict[str, Any]:
    return feature.get("properties") or {}


def _ring(feature: Feature) -> list:
    try:
        return feature["geometry"]["coordinates"][0]
    except (KeyError, IndexError, TypeError):
        return []


def rule_index_present(feature: Feature, schema: dict) -> bool:
    return bool(_props(feature).get("index"))


def rule_index_pattern(feature: Feature, schema: dict) -> bool:
    pattern = schema["properties"]["index"]["pattern"]
    value = _props(feature).get("index")
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def rule_geometry_type(feature: Feature, schema: dict) -> bool:
    expected = schema["geometry"]["type"]
    return (feature.get("geometry") or {}).get("type") == expected


def rule_geometry_positions(feature: Feature, schema: dict) -> bool:
    return len(_ring(feature)) == schema["geometry"]["positions"]


def rule_geometry_closed(feature: Feature, schema: dict) -> bool:
    ring = _ring(feature)
    return len(ring) >= 2 and ring[0] == ring[-1]


def rule_coordinates_in_bounds(feature: Feature, schema: dict) -> bool:
    bounds = schema["geometry"]["bounds"]
    ring = _ring(feature)
    if not ring:
        return False
    for position in ring:
        try:
            lon, lat = position[0], position[1]
        except (IndexError, TypeError):
            return False
        if not (bounds["lon"][0] <= lon <= bounds["lon"][1]):
            return False
        if not (bounds["lat"][0] <= lat <= bounds["lat"][1]):
            return False
    return True


def rule_centroid_present(feature: Feature, schema: dict) -> bool:
    props = _props(feature)
    return isinstance(props.get("centroid_lat"), (int, float)) and isinstance(
        props.get("centroid_lon"), (int, float)
    )


def rule_centroid_in_bounds(feature: Feature, schema: dict) -> bool:
    props = _props(feature)
    lat, lon = props.get("centroid_lat"), props.get("centroid_lon")
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False
    spec = schema["properties"]
    return (
        spec["centroid_lat"]["min"] <= lat <= spec["centroid_lat"]["max"]
        and spec["centroid_lon"]["min"] <= lon <= spec["centroid_lon"]["max"]
    )


def rule_centroid_within_polygon(feature: Feature, schema: dict) -> bool:
    """Centroid must lie inside its own polygon.

    This is the single most effective check against axis inversion: if latitude
    and longitude were swapped in either the centroid or the ring, the point
    lands far outside and this fails for essentially every feature at once.
    """
    props = _props(feature)
    lat, lon = props.get("centroid_lat"), props.get("centroid_lon")
    ring = _ring(feature)
    if not ring or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return False

    # Ray casting, done inline rather than via shapely: this runs per feature
    # and a point-in-polygon test on seven positions is cheaper than building a
    # geometry object for each one.
    inside = False
    n = len(ring)
    for i in range(n - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        if (y1 > lat) != (y2 > lat):
            x_at = (x2 - x1) * (lat - y1) / (y2 - y1) + x1
            if lon < x_at:
                inside = not inside
    return inside


def rule_single_ring(feature: Feature, schema: dict) -> bool:
    """Exactly one ring: an H3 cell has no holes.

    The schema declared ``rings: 1`` from the start but nothing read it, so a
    polygon carrying interior rings would have scored as valid.
    """
    try:
        rings = feature["geometry"]["coordinates"]
    except (KeyError, TypeError):
        return False
    return isinstance(rings, list) and len(rings) == schema["geometry"]["rings"]


def rule_geometry_simple(feature: Feature, schema: dict) -> bool:
    """The polygon must not self-intersect.

    The schema declared ``must_be_valid: true  # no self-intersection`` but the
    old ``geometry_valid`` score was only the minimum of the type, position-count
    and closure rules - none of which detect a bow-tie. A self-intersecting
    hexagon passed every check.
    """
    if not schema["geometry"].get("must_be_valid", False):
        return True
    ring = _ring(feature)
    if len(ring) < 4:
        return False
    try:
        return Polygon(ring).is_valid
    except Exception:  # noqa: BLE001 - malformed input is a rule failure, not a crash
        return False


def rule_axis_order(feature: Feature, schema: dict) -> bool:
    """Positions must be [longitude, latitude], per RFC 7946.

    Named explicitly rather than left implicit in the bounds rule, because axis
    inversion is the defect most likely to arrive from an upstream change and
    the one whose symptom - a join that matches nothing - points away from its
    cause. Reliable for Cape Town because the longitude range (+18 to +19) and
    the latitude range (-34 to -33) are disjoint and opposite in sign, so a
    swapped pair cannot masquerade as a valid one.
    """
    if schema["geometry"].get("axis_order") != "lon_lat":
        return True
    bounds = schema["geometry"]["bounds"]
    ring = _ring(feature)
    if not ring:
        return False
    for position in ring:
        try:
            first, second = position[0], position[1]
        except (IndexError, TypeError):
            return False
        # A swapped position puts latitude first and longitude second.
        if (bounds["lat"][0] <= first <= bounds["lat"][1]
                and bounds["lon"][0] <= second <= bounds["lon"][1]):
            return False
    return True


def rule_resolution_correct(feature: Feature, schema: dict) -> bool:
    """Resolution must equal 8 when present.

    Absence is tolerated: the reference file carries no ``resolution`` property
    at all (docs/discrepancies.md E2), so requiring it would penalise the
    reference for a difference we already know about and have documented.
    """
    props = _props(feature)
    if "resolution" not in props:
        return True
    return props["resolution"] == schema["properties"]["resolution"]["equals"]


RULES: dict[str, RuleFn] = {
    "index_present": rule_index_present,
    "index_pattern": rule_index_pattern,
    "geometry_type": rule_geometry_type,
    "geometry_positions": rule_geometry_positions,
    "geometry_closed": rule_geometry_closed,
    "geometry_single_ring": rule_single_ring,
    "geometry_simple": rule_geometry_simple,
    "axis_order": rule_axis_order,
    "coordinates_in_bounds": rule_coordinates_in_bounds,
    "centroid_present": rule_centroid_present,
    "centroid_in_bounds": rule_centroid_in_bounds,
    "centroid_within_polygon": rule_centroid_within_polygon,
    "resolution_correct": rule_resolution_correct,
}


def check_overlaps(
    features: list[Feature], schema: dict[str, Any]
) -> dict[str, Any]:
    """Detect polygons that overlap with positive area.

    Collection-level rather than per-feature: overlap is a relationship between
    polygons, so no amount of inspecting one feature reveals it.

    **Why this exists when H3 guarantees non-overlap.** We are validating a
    supplied file, not trusting the process that produced it. The same reasoning
    retired `must_be_valid` as dead configuration: a guarantee asserted by the
    generator is not a property verified in the artifact.

    **Why the existing check was not enough.** ``assign_hexagons_geometric``
    already guards against a point landing strictly inside two polygons, but
    that is *point-driven* - it only fires where a service request happens to
    be. An overlap in an area with no requests is invisible to it. This checks
    the cause in the input rather than the symptom in the output.

    Adjacent H3 cells share edges by design, so a shared boundary produces a
    zero-area LineString intersection. Only positive area is a defect, and a
    small tolerance absorbs floating-point noise at the seams.
    """
    tolerance = float(
        schema["collection"].get("max_overlap_area_deg2", 1.0e-14)
    )
    geometries = []
    indices = []
    for feature in features:
        ring = _ring(feature)
        if len(ring) < 4:
            continue
        try:
            geometries.append(Polygon(ring))
        except Exception:  # noqa: BLE001 - malformed geometry is scored elsewhere
            continue
        indices.append(_props(feature).get("index", "<no index>"))

    if len(geometries) < 2:
        return {"n_polygons": len(geometries), "n_pairs_checked": 0,
                "n_overlapping": 0, "max_overlap_area_deg2": 0.0, "examples": []}

    geometries = np.array(geometries, dtype=object)
    tree = STRtree(geometries)
    left, right = tree.query(geometries, predicate="intersects")
    unique = left < right          # each unordered pair once, self-pairs dropped
    left, right = left[unique], right[unique]

    areas = area(intersection(geometries[left], geometries[right]))
    offending = areas > tolerance

    examples = [
        {"a": indices[int(i)], "b": indices[int(j)], "area_deg2": float(a)}
        for i, j, a in zip(left[offending], right[offending], areas[offending])
    ][:5]

    return {
        "n_polygons": len(geometries),
        "n_pairs_checked": int(len(left)),
        "n_overlapping": int(offending.sum()),
        "max_overlap_area_deg2": float(areas.max()) if len(areas) else 0.0,
        "tolerance_deg2": tolerance,
        "examples": examples,
    }


def log_overlaps(report: dict[str, Any]) -> None:
    """Log the overlap report at a level matching its result."""
    if report["n_overlapping"]:
        logger.error(
            "Polygon overlap: %d of %d pairs overlap with positive area "
            "(max %.3e deg2). Overlapping hexagons cause a point to match more "
            "than one cell, which duplicates service requests downstream.",
            report["n_overlapping"], report["n_pairs_checked"],
            report["max_overlap_area_deg2"],
        )
        for example in report["examples"]:
            logger.error("    %s / %s  area=%.3e deg2",
                         example["a"], example["b"], example["area_deg2"])
    else:
        logger.info(
            "Polygon overlap: none. %d adjacent pairs share edges only "
            "(zero-area intersections), as H3 requires.",
            report["n_pairs_checked"],
        )


def score_conformance(features: list[Feature], schema: dict) -> dict[str, Any]:
    """Score a feature collection against the schema contract."""
    if not features:
        return {
            "score": 0.0, "verdict": "fail", "n_features": 0,
            "rule_scores": {}, "failures": {},
            "detail": "no features to score",
        }

    scoring = schema["scoring"]
    weights = scoring["weights"]
    max_examples = scoring.get("max_examples_per_rule", 5)

    rule_scores: dict[str, float] = {}
    failures: dict[str, list[str]] = {}

    for name, rule in RULES.items():
        failing = [f for f in features if not rule(f, schema)]
        rule_scores[name] = (len(features) - len(failing)) / len(features)
        if failing:
            failures[name] = [
                str(_props(f).get("index", "<no index>")) for f in failing[:max_examples]
            ]

    # Uniqueness is collection-level, not per-feature, so it is scored separately
    # as the fraction of features carrying a non-duplicated index.
    indices = [_props(f).get("index") for f in features]
    unique_count = sum(1 for i in indices if indices.count(i) == 1) if len(indices) < 5000 else None
    if unique_count is None:
        seen: dict[Any, int] = {}
        for i in indices:
            seen[i] = seen.get(i, 0) + 1
        unique_count = sum(1 for i in indices if seen[i] == 1)
    rule_scores["index_unique"] = unique_count / len(features)

    # geometry_valid: a closed, correctly-sized, single ring within bounds.
    rule_scores["geometry_valid"] = min(
        rule_scores["geometry_type"],
        rule_scores["geometry_positions"],
        rule_scores["geometry_closed"],
        rule_scores["geometry_single_ring"],
        rule_scores["geometry_simple"],
    )

    total_weight = sum(weights.get(name, 0.0) for name in rule_scores)
    if total_weight == 0:
        raise ValueError("Schema defines no weights for any active rule")
    score = sum(
        rule_scores[name] * weights.get(name, 0.0) for name in rule_scores
    ) / total_weight

    thresholds = scoring["thresholds"]
    if score >= thresholds["pass"]:
        verdict = "pass"
    elif score >= thresholds["warn"]:
        verdict = "warn"
    else:
        verdict = "fail"

    # Collection-level bounds are reported but do not enter the weighted score --
    # they are an order-of-magnitude sanity check, not a quality measure.
    collection = schema["collection"]
    count_ok = collection["min_features"] <= len(features) <= collection["max_features"]

    return {
        "score": round(score, 6),
        "verdict": verdict,
        "n_features": len(features),
        "feature_count_in_expected_range": count_ok,
        "rule_scores": {k: round(v, 6) for k, v in sorted(rule_scores.items())},
        "failures": failures,
    }


def log_conformance(report: dict[str, Any], schema: dict) -> None:
    """Log a conformance report at a level matching its verdict."""
    thresholds = schema["scoring"]["thresholds"]
    verdict = report["verdict"]
    level = {"pass": logging.INFO, "warn": logging.WARNING}.get(verdict, logging.ERROR)

    logger.log(
        level,
        "Schema conformance: %.6f (%s) over %d features [pass>=%.2f warn>=%.2f]",
        report["score"], verdict.upper(), report["n_features"],
        thresholds["pass"], thresholds["warn"],
    )

    # Any imperfect rule is always surfaced, whatever the aggregate -- an
    # aggregate can hide a small systematic fault behind many passing features.
    for name, value in report["rule_scores"].items():
        if value < 1.0:
            examples = ", ".join(report["failures"].get(name, [])) or "n/a"
            logger.log(level, "  rule %-26s %.6f  e.g. %s", name, value, examples)

    if not report["feature_count_in_expected_range"]:
        logger.warning(
            "  feature count %d is outside the expected range in the schema",
            report["n_features"],
        )


def compare_to_reference(
    extracted: list[Feature],
    reference: list[Feature],
    schema: dict,
) -> dict[str, Any]:
    """Compare extracted features against the reference file.

    Comparison runs on the intersection of properties only. The extraction
    source carries a ``resolution`` property that the reference lacks
    (docs/discrepancies.md E2), so a whole-record equality check would report a
    total mismatch on a perfectly correct extraction.
    """
    cfg = schema["comparison"]
    key = cfg["key"]
    # Honour the declared exclusions rather than relying on compare_properties
    # happening to omit them: dead config that merely describes intent is
    # indistinguishable from a check that does not run.
    excluded = set(cfg.get("extraction_only_properties", []))
    compare_props = [p for p in cfg["compare_properties"] if p not in excluded]
    tolerance = float(cfg["coordinate_tolerance_deg"])

    def index_of(features: list[Feature]) -> dict[str, Feature]:
        return {_props(f).get(key): f for f in features}

    got, want = index_of(extracted), index_of(reference)
    got_keys, want_keys = set(got), set(want)

    missing = sorted(want_keys - got_keys)
    extra = sorted(got_keys - want_keys)
    common = want_keys & got_keys

    property_mismatches: list[str] = []
    geometry_mismatches: list[str] = []
    exact_geometry_matches = 0

    for k in common:
        gp, wp = _props(got[k]), _props(want[k])
        for prop in compare_props:
            a, b = gp.get(prop), wp.get(prop)
            if isinstance(a, float) and isinstance(b, float):
                if abs(a - b) > tolerance:
                    property_mismatches.append(k)
                    break
            elif a != b:
                property_mismatches.append(k)
                break

        if cfg.get("compare_geometry"):
            ga, gb = _ring(got[k]), _ring(want[k])
            if ga == gb:
                exact_geometry_matches += 1
            elif len(ga) != len(gb) or any(
                abs(p[0] - q[0]) > tolerance or abs(p[1] - q[1]) > tolerance
                for p, q in zip(ga, gb)
            ):
                geometry_mismatches.append(k)

    passed = not missing and not extra and not property_mismatches and not geometry_mismatches

    return {
        "passed": passed,
        "n_extracted": len(extracted),
        "n_reference": len(reference),
        "n_common": len(common),
        "n_missing_from_extraction": len(missing),
        "n_extra_in_extraction": len(extra),
        "n_property_mismatches": len(property_mismatches),
        "n_geometry_mismatches": len(geometry_mismatches),
        "n_geometry_exact_matches": exact_geometry_matches,
        "examples": {
            "missing": missing[:5],
            "extra": extra[:5],
            "property_mismatches": property_mismatches[:5],
            "geometry_mismatches": geometry_mismatches[:5],
        },
    }
