"""Data contract validation for the service request dataset.

Scored the same way as the hexagon contract: each rule contributes the fraction
of rows satisfying it, aggregated as a weighted mean against pass/warn/fail
bands. Rules come from ``config/sr_schema.yaml``, not from code.

Structural checks run first and are fatal rather than scored. If the columns
are not what we expect, every row-level score is measuring the wrong thing and
a high aggregate would be actively misleading.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)


class SchemaViolationError(ValueError):
    """Raised when the input does not satisfy the structural contract."""


def _is_blank(series: pd.Series) -> pd.Series:
    """Blank meaning absent: empty, whitespace, or a textual null spelling."""
    text = series.astype("string").fillna("").str.strip().str.lower()
    return text.isin({"", "nan", "none", "null", "na", "n/a"})


def check_structure(df: pd.DataFrame, schema: dict[str, Any]) -> None:
    """Validate the structural contract. Raises on violation."""
    structure = schema["structure"]

    missing = [c for c in structure["required_columns"] if c not in df.columns]
    if missing:
        raise SchemaViolationError(
            f"Input is missing required column(s): {missing}. "
            f"Present columns: {list(df.columns)}"
        )

    if not structure.get("allow_extra_columns", True):
        extra = [c for c in df.columns if c not in structure["required_columns"]]
        if extra:
            raise SchemaViolationError(f"Unexpected column(s): {extra}")

    if len(df) < structure.get("min_rows", 0):
        raise SchemaViolationError(
            f"Input has {len(df)} rows, below the contract minimum of "
            f"{structure['min_rows']}. Refusing to proceed: a truncated input "
            "would produce confident-looking but meaningless results."
        )

    logger.info("Structural contract satisfied: %d columns, %d rows",
                len(df.columns), len(df))


def score(df: pd.DataFrame, schema: dict[str, Any]) -> dict[str, Any]:
    """Score the dataset against the contract. Returns a conformance report."""
    check_structure(df, schema)

    n = len(df)
    columns = schema["columns"]
    rule_scores: dict[str, float] = {}
    failures: dict[str, list[str]] = {}
    max_examples = schema["scoring"].get("max_examples_per_rule", 5)

    def record(name: str, ok: pd.Series) -> None:
        ok = ok.fillna(False).astype(bool)
        rule_scores[name] = float(ok.sum()) / n if n else 0.0
        if not ok.all():
            bad = df.loc[~ok]
            ident = (
                bad["notification_number"].astype("string").head(max_examples).tolist()
                if "notification_number" in bad.columns
                else [str(i) for i in bad.index[:max_examples]]
            )
            failures[name] = ident

    # --- Identity ------------------------------------------------------------
    ident_spec = columns["notification_number"]
    ident = df["notification_number"].astype("string")
    record("notification_number_present", ~_is_blank(ident))
    record(
        "notification_number_pattern",
        ident.str.fullmatch(ident_spec["pattern"]).fillna(False),
    )
    record("notification_number_unique", ~ident.duplicated(keep=False))

    # --- Spatial -------------------------------------------------------------
    lat_blank, lon_blank = _is_blank(df["latitude"]), _is_blank(df["longitude"])
    lat = pd.to_numeric(df["latitude"], errors="coerce")
    lon = pd.to_numeric(df["longitude"], errors="coerce")

    # A blank coordinate is legitimately absent, so it satisfies a range rule;
    # only a populated out-of-range value is a violation.
    record(
        "latitude_in_range",
        lat_blank | lat.between(columns["latitude"]["min"], columns["latitude"]["max"]),
    )
    record(
        "longitude_in_range",
        lon_blank | lon.between(columns["longitude"]["min"], columns["longitude"]["max"]),
    )
    record("coordinate_pair_completeness", lat_blank == lon_blank)

    # Axis inversion, named explicitly. The range rules above already reject a
    # swapped pair, but they report it as "longitude out of range", which sends
    # the reader looking for a geocoding fault rather than a transposed column.
    # Detectable because Cape Town's ranges are disjoint and opposite in sign.
    lat_spec, lon_spec = columns["latitude"], columns["longitude"]
    swapped = (
        lat.between(lon_spec["min"], lon_spec["max"])
        & lon.between(lat_spec["min"], lat_spec["max"])
    )
    record("coordinate_axis_order", ~(swapped & ~lat_blank & ~lon_blank))

    # --- Temporal ------------------------------------------------------------
    created = pd.to_datetime(df["creation_timestamp"], errors="coerce", utc=True)
    completed = pd.to_datetime(df["completion_timestamp"], errors="coerce", utc=True)

    record("creation_timestamp_parseable", created.notna())
    spec = columns["creation_timestamp"]
    lo = pd.Timestamp(spec["min"], tz="UTC")
    hi = pd.Timestamp(spec["max"], tz="UTC")
    record("creation_timestamp_in_range", created.isna() | created.between(lo, hi))

    # Only comparable where both are present. Split by magnitude: sub-hour
    # inversions are clock skew between two recording systems; gross ones mean
    # swapped columns or a timezone fault and are a different problem entirely.
    both = created.notna() & completed.notna()
    tolerance = pd.Timedelta(
        seconds=schema["consistency"]["completion_after_creation"][
            "clock_skew_tolerance_seconds"
        ]
    )
    inverted = both & (completed < created)
    gross = inverted & ((created - completed) > tolerance)

    record("completion_after_creation", ~inverted)
    record("completion_after_creation_gross", ~gross)

    # --- Categorical completeness -------------------------------------------
    for column, rule in (
        ("directorate", "directorate_populated"),
        ("department", "department_populated"),
        ("official_suburb", "official_suburb_populated"),
    ):
        record(rule, ~_is_blank(df[column]))

    # --- Aggregate -----------------------------------------------------------
    weights = schema["scoring"]["weights"]
    total = sum(weights.get(name, 0.0) for name in rule_scores)
    if total == 0:
        raise ValueError("Schema defines no weights for any active rule")
    aggregate = sum(rule_scores[n_] * weights.get(n_, 0.0) for n_ in rule_scores) / total

    thresholds = schema["scoring"]["thresholds"]
    if aggregate >= thresholds["pass"]:
        verdict = "pass"
    elif aggregate >= thresholds["warn"]:
        verdict = "warn"
    else:
        verdict = "fail"

    # --- Hard consistency limits --------------------------------------------
    # Scored rules can be diluted by the weighted mean; these are absolute and
    # are checked independently of the aggregate.
    violations: dict[str, dict[str, float]] = {}

    pair_limit = schema["consistency"]["coordinate_pair_completeness"][
        "max_violation_fraction"
    ]
    pair_rate = 1.0 - rule_scores["coordinate_pair_completeness"]
    if pair_rate > pair_limit:
        violations["coordinate_pair_completeness"] = {
            "rate": pair_rate, "limit": pair_limit
        }

    axis_limit = schema["consistency"]["coordinate_axis_order"]["max_violation_fraction"]
    axis_rate = 1.0 - rule_scores["coordinate_axis_order"]
    if axis_rate > axis_limit:
        violations["coordinate_axis_order"] = {"rate": axis_rate, "limit": axis_limit}

    temporal = schema["consistency"]["completion_after_creation"]
    minor_rate = 1.0 - rule_scores["completion_after_creation"]
    gross_rate = 1.0 - rule_scores["completion_after_creation_gross"]
    if minor_rate > temporal["max_minor_violation_fraction"]:
        violations["completion_before_creation_minor"] = {
            "rate": minor_rate, "limit": temporal["max_minor_violation_fraction"]
        }
    if gross_rate > temporal["max_gross_violation_fraction"]:
        violations["completion_before_creation_gross"] = {
            "rate": gross_rate, "limit": temporal["max_gross_violation_fraction"]
        }

    # Per-column null-rate ceilings. Without these, a column going entirely
    # empty is diluted by the weighted mean and passes unnoticed.
    for column, spec in columns.items():
        ceiling = spec.get("max_null_fraction")
        if ceiling is None or column not in df.columns:
            continue
        null_rate = float(_is_blank(df[column]).sum()) / n if n else 0.0
        if null_rate > ceiling:
            violations[f"{column}_null_rate"] = {"rate": null_rate, "limit": ceiling}

    dup_rate = 1.0 - rule_scores["notification_number_unique"]
    dup_limit = schema["consistency"]["duplicate_notification_number"]["max_violation_fraction"]
    if dup_rate > dup_limit:
        violations["duplicate_notification_number"] = {"rate": dup_rate, "limit": dup_limit}

    return {
        "score": round(aggregate, 6),
        "verdict": verdict,
        "n_rows": n,
        "rule_scores": {k: round(v, 6) for k, v in sorted(rule_scores.items())},
        "failures": failures,
        "consistency_violations": violations,
    }


def log_report(report: dict[str, Any], schema: dict[str, Any]) -> None:
    """Log a conformance report at a level matching its verdict."""
    thresholds = schema["scoring"]["thresholds"]
    verdict = report["verdict"]
    level = {"pass": logging.INFO, "warn": logging.WARNING}.get(verdict, logging.ERROR)

    logger.log(
        level,
        "Service request data conformance: %.6f (%s) over %d rows "
        "[pass>=%.2f warn>=%.2f]",
        report["score"], verdict.upper(), report["n_rows"],
        thresholds["pass"], thresholds["warn"],
    )

    for name, value in report["rule_scores"].items():
        if value < 1.0:
            examples = ", ".join(report["failures"].get(name, [])) or "n/a"
            logger.log(level, "  rule %-32s %.6f  e.g. %s", name, value, examples)

    for name, detail in report["consistency_violations"].items():
        logger.error(
            "  CONSISTENCY VIOLATION %s: %.6f exceeds the limit of %.6f",
            name, detail["rate"], detail["limit"],
        )


def enforce(report: dict[str, Any], schema: dict[str, Any]) -> None:
    """Fail the pipeline on a failing verdict or a consistency violation."""
    if "coordinate_axis_order" in report["consistency_violations"]:
        rate = report["consistency_violations"]["coordinate_axis_order"]["rate"]
        raise SchemaViolationError(
            f"{rate:.2%} of records have inverted coordinates - latitude and "
            "longitude appear transposed. Refusing to proceed: an axis swap "
            "produces a join that matches almost nothing, which reads as a "
            "coverage problem rather than a coordinate one."
        )
    if report["consistency_violations"]:
        raise SchemaViolationError(
            "Cross-column consistency violated: "
            f"{list(report['consistency_violations'])}. These indicate the input "
            "is internally incoherent, which silently corrupts the join rather "
            "than failing it. See the log for rates and examples."
        )
    if report["verdict"] == "fail":
        raise SchemaViolationError(
            f"Service request conformance {report['score']:.6f} is below the "
            f"failure threshold {schema['scoring']['thresholds']['warn']}."
        )
