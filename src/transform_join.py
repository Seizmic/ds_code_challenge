"""Section 2: assign each service request to exactly one H3 resolution-8 hexagon.

Two routes are computed over the full dataset and compared:

* **Method G (geometric)** -- spatial join against the supplied polygons, using
  the R0-R4 rule documented in ``docs/decisions.md``.
* **Method H (library)** -- ``h3.latlng_to_cell``, which is O(1) per point and
  has no boundary ambiguity by construction.

Method G is primary because it is what the challenge asks for and it is the only
route that can surface coverage gaps in the supplied polygons. Method H is an
independent oracle; the disagreements between them are a deliverable in their
own right.
"""

from __future__ import annotations

import logging
from typing import Any

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
from shapely.geometry import Polygon

from src import config, quality_checks
from src.logging_setup import MANIFEST, timed
from src.quality_checks import CoordClass

logger = logging.getLogger(__name__)

WGS84 = "EPSG:4326"

# Outcome classes for the assignment rule -- see docs/decisions.md section 1.
RULE_R0_NO_GEOLOCATION = "R0_no_geolocation"
RULE_R1_INTERIOR = "R1_interior"
RULE_R2_BOUNDARY_UNIQUE = "R2_boundary_unique"
RULE_R3_TIEBREAK = "R3_tiebreak"
RULE_R4_NO_MATCH = "R4_no_match"
RULE_INVALID_COORDS = "invalid_coordinates"


def hexes_to_geodataframe(features: list[dict[str, Any]]) -> gpd.GeoDataFrame:
    """Build a GeoDataFrame of hexagons from GeoJSON features."""
    records = []
    geometries = []
    for feature in features:
        props = feature["properties"]
        records.append({
            "h3_index": props["index"],
            "centroid_lat": props["centroid_lat"],
            "centroid_lon": props["centroid_lon"],
        })
        geometries.append(Polygon(feature["geometry"]["coordinates"][0]))
    return gpd.GeoDataFrame(records, geometry=geometries, crs=WGS84)


def assign_hexagons_geometric(
    points: pd.DataFrame,
    hexes: gpd.GeoDataFrame,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
) -> pd.DataFrame:
    """Assign each *unique* coordinate pair to exactly one hexagon.

    Expects a frame of distinct coordinate pairs with numeric lat/lon columns.
    Returns one row per input row with ``h3_index``, ``rule``, and tie-break
    diagnostics.

    The three-step structure exists because H3 polygons share edges exactly:
    a point lying on a shared edge is geometrically inside two hexagons, and one
    on a vertex is inside three. Using ``within`` first keeps the unambiguous
    interior case clean and unique, and pushes only genuine boundary cases into
    the more expensive tie-break path.
    """
    geometry = gpd.points_from_xy(points[lon_col], points[lat_col], crs=WGS84)
    points_gdf = gpd.GeoDataFrame(points.copy(), geometry=geometry, crs=WGS84)

    result = pd.DataFrame(
        {"h3_index": pd.Series(pd.NA, index=points.index, dtype="object"),
         "rule": pd.Series(pd.NA, index=points.index, dtype="object"),
         "n_candidates": 0,
         "candidate_indices": pd.Series(pd.NA, index=points.index, dtype="object"),
         "runner_up_index": pd.Series(pd.NA, index=points.index, dtype="object"),
         "margin_m": np.nan},
        index=points.index,
    )

    # --- R1: strict interior ---------------------------------------------------
    interior = gpd.sjoin(
        points_gdf, hexes[["h3_index", "geometry"]], how="inner", predicate="within"
    )
    # A point cannot be strictly inside two hexagons, but guard anyway: if the
    # source polygons ever overlap, we want that visible rather than silently
    # producing duplicate service requests.
    interior_counts = interior.index.value_counts()
    overlapping = interior_counts[interior_counts > 1].index
    if len(overlapping):
        logger.warning(
            "%d point(s) fell strictly inside more than one polygon -- the "
            "supplied hexagons overlap. Routing these through the tie-break.",
            len(overlapping),
        )
        interior = interior[~interior.index.isin(overlapping)]

    result.loc[interior.index, "h3_index"] = interior["h3_index"].to_numpy()
    result.loc[interior.index, "rule"] = RULE_R1_INTERIOR
    result.loc[interior.index, "n_candidates"] = 1

    # --- R2/R3: boundary cases -------------------------------------------------
    unresolved = result.index[result["h3_index"].isna()]
    if len(unresolved):
        boundary = gpd.sjoin(
            points_gdf.loc[unresolved],
            hexes[["h3_index", "centroid_lat", "centroid_lon", "geometry"]],
            how="inner",
            predicate="intersects",
        )
        if len(boundary):
            counts = boundary.index.value_counts()

            # R2: exactly one candidate.
            single = counts[counts == 1].index
            if len(single):
                rows = boundary.loc[boundary.index.isin(single)]
                result.loc[rows.index, "h3_index"] = rows["h3_index"].to_numpy()
                result.loc[rows.index, "rule"] = RULE_R2_BOUNDARY_UNIQUE
                result.loc[rows.index, "n_candidates"] = 1

            # R3: two or more candidates -> deterministic tie-break.
            multiple = counts[counts > 1].index
            if len(multiple):
                resolved = _tiebreak(
                    boundary.loc[boundary.index.isin(multiple)],
                    points_gdf.loc[multiple],
                    lat_col, lon_col,
                )
                for column in resolved.columns:
                    result.loc[resolved.index, column] = resolved[column]

    # --- R4: no match ----------------------------------------------------------
    unmatched = result.index[result["h3_index"].isna()]
    result.loc[unmatched, "rule"] = RULE_R4_NO_MATCH
    result.loc[unmatched, "n_candidates"] = 0

    return result


def _tiebreak(
    candidates: pd.DataFrame,
    points_gdf: gpd.GeoDataFrame,
    lat_col: str,
    lon_col: str,
) -> pd.DataFrame:
    """Resolve multi-candidate points deterministically.

    Rule, in order (docs/decisions.md section 1):
      1. nearest hexagon centroid by great-circle distance;
      2. on a tie, the lexicographically smallest H3 index.

    Criterion 1 approximates what ``h3.latlng_to_cell`` itself does, so the
    tie-break agrees with the library we validate against instead of fighting
    it. Criterion 2 exists solely to make the outcome independent of feature
    ordering, thread scheduling and platform float behaviour -- the same input
    must always produce the same output.
    """
    work = candidates.copy()
    point_lat = points_gdf[lat_col].reindex(work.index).to_numpy(dtype=float)
    point_lon = points_gdf[lon_col].reindex(work.index).to_numpy(dtype=float)

    work["distance_m"] = quality_checks.haversine_metres(
        point_lat, point_lon,
        work["centroid_lat"].to_numpy(dtype=float),
        work["centroid_lon"].to_numpy(dtype=float),
    )

    # Sort so the winner is first within each point: nearest centroid, then
    # lexicographic index as the deterministic secondary key.
    work = work.sort_values(
        ["distance_m", "h3_index"], ascending=[True, True], kind="stable"
    )
    grouped = work.groupby(level=0, sort=False)

    winners = grouped.head(1)
    runners = grouped.nth(1)

    out = pd.DataFrame(index=winners.index)
    out["h3_index"] = winners["h3_index"]
    out["rule"] = RULE_R3_TIEBREAK
    out["n_candidates"] = grouped.size().reindex(winners.index).to_numpy()
    out["candidate_indices"] = (
        work.groupby(level=0, sort=False)["h3_index"]
        .apply(lambda s: "|".join(sorted(s)))
        .reindex(winners.index)
    )
    out["runner_up_index"] = runners["h3_index"].reindex(winners.index)
    out["margin_m"] = (
        runners["distance_m"].reindex(winners.index).to_numpy()
        - winners["distance_m"].to_numpy()
    )
    return out


def assign_hexagons_h3(
    points: pd.DataFrame,
    lat_col: str = "latitude",
    lon_col: str = "longitude",
    resolution: int = config.TARGET_RESOLUTION,
) -> pd.Series:
    """Method H: assign via the H3 library directly."""
    lat = points[lat_col].to_numpy(dtype=float)
    lon = points[lon_col].to_numpy(dtype=float)
    return pd.Series(
        [h3.latlng_to_cell(a, o, resolution) for a, o in zip(lat, lon)],
        index=points.index,
        dtype="object",
    )


def categorise_disagreements(
    comparison: pd.DataFrame,
    valid_hexes: set[str],
) -> pd.Series:
    """Bucket each geometric/library disagreement -- see docs/decisions.md section 4.

    Categories, in precedence order:
      C2  coverage gap       -- library returns a cell the polygon file HAS,
                                but the geometric join matched nothing: a hole
                                inside the covered area
      C2b outside coverage   -- geometric matched nothing AND the library's cell
                                is absent from the file: the point lies beyond
                                the supplied tiling altogether, rather than in a
                                gap within it
      C3  out of tiling      -- geometric matched, library's cell not in the file
      C1  boundary tie       -- the tie-break fired and picked a different candidate
      C4  adjacent cell      -- both valid and H3-adjacent (precision drift)
      C5  non-adjacent       -- both valid, not adjacent: NOT a rounding artifact

    C2 and C2b are kept apart because they mean different things operationally.
    C2 is a defect in the polygon file -- a cell that should be there is not.
    C2b is a scope question -- the request happened outside the area the file
    covers, which may be entirely legitimate.
    """
    result = pd.Series("", index=comparison.index, dtype="object")

    geo = comparison["h3_geometric"]
    lib = comparison["h3_library"]

    lib_in_file = lib.isin(valid_hexes)
    geo_missing = geo.isna() | (geo == config.NO_GEOLOCATION_INDEX)

    result[geo_missing & lib_in_file] = "C2_coverage_gap"
    result[geo_missing & (~lib_in_file)] = "C2b_outside_coverage"
    result[(~geo_missing) & (~lib_in_file)] = "C3_out_of_tiling"

    both = (~geo_missing) & lib_in_file & (result == "")
    if both.any():
        tie = both & (comparison["rule"] == RULE_R3_TIEBREAK)
        result[tie] = "C1_boundary_tie"

        rest = both & (result == "")
        if rest.any():
            adjacent = pd.Series(
                [
                    h3.are_neighbor_cells(a, b)
                    for a, b in zip(geo[rest].to_numpy(), lib[rest].to_numpy())
                ],
                index=comparison.index[rest],
            )
            result[comparison.index[rest][adjacent.to_numpy()]] = "C4_adjacent_cell"
            result[comparison.index[rest][~adjacent.to_numpy()]] = "C5_non_adjacent"

    return result


# =============================================================================
# Orchestration
# =============================================================================

OUTPUT_PATH = config.PROCESSED_DIR / "sr_hex.csv.gz"
AMBIGUOUS_PATH = config.QUALITY_DIR / "ambiguous_hex_assignments.csv"
DISAGREEMENT_PATH = config.QUALITY_DIR / "method_disagreements.csv"
JOIN_SUMMARY_PATH = config.QUALITY_DIR / "join_summary.json"

ID_COLUMN = "notification_number"


def load_service_requests(client) -> pd.DataFrame:
    """Load the un-indexed service request dataset.

    Uses ``sr.csv.gz`` deliberately, not ``sr_hex.csv.gz``: the latter already
    contains the answer, so joining against it would be circular. ``sr_hex`` is
    reserved for validation.

    ``index_col=0`` handles the unnamed pandas artifact column that ``sr.csv.gz``
    carries and ``sr_hex.csv.gz`` does not (docs/discrepancies.md B11).
    Identifiers are read as strings because they carry leading zeros that type
    inference would silently destroy, corrupting the validation join key (E4).
    """
    from src import s3_io

    path = s3_io.download_cached(client, config.KEY_SR)
    return pd.read_csv(
        path,
        index_col=0,
        dtype={ID_COLUMN: "string", "reference_number": "string",
               "latitude": "string", "longitude": "string"},
        keep_default_na=False,
        na_values=[],
        low_memory=False,
    )


def validate_against_reference(
    client, assigned: pd.Series, source: pd.DataFrame
) -> dict[str, Any]:
    """Validate our assignments against ``sr_hex.csv.gz``.

    This is the validation Section 2 asks for. The reference is joined on
    ``notification_number`` rather than compared positionally, so the result
    does not silently depend on both files being in the same row order.
    """
    from src import s3_io

    path = s3_io.download_cached(client, config.KEY_SR_HEX)
    reference = pd.read_csv(
        path,
        usecols=[ID_COLUMN, "h3_level8_index"],
        dtype="string",
        keep_default_na=False,
        na_values=[],
    )

    ours = pd.DataFrame({
        ID_COLUMN: source[ID_COLUMN].to_numpy(),
        "ours": assigned.to_numpy(),
    })

    duplicated = int(ours[ID_COLUMN].duplicated().sum())
    if duplicated:
        logger.warning(
            "%d duplicated %s value(s); validation joins on the first occurrence",
            duplicated, ID_COLUMN,
        )

    merged = ours.merge(
        reference.rename(columns={"h3_level8_index": "theirs"}),
        on=ID_COLUMN, how="left",
    )

    unmatched_key = int(merged["theirs"].isna().sum())
    comparable = merged[merged["theirs"].notna()].copy()

    # Null must be normalised to a sentinel before comparing. Comparing a
    # StringDtype column containing <NA> yields <NA> rather than False, so
    # `~agree` drops those rows from the mismatch set entirely -- they vanish
    # from the breakdown while still counting towards n_disagree.
    UNMATCHED = "<unmatched>"
    comparable["ours_cmp"] = comparable["ours"].astype("string").fillna(UNMATCHED)
    comparable["theirs_cmp"] = comparable["theirs"].astype("string")

    agree = comparable["ours_cmp"] == comparable["theirs_cmp"]
    n_agree = int(agree.sum())
    n_disagree = int(len(comparable) - n_agree)
    rate = n_agree / len(comparable) if len(comparable) else 0.0

    # Classify mismatches so a failure says *what kind* of failure it is.
    breakdown: dict[str, int] = {}
    examples: list[dict[str, str]] = []
    if n_disagree:
        bad = comparable[~agree]
        sentinel = config.NO_GEOLOCATION_INDEX
        # `ours` is null for R4 (matched no polygon). That is a distinct outcome
        # from the sentinel and must have its own bucket -- without it the
        # buckets do not sum to n_disagree and the shortfall is invisible.
        ours_null = bad["ours_cmp"] == UNMATCHED
        breakdown = {
            "ours_unmatched_theirs_indexed": int(ours_null.sum()),
            "ours_sentinel_theirs_indexed": int(
                (~ours_null & (bad["ours_cmp"] == sentinel) & (bad["theirs_cmp"] != sentinel)).sum()
            ),
            "ours_indexed_theirs_sentinel": int(
                (~ours_null & (bad["ours_cmp"] != sentinel) & (bad["theirs_cmp"] == sentinel)).sum()
            ),
            "different_index": int(
                (~ours_null & (bad["ours_cmp"] != sentinel) & (bad["theirs_cmp"] != sentinel)).sum()
            ),
        }
        assert sum(breakdown.values()) == n_disagree, (
            f"mismatch breakdown {sum(breakdown.values())} does not account for "
            f"all {n_disagree} disagreements"
        )
        examples = bad.head(10).to_dict("records")

    logger.info(
        "Reference validation against %s: %.6f%% exact match (%d of %d)",
        config.KEY_SR_HEX, rate * 100, n_agree, len(comparable),
    )
    if n_disagree:
        logger.warning("  %d record(s) disagree with the reference:", n_disagree)
        for name, count in breakdown.items():
            if count:
                logger.warning("    %-32s %d", name, count)
        for example in examples[:5]:
            logger.warning(
                "    %s: ours=%s theirs=%s",
                example[ID_COLUMN], example["ours"], example["theirs"],
            )
    if unmatched_key:
        logger.warning("  %d record(s) had no matching key in the reference", unmatched_key)

    return {
        "match_rate": rate,
        "n_agree": n_agree,
        "n_disagree": n_disagree,
        "n_unmatched_key": unmatched_key,
        "duplicated_keys": duplicated,
        "mismatch_breakdown": breakdown,
        "examples": examples[:10],
    }


def run(client=None, hex_features: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Execute Section 2 end to end."""
    import json

    from src import extract_hex, s3_io

    client = client or s3_io.make_s3_client()

    if hex_features is None:
        hex_features = extract_hex.run(client)["features"]
    hexes = hexes_to_geodataframe(hex_features)
    valid_hexes = set(hexes["h3_index"])

    with timed("section2.load_service_requests", logger):
        df = load_service_requests(client)
    logger.info("Loaded %d service requests", len(df))

    # --- Quality gate --------------------------------------------------------
    with timed("section2.coordinate_classification", logger):
        coord_class = quality_checks.classify_coordinates(df)
    summary = quality_checks.summarise(coord_class)
    quality_checks.log_summary(summary, len(df))
    MANIFEST.record_metric("section2.coordinate_classes", summary)

    if summary[str(CoordClass.INVERTED)]:
        raise ValueError(
            f"{summary[str(CoordClass.INVERTED)]} record(s) have inverted "
            "coordinates. Refusing to join: an axis swap produces a join that "
            "matches almost nothing and reads as a coverage problem."
        )

    joinable = coord_class == CoordClass.VALID
    logger.info("%d of %d records are joinable", int(joinable.sum()), len(df))

    # --- De-duplicate coordinates -------------------------------------------
    # Only distinct coordinate pairs need the spatial join; the result is then
    # broadcast back. The measured saving is reported rather than assumed.
    with timed("section2.deduplicate_coordinates", logger):
        points = df.loc[joinable, ["latitude", "longitude"]].copy()
        unique = points.drop_duplicates(
            subset=["latitude", "longitude"]
        ).reset_index(drop=True)
        unique["latitude_num"] = pd.to_numeric(unique["latitude"])
        unique["longitude_num"] = pd.to_numeric(unique["longitude"])

    ratio = len(unique) / len(points) if len(points) else 1.0
    logger.info(
        "Coordinate de-duplication: %d unique pairs from %d rows "
        "(%.1f%% unique, %.2fx less join work)",
        len(unique), len(points), ratio * 100, (1 / ratio) if ratio else 1.0,
    )
    MANIFEST.record_metric("section2.unique_coordinate_pairs", int(len(unique)))
    MANIFEST.record_metric("section2.dedup_ratio", round(ratio, 4))

    numeric = unique[["latitude_num", "longitude_num"]].rename(
        columns={"latitude_num": "latitude", "longitude_num": "longitude"}
    )

    # --- Method G: geometric join -------------------------------------------
    with timed("section2.geometric_join", logger):
        geometric = assign_hexagons_geometric(numeric, hexes)

    # --- Method H: H3 library ------------------------------------------------
    with timed("section2.h3_library_assignment", logger):
        library = assign_hexagons_h3(numeric)

    unique["h3_geometric"] = geometric["h3_index"].to_numpy()
    unique["rule"] = geometric["rule"].to_numpy()
    unique["h3_library"] = library.to_numpy()
    for column in ("n_candidates", "candidate_indices", "runner_up_index", "margin_m"):
        unique[column] = geometric[column].to_numpy()

    # --- Broadcast back to every row ----------------------------------------
    with timed("section2.broadcast_to_rows", logger):
        merged = points.merge(
            unique[["latitude", "longitude", "h3_geometric", "rule"]],
            on=["latitude", "longitude"], how="left",
        )
        merged.index = points.index

        result = pd.DataFrame(index=df.index)
        result["h3_level8_index"] = config.NO_GEOLOCATION_INDEX
        result["rule"] = RULE_R0_NO_GEOLOCATION
        result.loc[joinable, "h3_level8_index"] = merged["h3_geometric"].to_numpy()
        result.loc[joinable, "rule"] = merged["rule"].to_numpy()

        # Invalid coordinates are marked distinctly so they cannot hide inside
        # the legitimate R0 (no geolocation) bucket.
        invalid = coord_class.isin([
            CoordClass.NULL_ISLAND, CoordClass.OUT_OF_BOUNDS, CoordClass.UNPARSEABLE
        ])
        result.loc[invalid, "rule"] = RULE_INVALID_COORDS

    # --- Outcome accounting --------------------------------------------------
    rule_counts = result["rule"].value_counts().to_dict()
    MANIFEST.record_metric(
        "section2.rule_counts", {str(k): int(v) for k, v in rule_counts.items()}
    )
    logger.info("Assignment outcomes:")
    for rule, count in sorted(rule_counts.items()):
        logger.info("  %-22s %9d  (%5.2f%%)", rule, count, 100.0 * count / len(df))

    n_geolocated = int(joinable.sum())
    n_no_match = int((result["rule"] == RULE_R4_NO_MATCH).sum())
    n_invalid = int(invalid.sum())
    class_b_rate = n_no_match / n_geolocated if n_geolocated else 0.0
    class_d_rate = n_invalid / len(df) if len(df) else 0.0

    MANIFEST.record_metric("section2.class_b_no_hex_match_rate", round(class_b_rate, 8))
    MANIFEST.record_metric("section2.class_d_invalid_rate", round(class_d_rate, 8))

    # --- Side-car quality output --------------------------------------------
    ambiguous = unique[unique["rule"] == RULE_R3_TIEBREAK]
    if len(ambiguous):
        columns = ["latitude", "longitude", "n_candidates", "candidate_indices",
                   "h3_geometric", "rule", "runner_up_index", "margin_m"]
        ambiguous[columns].rename(
            columns={"h3_geometric": "chosen_index"}
        ).to_csv(AMBIGUOUS_PATH, index=False)
        logger.warning(
            "Ambiguous hex assignment: %d unique coordinate pair(s) matched more "
            "than one polygon (%.4f%% of geolocated). Resolved by nearest-centroid "
            "tie-break. Detail: %s",
            len(ambiguous), 100.0 * len(ambiguous) / max(n_geolocated, 1), AMBIGUOUS_PATH,
        )
        logger.info(
            "  tie-break margin: median %.3f m, max %.3f m",
            float(ambiguous["margin_m"].median()), float(ambiguous["margin_m"].max()),
        )
    else:
        logger.info("No ambiguous (multi-polygon) assignments occurred")
    MANIFEST.record_metric("section2.n_ambiguous_unique_pairs", int(len(ambiguous)))

    # --- Dual-method comparison ---------------------------------------------
    with timed("section2.method_comparison", logger):
        geo_filled = unique["h3_geometric"].astype("object").where(
            unique["h3_geometric"].notna(), ""
        )
        disagree = unique[geo_filled != unique["h3_library"]]
        agreement = 1.0 - (len(disagree) / len(unique) if len(unique) else 0.0)
        logger.info(
            "Method agreement (geometric vs H3 library): %.6f%% over %d unique pairs",
            agreement * 100, len(unique),
        )

        categories: dict[str, int] = {}
        if len(disagree):
            cats = categorise_disagreements(disagree, valid_hexes)
            categories = {str(k): int(v) for k, v in cats.value_counts().to_dict().items()}
            out = disagree[["latitude", "longitude", "h3_geometric", "h3_library",
                            "rule", "n_candidates", "margin_m"]].copy()
            out["category"] = cats.to_numpy()
            out.to_csv(DISAGREEMENT_PATH, index=False)
            logger.info("Disagreement categories:")
            for name, count in sorted(categories.items()):
                logger.info("  %-20s %8d", name, count)
            if categories.get("C5_non_adjacent"):
                logger.error(
                    "%d NON-ADJACENT disagreement(s). These are not rounding "
                    "artifacts -- investigate before trusting the output.",
                    categories["C5_non_adjacent"],
                )

    MANIFEST.record_metric("section2.method_agreement", round(agreement, 8))
    MANIFEST.record_metric("section2.disagreement_categories", categories)

    # --- Threshold enforcement ----------------------------------------------
    thresholds = config.JOIN_ERROR_THRESHOLDS
    b_ok = class_b_rate <= thresholds["class_b_no_hex_match"]
    d_ok = class_d_rate <= thresholds["class_d_malformed"]
    MANIFEST.record_verdict("section2.class_b_threshold", b_ok,
                            f"{class_b_rate:.8f} vs {thresholds['class_b_no_hex_match']}")
    MANIFEST.record_verdict("section2.class_d_threshold", d_ok,
                            f"{class_d_rate:.8f} vs {thresholds['class_d_malformed']}")

    JOIN_SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with JOIN_SUMMARY_PATH.open("w", encoding="utf-8") as handle:
        json.dump({
            "n_records": int(len(df)),
            "n_geolocated": n_geolocated,
            "coordinate_classes": summary,
            "rule_counts": {str(k): int(v) for k, v in rule_counts.items()},
            "class_b_no_hex_match_rate": class_b_rate,
            "class_d_invalid_rate": class_d_rate,
            "thresholds": thresholds,
            "method_agreement": agreement,
            "disagreement_categories": categories,
            "n_ambiguous_unique_pairs": int(len(ambiguous)),
        }, handle, indent=2)

    if not b_ok:
        raise ValueError(
            f"Join failure rate {class_b_rate:.4%} exceeds the threshold "
            f"{thresholds['class_b_no_hex_match']:.4%}. See {JOIN_SUMMARY_PATH}."
        )
    if not d_ok:
        raise ValueError(
            f"{n_invalid} record(s) had invalid coordinates against a threshold of "
            f"{thresholds['class_d_malformed']}. This indicates a defect in the "
            "quality gate, not a data problem."
        )

    # --- Validate against the reference dataset ------------------------------
    with timed("section2.reference_validation", logger):
        validation_report = validate_against_reference(
            client, result["h3_level8_index"], df
        )
    MANIFEST.record_metric("section2.reference_validation", validation_report)
    MANIFEST.record_verdict(
        "section2.reference_match",
        validation_report["n_disagree"] == 0,
        f"{validation_report['match_rate']:.8f} exact match",
    )

    # --- Write output --------------------------------------------------------
    with timed("section2.write_output", logger):
        output = df.copy()
        output["h3_level8_index"] = (
            result["h3_level8_index"].fillna(config.NO_GEOLOCATION_INDEX)
        )
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        output.to_csv(OUTPUT_PATH, index=False, compression="gzip")
    logger.info("Wrote %d rows to %s", len(output), OUTPUT_PATH)

    return {
        "output": output,
        "result": result,
        "unique": unique,
        "summary": summary,
        "agreement": agreement,
        "categories": categories,
        "validation": validation_report,
    }
