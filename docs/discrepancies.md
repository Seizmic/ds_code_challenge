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
4. **Order-of-magnitude sanity.** H3 resolution-8 cells average approximately 0.737 km squared; CoCT covers approximately 2,446 km squared, implying roughly **3,300 cells** plus an edge margin. The 1.97 MB file size is broadly consistent with that count. *This is an a-priori estimate to be confirmed, not a measurement.*

Dependency and risk: angle (1) needs the boundary from the CoCT open-data portal, whose reliability the upstream README itself warns about. Mitigation: retry with backoff, and cache the boundary into the repo as a fallback so the pipeline still runs end to end.
