# Design Decisions

Decisions that are not self-evident from the code, recorded because the challenge warns that
interview follow-ups "might be at a very detailed level" about the choices made here.

Status: **PROPOSED** - awaiting sign-off. Nothing below has been implemented.

---

## 1. Resolving points that fall in two or more hexagons

### The problem

H3 cells tile the plane without overlap *in exact arithmetic*. Once they are serialised as
GeoJSON polygons at finite floating-point precision, two failure modes appear:

1. **Shared boundaries.** A point lying exactly on an edge is geometrically inside **two**
   hexagons, and one sitting on a vertex is inside **three**.
2. **Slivers.** If the vertices of adjacent cells are not bit-identical after rounding, the
   seams produce microscopic overlaps (a point matches 2+ cells) or gaps (a point matches 0).

Both are made materially worse by low-precision coordinates. Service-request latitude and
longitude are frequently rounded or snapped to an address or block centroid, so ties are
expected to be **far more common than random chance would suggest** - coordinates rounded to,
say, 4 decimal places land on a sparse lattice that repeatedly intersects the same edges.

Left unhandled, a one-to-many join silently **duplicates service requests**, inflating every
downstream count. This is exactly the multiple-results problem to prevent.

### Proposed rule

Applied in strict order. Every record resolves to exactly one outcome.

| Step | Predicate | Outcome |
|---|---|---|
| **R0** | `Latitude`/`Longitude` empty | Index `0`. Not an error - mandated by the spec. Excluded from the error rate. |
| **R1** | Point **strictly within** polygon interior (`within`) | Unique by construction. Expected to cover the overwhelming majority. |
| **R2** | Unmatched by R1, retry with `intersects` (boundary inclusive), exactly 1 candidate | Assign it. Sliver gap closed. |
| **R3** | R2 yields **2 or more** candidates | Tie-break, below. |
| **R4** | 0 candidates after R2 | **Join failure.** Distinct from R0 - see `docs/discrepancies.md` B4. Feeds the error threshold. |

**R3 tie-break, in order:**

1. **Nearest cell centroid** (great-circle distance from point to candidate centroid).
2. If still tied within `1e-9`, the **lexicographically smallest H3 index string**.

**Why nearest-centroid.** It is not arbitrary. H3's own `latLngToCell` assigns a point to the
cell whose centre is nearest in the icosahedral gnomonic projection, so nearest-centroid is the
closest available approximation to H3's canonical answer - meaning the tie-break agrees with the
library we validate against, rather than fighting it. Criterion 2 exists purely to guarantee
determinism: the result must not depend on GeoJSON feature order, thread scheduling, or platform
floating-point behaviour. The same input must always produce the same output.

### Recording the occurrences - a proposal beyond logging

You asked for these to appear in the logging, or for a better suggestion. **Recommendation: do
both, with logs carrying the summary and a side-car dataset carrying the detail.**

Logging alone is the wrong primary home for this, for three reasons:

- At this row count, one log line per ambiguous record is itself a performance problem and will
  bury the signal.
- Logs are rotated, truncated, and thrown away. This is *evidence about data quality* and
  deserves to outlive a single run.
- Log text is not queryable. Nobody can answer "are the ties clustered along one seam?" by
  grepping.

Proposed split:

**1. Logs - summary only.** One `WARNING` per run:

```
Ambiguous hex assignment: 1,234 records matched >1 polygon (0.14% of geolocated).
Resolved by nearest-centroid (1,230) / index-order (4).
Detail: data/quality/ambiguous_hex_assignments.csv
```

**2. Side-car dataset** - `data/quality/ambiguous_hex_assignments.csv`, one row per ambiguous
record:

| Column | Purpose |
|---|---|
| `notification_id` | Trace back to source |
| `latitude`, `longitude` | Reproduce the case |
| `n_candidates` | 2, 3, or a sliver pathology |
| `candidate_indices` | Pipe-delimited, sorted |
| `chosen_index` | The assignment made |
| `rule_applied` | `nearest_centroid` or `index_order` |
| `distance_to_chosen_m` | How close the call was |
| `runner_up_index`, `margin_m` | **The key diagnostic.** A sub-metre margin means a genuine coin-flip; a large margin means something else is wrong. |

**3. Run manifest** - `data/quality/join_summary.json`: counts per outcome class R0-R4, the
error rate, the threshold, the pass/fail verdict, timings, and library versions. This is what a
CI job or a future regression test asserts against.

Why this is better: it is diffable in git, so a change in ambiguity between runs shows up in a
pull request; it is queryable; and `margin_m` turns "we had some ties" into a *testable claim*
about whether the tie-break ever mattered.

### The independent cross-check

We compute each index **twice**, by two independent routes:

- **Geometric join** against the supplied polygons - what Section 2 literally asks for, and the
  only route that can surface coverage gaps and boundary pathologies.
- **`h3.latlng_to_cell(lat, lon, 8)`** - the library's own answer, O(1) per point, with no
  boundary ambiguity by construction.

Reporting the agreement rate between them is a strong validation artifact, and every
disagreement is by definition an interesting record. **Open question for you:** if the two
routes disagree, which wins? Recommendation is the H3 library, since `sr_hex.csv.gz` was
almost certainly generated with it and it is our accuracy benchmark - but this should be decided
by the measured agreement rate rather than assumed now.

---

## 2. The join error threshold

The challenge requires a threshold "above which the script will error out", and asks us to
motivate it. An arbitrary round number is not a motivation.

### Classify before thresholding

Lumping all failures into one rate makes the threshold meaningless, because the classes have
completely different expected rates and severities:

| Class | Meaning | Expected | Counts toward threshold? |
|---|---|---|---|
| **A** | Missing lat/lon, index `0` | Common and legitimate | **No** - mandated by the spec |
| **B** | Valid, in-bounds coordinates, no hexagon matched | Near zero | **Yes** - the primary signal |
| **C** | Valid coordinates outside the CoCT boundary | Small | Reported separately |
| **D** | Malformed or inverted coordinates | Should be zero | **Yes** - fail fast |

### Proposed calibration

Set the hard-fail threshold on **class B**, calibrated empirically rather than guessed:

1. Measure the class-A rate in `sr_hex.csv.gz`. That is the vendor's own baseline and tells us
   what "normal" looks like.
2. Run the join once, observe the class-B baseline, and set the threshold to
   `max(0.5%, 3 x observed_baseline)`, recording the observed figure in the config.

**Motivation.** The threshold has to satisfy two opposing constraints. It must be loose enough
not to fail on known-good data - otherwise the pipeline cries wolf and gets ignored. It must be
tight enough to catch a regression. Note that the *catastrophic* failure modes are easy: a
latitude/longitude swap, a CRS error, or a truncated polygon file each drive class B toward
**100%**, so any threshold below about 50% catches them. The threshold's real job is therefore
detecting **subtle** regressions - a handful of dropped polygons, a slightly shifted boundary -
which is precisely why it is pinned to a multiple of the observed baseline rather than to a
round number chosen in advance.

The `3x` multiplier absorbs legitimate run-to-run variation while still tripping on a doubling
of the failure rate. The `0.5%` floor prevents an absurdly tight threshold if the observed
baseline happens to be zero.

**Class D gets a threshold of zero**: any malformed coordinate that survives to the join stage
means the upstream validation gate failed, which is a code defect, not a data problem.

---

## 3. Resolved questions

Decided 2026-09-20.

| # | Question | Decision |
|---|---|---|
| 1 | `sr_hex_truncated.csv` integrity check | **Descoped.** Section 3 is out of scope and the file is not a dependency of Sections 1-2. |
| 2 | Arbiter where the two methods disagree | **Deferred, deliberately.** Run both methods over the full dataset, compare cell IDs, and categorise the disagreements first. Picking a winner before seeing the failure modes would assume the answer. See section 4. |
| 3 | Coverage gaps | **Report, do not fail.** Coverage is a property of the supplied data, not of our pipeline - failing on it would conflate a finding with a defect. |
| 4 | AI correction example | Confirmed as the candidate's to write. See `AI_log.md`. |

Still open, and only the data can settle it:

- **B4 / B5 encoding.** When coordinates are present but no hexagon matches, do we emit `0`
  (the spec's only defined sentinel, and probably what `sr_hex.csv.gz` does) or a distinct
  value preserving the semantic difference? Plan: emit whatever validates against
  `sr_hex.csv.gz`, and carry the distinction in the quality side-car instead.

---

## 4. Dual-method comparison

Both methods run over the **full** dataset and their assigned cell IDs are compared row by row:

- **Method G (geometric)** - spatial join against the supplied polygons, using the R0-R4 rule
  in section 1.
- **Method H (library)** - `h3.latlng_to_cell(lat, lon, 8)`.

This is a deliverable in its own right, not merely a validation step. Output:
`docs/method_comparison.md` plus `data/quality/method_disagreements.csv`.

### Disagreement categories

Every disagreeing row is classified into exactly one bucket. The categories are hypotheses to
confirm or discard, not predictions:

| Category | Signature | Interpretation |
|---|---|---|
| **C1 - boundary tie** | G's chosen cell was ambiguous (R3 fired) and H picked a candidate G rejected | Tie-break disagreement. Benign if `margin_m` is small; the two rules simply broke a near-coin-flip differently. |
| **C2 - coverage gap** | H returns a valid cell, G returns none (R4) | The point is inside H3's tiling but the supplied polygon file has no such cell. **Direct evidence for the coverage question.** |
| **C3 - out of tiling** | G matches a polygon, H's cell is absent from the supplied file | The polygon file extends beyond, or disagrees with, the H3 cell set it claims to represent. |
| **C4 - adjacent cell** | Both return valid cells that are H3 neighbours | Precision or projection drift near a seam. Quantify by distance to the shared edge. |
| **C5 - non-adjacent** | Both return valid cells that are **not** neighbours | **The alarming one.** Points to axis inversion, a CRS mismatch, or a corrupt polygon - not a rounding artifact. Any non-zero count here is a stop-and-investigate signal. |

For each category: record the count, the share of geolocated records, and worked examples.
Then cross-check both against `sr_hex.csv.gz` - whichever method agrees with the reference more
often is the empirically better arbiter, which is the evidence needed to settle question 2
properly.

**Expected shape of the result** (to be confirmed, not assumed): C1 and C4 dominate, C2 is
small but non-zero, C5 is zero. A large C5 means something is wrong with our pipeline, not with
the data.
