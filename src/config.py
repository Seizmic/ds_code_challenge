"""Central configuration.

Every path, endpoint and tunable lives here so that no other module hard-codes a
literal. The schema contract itself lives in ``config/hex_schema.yaml`` and is
loaded on demand -- see :func:`load_hex_schema`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# --- Paths -------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
PROCESSED_DIR = DATA_DIR / "processed"
QUALITY_DIR = DATA_DIR / "quality"

HEX_SCHEMA_PATH = CONFIG_DIR / "hex_schema.yaml"
SR_SCHEMA_PATH = CONFIG_DIR / "sr_schema.yaml"

# --- Output filenames --------------------------------------------------------
# Names only, resolved against the current data directory at call time rather
# than frozen at import. Held here because this module's docstring promises that
# no other module hard-codes a path literal, and six of these previously lived
# in extract_hex and transform_join, which made that promise false.
OUTPUT_FILES = {
    "hex_extracted": "city-hex-polygons-8-extracted.geojson",
    "sr_hex": "sr_hex.csv.gz",
}
QUALITY_FILES = {
    "run_manifest": "run_manifest.json",
    "ambiguous": "ambiguous_hex_assignments.csv",
    "disagreements": "method_disagreements.csv",
    "join_summary": "join_summary.json",
}
RESULTS_FILE = PROJECT_ROOT / "docs" / "results.md"


def set_data_dir(path: Path) -> None:
    """Redirect every data directory beneath ``path``.

    Exists for one concrete reason rather than as general configurability: both
    ``--join-method`` settings write to the same output filename, so comparing
    the geometric and library results side by side is otherwise impossible
    without one clobbering the other. It is also what lets the pipeline run
    from a read-only checkout.
    """
    global DATA_DIR, RAW_DIR, INTERIM_DIR, PROCESSED_DIR, QUALITY_DIR
    DATA_DIR = Path(path)
    RAW_DIR = DATA_DIR / "raw"
    INTERIM_DIR = DATA_DIR / "interim"
    PROCESSED_DIR = DATA_DIR / "processed"
    QUALITY_DIR = DATA_DIR / "quality"


def processed_path(key: str) -> Path:
    """Resolve an output file under the current processed directory."""
    return PROCESSED_DIR / OUTPUT_FILES[key]


def quality_path(key: str) -> Path:
    """Resolve a quality artifact under the current quality directory."""
    return QUALITY_DIR / QUALITY_FILES[key]

# --- S3 ----------------------------------------------------------------------

AWS_REGION = "af-south-1"
S3_BUCKET = "cct-ds-code-challenge-input-data"
S3_ENDPOINT = f"https://{S3_BUCKET}.s3.{AWS_REGION}.amazonaws.com"

# The challenge supplies credentials publicly so that the AWS client libraries
# work out of the box. See docs/discrepancies.md B1 for why using these rather
# than a personal AWS profile is load-bearing, not incidental.
CREDENTIALS_URL = f"{S3_ENDPOINT}/ds_code_challenge_creds.json"

# Object keys
KEY_HEX_8_10 = "city-hex-polygons-8-10.geojson"
KEY_HEX_8 = "city-hex-polygons-8.geojson"
KEY_SR_HEX = "sr_hex.csv.gz"
KEY_SR = "sr.csv.gz"

# --- Section 1: extraction ---------------------------------------------------

TARGET_RESOLUTION = 8

# S3 Select over a single JSON document.
#
# The ``[*].features[*]`` path expression is the critical detail: it makes S3
# Select stream one record per GeoJSON feature (~500 bytes) instead of treating
# the 108 MB file as one record, which would breach the 1 MB record ceiling and
# fail. See docs/discrepancies.md E5.
S3_SELECT_EXPRESSION = (
    "SELECT s.properties, s.geometry "
    "FROM S3Object[*].features[*] s "
    f"WHERE s.properties.resolution = {TARGET_RESOLUTION}"
)

# --- Section 2: spatial join -------------------------------------------------

# Bounding box for the City of Cape Town, used to classify coordinates and to
# detect axis inversion. Latitude and longitude ranges here are disjoint and
# opposite in sign, which is what makes inversion trivially detectable.
#
# Originally set from general knowledge, then VALIDATED against the supplied
# polygons (2026-09-20). The 3,832 hexagons span lon 18.2979-19.0126 and lat
# -34.3649 to -33.4640, so these bounds contain the City's own definition of
# its extent with 0.035-0.098 degrees of margin on every side.
#
# Deliberately kept loose rather than tightened to the measured extent: this is
# a sanity gate for detecting inversion and gross error, and a point just
# outside hexagon coverage should be classed VALID and then fail the join as
# R4 (a coverage finding) rather than be dismissed as out-of-bounds. Three real
# records do exactly that -- see docs/discrepancies.md F3.
CCT_BOUNDS = {
    "lon_min": 18.20,
    "lon_max": 19.10,
    "lat_min": -34.40,
    "lat_max": -33.40,
}

# Which method produces the published h3_level8_index.
#
#   "geometric" -- spatial join against city-hex-polygons-8.geojson. This is
#                  what Section 2 literally asks for, and the only route that
#                  can surface coverage gaps in the supplied polygons.
#   "library"   -- h3.latlng_to_cell directly.
#
# Measured on the full dataset, geometric reaches 99.99692% exact agreement
# with sr_hex.csv.gz and library reaches 100%: all 29 differences resolve in
# the library's favour, which is evidence sr_hex was generated with the library
# rather than a geometric join. Geometric is kept as the default anyway,
# because matching the reference by switching to the method that produced it
# would demonstrate nothing about the polygons. The 29 are documented instead.
JOIN_METHOD = "geometric"
JOIN_METHODS = ("geometric", "library")

# Sentinel for records with no geolocation, mandated by the challenge spec.
# NOTE: emitted as a *string*, because the surrounding column holds 15-character
# H3 index strings and a mixed-type column coerces unpredictably. Confirmed
# against sr_hex.csv.gz at runtime -- see docs/discrepancies.md B5.
NO_GEOLOCATION_INDEX = "0"

# Minimum acceptable exact-match rate against sr_hex.csv.gz.
#
# Deliberately a threshold rather than "zero disagreements". The geometric
# route is the documented default and is KNOWN to differ from the reference on
# 29 of 941,634 records, because sr_hex.csv.gz was generated with the H3
# library (docs/results.md). Demanding perfection would mark an outcome we
# chose, understand and documented as a failure, and would contradict the
# non-binary scoring used everywhere else in this project.
#
# 0.999 sits far above the measured 0.99996920 while still catching any real
# regression: a coordinate swap or a truncated polygon file would drop the
# match rate by orders of magnitude, nowhere near this band.
REFERENCE_MATCH_THRESHOLD = 0.999

# Join error thresholds. See docs/decisions.md section 2 for the motivation;
# the class-B figure is calibrated against the observed baseline on first run
# rather than chosen a priori.
JOIN_ERROR_THRESHOLDS = {
    "class_b_no_hex_match": 0.005,   # valid in-bounds coords, no hexagon matched
    "class_d_malformed": 0.0,        # malformed coords reaching the join = code defect
}

# --- HTTP --------------------------------------------------------------------

HTTP_TIMEOUT_SECONDS = 30
HTTP_MAX_RETRIES = 3
HTTP_BACKOFF_FACTOR = 1.5


def load_hex_schema() -> dict[str, Any]:
    """Load the hexagon schema contract.

    Kept in YAML rather than Python so the schema is inspectable and editable
    without touching code, which is what Section 1 asks for when it requires the
    desired schema in "a standalone configuration or documentation file".
    """
    with HEX_SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def load_sr_schema() -> dict[str, Any]:
    """Load the service request data contract."""
    with SR_SCHEMA_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def ensure_directories() -> None:
    """Create the data directories if absent.

    A fresh clone carries the directory layout via ``.gitkeep`` files, but this
    makes the pipeline robust to those being pruned, and to being run from a
    zip export rather than a clone.
    """
    for directory in (RAW_DIR, INTERIM_DIR, PROCESSED_DIR, QUALITY_DIR):
        directory.mkdir(parents=True, exist_ok=True)
