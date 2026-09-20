# Discrepancy & Risk Register

Audit of the brief (email) against the upstream challenge documentation
(`cityofcapetown/ds_code_challenge`, `main` @ `48907f2`, README last modified 2026-03-06).

**Governing rule:** where the email brief and the upstream README conflict, **the email brief wins.**
Where the README is *stricter* and compliance is cheap, we satisfy both.

Status key: `OPEN` needs a decision · `RESOLVED` decided · `UNVERIFIED` needs the data to confirm.

---

## A. Brief vs. upstream README

| # | Topic | Upstream README | Email brief | Resolution | Status |
|---|---|---|---|---|---|
| A1 | Scope | Six sections, role-dependent | "Complete Sections 0, 1 and 2. You do not need to attempt Sections 3 to 6." | Build Sections 0-2 only. Sections 3-6 explicitly out of scope; our README says so, so the gap reads as deliberate rather than unfinished. | RESOLVED |
| A2 | Effort | "up to 48 calendar hours" | "no more than about 8 hours" | Budget to 8 hours. This materially constrains scope - see section D. | RESOLVED |
| A3 | Deadline | Not stated | 23:59 SAST, Tue 22 Sep 2026 | Confirmed: 22 Sep 2026 *is* a Tuesday. Today is Sun 20 Sep 2026, so ~2 calendar days. | RESOLVED |
| A4 | Submission | "Clone this repository... Host your repository somewhere publicly accessible. If you're using GitHub, please use a fork" | "Fork the repository to your own GitHub account and make your fork public" | Fork. The brief is the stricter, unambiguous instruction. | RESOLVED |
| A5 | AI disclosure | `AI_log.md` logging "all of the work... including any prompts, the model used as well number of tokens" | "what you asked for, which tool, and roughly how much you used it" | The README is stricter. Satisfy the README: prompts, model ID, and token counts. It costs nothing, and the brief says "critical use counts in your favour". | RESOLVED |
| A6 | AI correction example | "considerable advantage if you can highlight... at least one instance where the AI undertook work that you then corrected" | "Include at least one example where the tool produced something you corrected" | The brief makes it **mandatory** where the README makes it merely advantageous. Treat as mandatory. **This must be a genuine correction made by you** - see `AI_log.md`. | OPEN |
| A7 | Role framing | Section 1 is gated "if applying for a Data Engineering Position"; Section 2 covers DE / Vis / FE / Science | Both required regardless of role | Assume a Data Engineering emphasis: modularity, testing, clean code, logging and data-quality tests - the traits the README names for DE candidates. | RESOLVED |

---

## B. Defects and ambiguities in the upstream documentation

| # | Severity | Finding | Impact | Proposed handling |
|---|---|---|---|---|
| B1 | **High** | **S3 Select is closed to new AWS customers** (announced July 2024). Section 1 mandates it. The API continues to work for *existing* customers. | If `SelectObjectContent` is called with a **personal or newly created** AWS account, it fails outright. The City's account is long-standing, which is precisely why dummy credentials are supplied. | Hard-require the supplied credentials; never silently fall back to an ambient AWS profile or environment variables. Detect the condition and fail with an explicit, actionable message. Pin `boto3`. Document a non-S3-Select fallback but keep S3 Select as the primary path, as instructed. |
| B2 | Medium | The README hyperlinks "AWS S3 SELECT" to the **S3 Glacier Select** SQL reference (`s3-glacier-select-sql-reference-select.html`) rather than the S3 Select reference (`s3-select-sql-reference-select.html`). Glacier Select is a different service, also deprecated. | A candidate following the link writes against the wrong API and SQL dialect. | Use the S3 Select API (`SelectObjectContent`) and its own SQL reference. Note the link error in our README. Candidate for an upstream PR, which the README explicitly invites. |
| B3 | Medium | Malformed S3 URI for the image data: `s3://cct-ds-code-challenge-input-data.s3.af-south-1.amazonaws.com/images/swimming-pool` mixes the `s3://` scheme with an HTTPS endpoint hostname. The correct form is `s3://cct-ds-code-challenge-input-data/images/swimming-pool`. | Copy-pasting this URI fails in every AWS client library. | Out of our scope (Section 4), but recorded. Candidate for the same upstream PR. |
| B4 | Medium | **Undefined behaviour for the `0` sentinel.** The spec defines index `0` only for records where "`Latitude` and `Longitude` fields are empty". It is silent on records that *have* coordinates but match **no** hexagon (outside coverage, or falling in a sliver gap). | These are semantically different - one is expected and benign, the other is a genuine join failure that should feed the error threshold - but the spec gives no guidance for the second. | Keep the two classes separate internally. The published output must still match `sr_hex.csv.gz`, so the *emitted* encoding will be whatever that file actually does. **UNVERIFIED - the data decides.** See `docs/decisions.md` section 2. |
| B5 | Medium | `0` has **no declared data type**. Is `h3_level8_index` the string `"0"` or the integer `0`, in a column that otherwise holds 15-character hex strings? | Silent validation failure: `"0" != 0`, and pandas will cheerfully coerce a mixed column to `object` or `float64`. | Read the validation file's column as `str` with type inference disabled, and mirror its exact literal. **UNVERIFIED.** |
| B6 | Low | The bullet reads "`sr_hex.csv.gz` contains the same data as `sr.csv`" - the uncompressed name, while the object is `sr.csv.gz`. | Cosmetic. | Note only. |
| B7 | Low | "12 months of service request data" is undated. Section 4 references "the first 6 months of 2020"; the objects were last modified 2022-06-21. | The actual date window is unstated and must be measured, never assumed. | Report observed min/max creation dates in the data-quality output. |
| B8 | Low | The repo carries a stale `master` branch alongside the default `main`. | Risk of forking or cloning the wrong ref. | Verified: the `master` and `main` READMEs are **byte-identical** today. Fork from `main`. |
| B9 | Info | README: "Be sure to 'watch' this repo for changes - we may push bugfixes." | Upstream could change mid-window. | Pin our fork to `48907f2` and re-check upstream immediately before submitting. |
| B10 | Medium | **Column names differ in case from the spec.** Section 2 says "where the `Latitude` and `Longitude` fields are empty". The actual columns are lowercase `latitude` and `longitude`. | Code written literally against the README raises `KeyError`. | Use the real lowercase names; assert the expected header on load so a future upstream rename fails loudly rather than silently. **CONFIRMED 2026-09-20.** |
| B11 | Medium | **`sr_hex.csv.gz` is not purely additive over `sr.csv.gz`.** The README says it "contains the same data as `sr.csv` as well as a column `h3_level8_index`". In fact `sr.csv.gz` carries a leading **unnamed index column** (a pandas `to_csv(index=True)` artifact) which `sr_hex.csv.gz` does **not**. So a column was dropped as well as added. | Any code assuming a pure superset mis-aligns columns; naive `read_csv` yields a junk `Unnamed: 0` column. | Read `sr.csv.gz` with `index_col=0`. Section 2 uses `sr_hex.csv.gz` as the reference, so impact is limited, but the asymmetry is worth knowing. **CONFIRMED 2026-09-20.** |

---

## C. Endpoint reconnaissance (HEAD requests only - no data downloaded)

All six objects are live and anonymously reachable:

| Object | HTTP | Size | Last modified |
|---|---|---|---|
| `sr.csv.gz` | 200 | 37.2 MB (gz) | 2022-06-21 |
| `sr_hex.csv.gz` | 200 | 36.7 MB (gz) | 2022-06-21 |
| `sr_hex_truncated.csv` | 200 | **63.4 MB (uncompressed)** | 2022-06-21 |
| `city-hex-polygons-8.geojson` | 200 | 1.97 MB | 2021-05-14 |
| `city-hex-polygons-8-10.geojson` | 200 | **108.3 MB** | 2021-05-14 |
| `ds_code_challenge_creds.json` | 200 | 115 B | 2021-05-14 |

Observations:

- **The 108.3 MB to ~1.97 MB reduction is the entire point of Section 1.** That ratio is the headline performance metric to report, alongside `BytesScanned` and `BytesReturned` from the S3 Select `Stats` event.
- `sr_hex_truncated.csv` is served **uncompressed**, so a like-for-like comparison against `sr_hex.csv.gz` requires decompressing the latter first. Its 63.4 MB is *plausible* for a 3-month slice but is **not on its own evidence** of one - it could equally reflect a different column set. Must be verified (D1).
- All payloads are static (2021/2022), so on-disk caching keyed by ETag is safe and makes reruns near-instant.

---

## D. Data-quality questions - planned checks, NOT yet run

Per instruction, **no datasets have been retrieved**. Everything below is a specified test awaiting your go-ahead. **Nothing in this section is a finding.**

### D1. Is `sr_hex_truncated.csv` genuinely a subset of `sr_hex.csv`? - ~~DESCOPED 2026-09-20~~

> **Not being run.** Section 3, the only consumer of this file, is out of scope, and the file is
> not a dependency of Sections 1-2. The specification below is retained only so the check can be
> picked up later without redesigning it.

Not answerable from row counts or date ranges alone. The test is set-membership **and** value equality:

1. Are the column set and order identical? A superset or subset of columns is itself a finding.
2. Is the truncated key set a strict subset of the full key set? Report any orphan keys - *this is your specific question.*
3. For shared keys, do the **whole rows** match? Compare a normalised row hash, not just the key. A record can share an ID and still differ in a field, for example a later status update.
4. Does the truncated date range actually span ~3 months, and is it a **contiguous window** within the full range?
5. Is the truncation a clean time-slice, or filtered some other way (for example by directorate)? Confirm by checking whether the full file holds *any* rows inside the truncated window that are absent from the truncated file.

Note: Section 3, which consumes this file, is out of scope, so this is a data-integrity check for you rather than a deliverable dependency.

### D2. Coordinate inversion

The check is cheap and decisive because Cape Town's latitude and longitude ranges are **disjoint and opposite in sign**:

- Valid: longitude approximately **+18.3 to +19.0**, latitude approximately **-34.4 to -33.4**
- Inverted: a "latitude" reading approximately +18.4 alongside a "longitude" of approximately -33.9

Targets:

1. **SR data** - the `Latitude` and `Longitude` columns, per row. Classify every row as valid / inverted / out-of-bounds / null-island `(0,0)` / missing.
2. **Both GeoJSON files** - RFC 7946 mandates `[longitude, latitude]` position order. Axis-order inversion is a *common* defect in municipal GeoJSON exports. If the first ordinate reads approximately -33.9, the file is inverted.
3. **Consistency between the two** - if the polygons are inverted and the points are not, or vice versa, the join yields approximately zero matches. This check must therefore run *before* the join, as a gate.

Handling: detect, log loudly, normalise, then assert. Never silently swap.

### D3. Other data-quality checks queued

- `(0, 0)` null-island coordinates masquerading as valid; empty string vs whitespace vs `"nan"`/`"NULL"` vs true null in the coordinate columns.
- Coordinates that are well-formed but fall outside the CoCT boundary.
- Coordinate precision and truncation - rounding to few decimal places creates artificial clustering on hexagon boundaries, which directly inflates the ambiguous-join count in `docs/decisions.md`.
- Duplicate notification IDs; non-unique keys.
- Temporal sanity: completion timestamps before creation; dates outside the stated window.
- GeoJSON structure: a non-RFC-7946 `crs` member; polygon validity and self-intersection; ring winding order; duplicate H3 index values; whether the H3 index property is named `index` or `h3_index`.
- **Schema of `city-hex-polygons-8-10.geojson`**: does each feature carry an explicit `resolution` or `level` property to filter on, or must resolution be inferred from the index itself? **This single unknown determines the S3 Select SQL** and is the first thing to inspect.
- Text encoding (mojibake) in suburb and department fields.

### D4. Does the City of Cape Town have full hexagon coverage?

Four independent angles, strongest first:

1. **Set difference (definitive).** Programmatically fetch the official CoCT municipal boundary, compute `h3.polygon_to_cells(boundary, res=8)`, and diff against the index set in `city-hex-polygons-8.geojson`.
   - `required - provided` = **true coverage gaps**
   - `provided - required` = cells outside the boundary, which are expected at the edge since hexagons straddle it
2. **Empirical.** Any SR with valid, in-bounds coordinates that fails to match a hexagon is direct evidence of a gap. Map the failures: genuine gaps cluster spatially, whereas random scatter points to a different cause.
3. **Topological.** Union the hexagons and inspect the interior for holes.
4. **Order-of-magnitude sanity.** ~~H3 resolution-8 cells average approximately 0.737 km squared; CoCT covers approximately 2,446 km squared, implying roughly 3,300 cells.~~ **Corrected 2026-09-20 after measurement — see section F2.** The 0.737 figure is H3's *global* mean; the cells over Cape Town measure **0.697990 km squared**. With CoCT at 2,445 km squared that predicts ~3,503 cells against **3,832 actual**, the ~9% excess being cells straddling the municipal boundary.

Dependency and risk: angle (1) needs the boundary from the CoCT open-data portal, whose reliability the upstream README itself warns about. Mitigation: retry with backoff, and cache the boundary into the repo as a fallback so the pipeline still runs end to end.

---

## E. Phase 1 reconnaissance findings (2026-09-20)

Established by HTTP **range requests** only - a few KB of each object, never the full 108 MB.
These settle the two unknowns that gated the Section 1 design.

### E1. `city-hex-polygons-8-10.geojson` carries an explicit `resolution` property - RESOLVED

```json
{ "type": "Feature",
  "properties": { "index": "88ad361801fffff",
                  "centroid_lat": -33.859427322761434,
                  "centroid_lon": 18.677843311941835,
                  "resolution": 8 },
  "geometry": { "type": "Polygon", "coordinates": [ [ [ 18.6811898997334, -33.863302790817968 ], ... ] ] } }
```

Resolution does **not** have to be inferred from the H3 index. The S3 Select predicate is a
direct `WHERE s.properties.resolution = 8`.

### E2. The reference file has a *different* property schema - IMPORTANT

`city-hex-polygons-8.geojson` features carry **no `resolution` property**:

```json
"properties": { "index": "88ad361801fffff", "centroid_lat": -33.859427322761434, "centroid_lon": 18.677843311941835 }
```

The file also has a top-level `"name": "city-hex-polygons-8"` member that the 8-10 file lacks.

**Consequence:** the records S3 Select returns are **not** field-identical to the reference,
even when both describe the same hexagon. A naive whole-record equality check between
extraction and reference **will fail**, and would look like a bug in the extraction.

Validation must therefore compare on the **intersection** of properties (`index`,
`centroid_lat`, `centroid_lon`, geometry), and treat `resolution` as extraction-only
provenance. This is recorded in `config/hex_schema.yaml` so the asymmetry is explicit rather
than buried in a comparison function.

Encouraging sign: for the features inspected, `index`, both centroids and every coordinate are
**character-for-character identical** across the two files, and feature ordering matches. Exact
comparison should be viable without a geometric tolerance - to be confirmed across the full set.

### E3. No coordinate inversion in the polygon files - RESOLVED

Both files declare `"crs": { "type": "name", "properties": { "name": "urn:ogc:def:crs:OGC:1.3:CRS84" } }`.

CRS84 is WGS84 with explicit **longitude-latitude** axis order, and the data agrees: the first
ordinate is ~`18.68` (longitude) and the second ~`-33.86` (latitude), which is correct per RFC
7946. **No axis swap in either GeoJSON.**

Note the `crs` member itself is a pre-RFC-7946 construct - RFC 7946 removed it and mandates
CRS84 unconditionally. Harmless, and here it is actively useful as explicit documentation of
intent.

The equivalent check on the SR data still has to run across all rows (D2). The first records
look correct - `latitude` ~`-33.87`, `longitude` ~`18.52` - but a per-row classification is
still needed, since inversion in a real dataset is usually partial rather than wholesale.

### E4. SR schema

```
notification_number, reference_number, creation_timestamp, completion_timestamp,
directorate, department, branch, section, code_group, code, cause_code_group,
cause_code, official_suburb, latitude, longitude, h3_level8_index
```

- **`notification_number` and `reference_number` carry leading zeros** (e.g. `000400583534`).
  These **must** be read as strings. Default type inference coerces them to integers and
  silently destroys the leading zeros, corrupting the join key used to validate against
  `sr_hex.csv.gz`. Explicit `dtype=str` on both.
- `creation_timestamp` / `completion_timestamp` are ISO-8601 with a `+02:00` SAST offset.
- Sampled records are from 2020, consistent with Section 4's reference to "the first 6 months
  of 2020" (B7).
- `h3_level8_index` values are 15-character H3 strings (e.g. `88ad360225fffff`), matching the
  `index` format in the polygon files.

### E5. Physical layout favours streaming

The 8-10 GeoJSON is pretty-printed with **one feature per line**. Each feature is roughly
500 bytes, so a `S3Object[*].features[*]` path expression keeps every S3 Select record three
orders of magnitude below the 1 MB record ceiling. The limit flagged as the most likely cause
of Section 1 failure is comfortably avoided.

### Still open after reconnaissance

- **B4 / B5** - the literal and dtype of the `0` sentinel in `sr_hex.csv.gz`. Needs a record
  with missing coordinates, which the leading rows do not contain. Resolve by reading the
  column as `str` and inspecting values whose length is not 15.
- **D2** - per-row coordinate classification across the full SR dataset.
- **D4** - coverage of the CoCT boundary.

---

## F. Assumption audit (2026-09-20)

Every figure asserted from general knowledge rather than measured was re-checked
against the data. Recorded because an unvalidated constant that happens to be
close enough is indistinguishable from a correct one until it is not.

| # | Claim as originally stated | Verified value | Verdict |
|---|---|---|---|
| F1 | Cape Town bbox: lon 18.20-19.10, lat -34.40 to -33.40 | Supplied hexagons span lon 18.2979-19.0126, lat -34.3649 to -33.4640 | **Correct.** Contains the City's own extent with 0.035-0.098 deg margin on every side. Kept deliberately loose - see F3. |
| F2 | H3 res-8 cells average ~0.737 km squared | **0.697990 km squared** measured across the 3,832 cells (range 0.6910-0.7030) | **WRONG by 5.3%.** See below. |
| F3 | CoCT area ~2,446 km squared | 2,445 km squared | Correct to within 1 km squared. Corrected for accuracy. |
| F4 | ~3,300 hexagons expected | **3,832** actual | **Underestimate by 13.9%**, a direct consequence of F2. Recomputed: 2,445 / 0.69799 = ~3,503, the remaining ~9% being cells straddling the boundary. |
| F5 | Res-8 H3 indices match `^88[0-9a-f]{8}fffff$` | 3,832 / 3,832 match; all resolution 8 | **Verified.** |
| F6 | "Pentagons exist in the H3 grid but none fall near Cape Town" | 0 pentagons; all 3,832 cells have exactly 7 ring positions | **Verified.** |
| F7 | Cape Town to Johannesburg ~1,260 km (test constant) | 1,261.6 km | **Verified.** |
| F8 | Clock skew: 5,483 rows, median -4s, worst -15 min, all sub-hour | 5,483 (0.5823%), median 4s, worst 15m41s, all under 1 hour | **Verified exactly.** |
| F9 | Minor-inversion limit is "~3x the observed baseline" | 0.02 / 0.005823 = **3.43x** | Restated precisely. |
| F10 | Coordinate de-duplication would be "the single largest algorithmic win" | 460,413 unique of 729,270 rows = **1.58x** | **Overstated.** Real, but modest; the headline saving is Section 1's 98.2% transfer reduction. Corrected in README. |

### F2 in detail - the one that was actually wrong

The widely-quoted 0.737 km squared for H3 resolution 8 is the **global mean**. H3
cells are projected onto an icosahedron, so area varies with position: at Cape
Town's location the cells measure **0.697990 km squared**, 5.3% smaller.

Consequence: the a-priori estimate of ~3,300 cells was 13.9% low against the 3,832
actual. It was reported at the time as "an estimate to be confirmed, not a
measurement", so nothing downstream depended on it - the schema's `min_features`
/ `max_features` band of 2,500-5,000 contains the true value comfortably. But it
was quoted three times across the documentation as though it were a fact, and a
reader would reasonably have taken it as one.

**Lesson applied:** the published constant for a spatial system is a global
average, not a local one. `h3.cell_area()` on the actual cells costs
milliseconds and is exact.

### F3 - why the bounding box is not tightened to the measured extent

It would be tempting to narrow `CCT_BOUNDS` to the hexagons' measured span. That
would be wrong. The bbox classifies coordinates *before* the join; a point just
beyond hexagon coverage must be classed `VALID` and then fail the join as `R4`,
which surfaces it as a **coverage finding**. Tightening the box would reclassify
it as `OUT_OF_BOUNDS` and silently discard exactly the signal worth having.

Three real records do precisely this - see the `C2b_outside_coverage` category.

---

## G. Check coverage audit (2026-09-20)

Prompted by the question: *does the supplied data actually trigger all of the
checks?* It does not.

### Before

| Group | Exercised by real data | Dormant |
|---|---|---|
| Coordinate classes | 2 of 7 | `partial`, `inverted`, `null_island`, `out_of_bounds`, `unparseable` |
| Assignment rules | 3 of 6 | `R2_boundary_unique`, `R3_tiebreak`, `invalid_coordinates` |
| Disagreement categories | 2 of 6 | `C1`, `C2`, `C3`, `C5` |
| Hexagon conformance rules | **0 of 12** | all |
| Service request contract rules | 4 of 13 | all range, pattern and uniqueness rules |
| Consistency violations | **0 of 3** | all |
| Coverage hole detection | **0 of 1** | fully-enclosed hole |
| **Total** | **11 of 48 (23%)** | **37 of 48 (77%)** |

`src/validation.py` - the twelve-rule conformance scorer that is Section 1's
headline deliverable - additionally had **no tests at all**. It scores 1.000000
on the supplied data and had never been demonstrated capable of returning
anything else. A scorer that has only ever returned 1.0 is indistinguishable
from `return 1.0`.

### The problem

A check that has never fired is indistinguishable from a check that is broken.
The pipeline reported healthy numbers on clean data while three quarters of its
logic, including every error and warning path, had never executed once.

### After

`tests/synthetic.py` builds inputs the real data does not contain - corrupted
hexagon features, frames containing every coordinate class, points on shared
edges and vertices, timestamps inverted by a month, columns emptied entirely.
`tests/test_hex_validation.py` and `tests/test_dormant_paths.py` drive every
remaining path and assert on what an operator would actually see: the rule that
drops, the exception raised, the artifact written, the log line emitted.

**83 tests. Every one of the 48 checks is now exercised by data or by test.**

### Two findings from writing them

**G1 - `centroid_within_polygon` cannot detect a consistent axis inversion.**
When both the ring and the centroid are swapped, the feature stays internally
coherent: the centroid still sits inside its own polygon in the swapped space.
Only the bounds rules catch it, and they do so reliably because Cape Town's
latitude and longitude ranges are disjoint and opposite in sign. An
*inconsistent* inversion, where only the geometry is swapped, is caught
topologically. Both shapes now have their own test, and the limitation is
asserted explicitly rather than left as an assumption.

**G2 - `R2_boundary_unique` is unreachable on any continuous tiling.** Every
interior boundary point touches at least two cells and therefore routes to R3.
R2 requires a boundary point with exactly one candidate, which only occurs at
the edge of the covered set. It is tested against a single-cell fixture.

Note also that a straight-line midpoint between two exact H3 vertices does not
lie exactly on the polygon edge once curvature is accounted for. On an interior
edge it lands inside one of the two cells; on an outer rim it lands outside
altogether, producing R4. Fixtures for boundary cases therefore use exact
vertices rather than derived midpoints wherever the distinction matters.

---

## H. Requirements audit (2026-09-20)

Line-by-line audit of the implementation against the literal wording of the
upstream README, rather than against a remembered summary of it.

### Section 1

| Requirement | Status |
|---|---|
| "Use the AWS S3 SELECT command to read in the H3 resolution 8 data from `city-hex-polygons-8-10.geojson`" | Met - `src/s3_io.py`, `SelectObjectContent` |
| "Use the `city-hex-polygons-8.geojson` file to validate your work" | Met - 3,832/3,832, geometries byte-identical |
| "add an additional validation that checks conformance to a reasonable schema" | Met - 15 weighted rules |
| "conformance score of some sort, with a non-binary threshold of your choice" | Met - fractional per rule, weighted mean, pass/warn/fail bands |
| "Explicitly capture the desired schema... in a standalone configuration or documentation file" | Met - `config/hex_schema.yaml` |
| "log the time taken... **as well as the validation steps**" | Met - conformance and comparison timed separately |
| "try to optimise latency and computational resources" | Met - 98.2% transfer reduction, 3.8x vs baseline |

### Section 2

| Requirement | Status |
|---|---|
| "Join... such that each service request is assigned to a single H3 resolution level 8 hexagon" | Met - R0-R4 guarantees exactly one row out per row in |
| "Use the `sr_hex.csv.gz` file to validate your work" | Met - 99.996920% |
| "For any requests where the `Latitude` and `Longitude` fields are empty, set the index value to `0`" | Met - all 212,364 match the reference exactly |
| "Use your judgement to include any other appropriate validation" | Met - see the data contract |
| "logging that lets the executor know how many of the records failed to join" | Met - per-rule counts and shares |
| "include a join error threshold above which the script will error out" | Met - raises on breach |
| "Please motivate why you have selected the error threshold" | Met - `decisions.md` section 2 |
| "log the time taken" / "optimise latency" | Met - every stage timed into the run manifest |

### Gaps found and closed

The audit found five, four of which were real defects rather than omissions.

| # | Gap | Resolution |
|---|---|---|
| H1 | **Five imports were inside functions**, against the README's explicit instruction to "place `import` and `library()` commands at the top of your scripts". The dependency graph was checked and is a clean DAG - no circular import justified them. | All moved to module top. |
| H2 | **No integration test**, despite the README naming "unit and even integration tests" for Data Engineers, and despite Phase 5 of our own plan listing one. | `tests/test_integration.py` - 9 tests running `transform_join.run()` end to end against a stubbed client. |
| H3 | **`must_be_valid: true  # no self-intersection` was declared but never enforced.** The `geometry_valid` score was only the minimum of the type, position-count and closure rules, none of which detect a bow-tie. A self-intersecting hexagon scored as valid. | `geometry_simple` rule added using shapely; `geometry_valid` now includes it. |
| H4 | **`rings: 1` (no holes) declared but never enforced.** | `geometry_single_ring` rule added. |
| H5 | **`axis_order: lon_lat` declared but never enforced** - it was a comment describing intent, not a check. | `axis_order` rule added on both the hexagon and service request sides. |

`centroid_within_own_polygon` at collection level duplicated an existing
feature rule and was removed; `extraction_only_properties` was being honoured
only by coincidence (because `compare_properties` happened to omit
`resolution`) and is now read explicitly.

Dead configuration is worse than missing configuration: it documents a check
that does not run, and a reader auditing the schema would reasonably conclude
self-intersection was covered.

### H6 - the integration test caught a live regression immediately

Moving `import json` out of `run()` for H1 removed it without adding it at
module top. **All 83 unit tests still passed**, because not one of them calls
`run()`. The first integration test failed with `NameError: name 'json' is not
defined` - a fault that would have broken the real pipeline on its next run.

That is the case for integration tests stated better than any argument: the
unit suite verified every rule in isolation and was blind to the module being
unable to execute.

---

## I. Root cause of the C4 adjacent-cell disagreements (2026-09-20)

Earlier commits described these as the supplied polygon boundaries "drifting
slightly from the true H3 cell boundaries". **That wording was wrong and is
corrected here.**

### What was actually measured

The supplied polygons are **not** a rounded rendering of H3's geometry. Comparing
`city-hex-polygons-8.geojson` against `h3.cell_to_boundary()` for the disagreeing
cell:

```
vertices in supplied polygon : 6
vertices from h3             : 6
max per-vertex deviation     : 0.0000 m  (identical to within 1e-6)
```

The vertices are exact. The difference lies **between** them: a GeoJSON polygon
joins its vertices with straight lines in longitude/latitude space, whereas an H3
cell edge follows a geodesic in the library's icosahedral projection. The two
curves coincide at every vertex and separate very slightly in between.

Demonstration: the exact straight-line midpoint of the seam shared by
`88ad360221fffff` and `88ad360227fffff` is assigned by H3 to the second cell,
while the planar polygon places it in the first. Even the geometric centre of
the shared edge disagrees.

### How close are the affected points?

All four disagreeing coordinate pairs sit **within 2 mm** of a boundary:

| Coordinate | Distance to edge |
|---|---|
| (-33.87138874, 18.51291184) | **0.1289 mm** |
| (-34.01534140, 18.61084840) | 0.6656 mm |
| (-34.05500391, 18.81786608) | 1.9400 mm |
| (-33.81938352, 18.53545445) | 1.9891 mm |

For context, of 460,413 unique coordinate pairs only **2** lie within 1 mm of a
boundary and **23** within 1 cm. These are not ordinary near-edge points; they
are the extreme tail.

### Why the tie-break never ran on them

Each resolved as `R1_interior`. The point is a fraction of a millimetre *inside*
the drawn polygon, so `within` returns `True` and the rule that exists to handle
boundary ambiguity is never consulted. They are not tie-break failures - they are
cases the tie-break was never offered.

### J. The tie-break criterion was measurably wrong

Investigating the above exposed a defect in the rule itself. `docs/decisions.md`
justified nearest-centroid on the grounds that it "approximates what
`h3.latlng_to_cell` itself does". Measured against 4,000 points sampled from
known cells:

| Distance from cell boundary | Nearest-centroid disagrees with H3 |
|---|---|
| 0 - 1 m | **55.6%** |
| 1 - 5 m | 18.2% |
| 5 - 10 m | 4.0% |
| > 10 m | 0.0% |

Overall agreement is 99.75%, which sounds reassuring and is misleading: **the
entire disagreement is concentrated within 10 m of a boundary, and the tie-break
runs only on points that are ON a boundary.** In the sole regime where the rule
applies, it was close to a coin flip.

H3 cell membership is defined by the library's icosahedral projection, not by
spherical proximity to a centre, so the approximation was unnecessary in the
first place. The rule is now:

1. the cell `h3.latlng_to_cell` assigns, when it is among the candidates;
2. otherwise nearest centroid;
3. on an exact tie, lexicographically smallest index.

The library only *orders* the candidates; the geometric join still decides which
polygons are eligible.

**Exact ties are reachable, not hypothetical.** Haversine depends on
`sin^2(dlon/2)` and `sin^2` is even, so two centroids mirrored about a point at
the same latitude give bit-identical distances. Criterion 3 exists for that case
and is tested with a constructed example; `margin_m` is `0.0` there, which flags
it as a genuine coin-flip in the side-car.

`margin_m` is now unsigned, and a new `chose_nearest_centroid` column records
whether criteria 1 and 2 agreed. A `False` marks precisely the near-boundary
case where nearest-centroid was measured to be unreliable.

---

## K. Polygon overlap check (2026-09-20)

Added after asking whether one was worth having. The answer was yes, on three
grounds, none of which is "it might find something here" - it does not.

**1. The existing guard was point-driven, not data-driven.**
`assign_hexagons_geometric` already routes a point that lands strictly inside
more than one polygon through the tie-break. But that only fires *where a
service request happens to be*. An overlap in an area with no requests is
completely invisible to it. That is the same flaw as validating against the data
in front of you and reporting the result as a general property.

**2. It checks the cause, not the symptom.** Overlapping polygons are precisely
the structural defect that makes one service request match two cells and
duplicate downstream. The whole R0-R4 rule exists to contain that symptom, while
nothing verified the input property that would produce it.

**3. "H3 guarantees non-overlap" is the argument already rejected.** That is the
reasoning that left `must_be_valid` declared but unenforced (section H). We are
validating a supplied file, not trusting the process that generated it.

### Result on the supplied data

```
3,832 polygons, 10,979 adjacent pairs examined
pairs overlapping with positive area : 0
intersection geometry types          : {'LineString': 10979}
cost                                 : ~0.3 s  (~1% of a 33 s run)
```

Every adjacent pair intersects as a **zero-area LineString** - a shared edge,
exactly as H3 requires. The tiling is a true partition.

### Design notes

- Adjacent H3 cells share edges by design, so `intersects` is True for all 10,979
  neighbouring pairs. Only **positive area** is a defect. A check that flagged
  every neighbour would be useless, and the test suite asserts this explicitly.
- Tolerance `1.0e-14 deg2` (~1.2e-4 m2) absorbs floating-point noise at seams.
  Measured maximum here was exactly `0.0`.
- Implemented with an STRtree query rather than all-pairs: 14.7M naive
  comparisons reduce to 10,979 candidate pairs.
- A detected overlap **fails the run**. Unlike a coverage gap, which is a
  property of the supplied data worth reporting, an overlapping tiling makes the
  "exactly one hexagon per request" guarantee unachievable, so continuing would
  produce silently duplicated records.

It will almost certainly never fire. That is not an argument against it - by the
reasoning in section G, a check that has never fired is indistinguishable from a
check that is broken, which is why seven tests drive it against deliberately
overlapping fixtures.
