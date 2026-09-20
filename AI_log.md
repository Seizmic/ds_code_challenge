# AI Usage Log

Disclosure of generative-AI assistance, as required by the challenge README ("log all of the
work that you asked AI assistance to undertake, including any prompts, the model used as well
number of tokens") and by the assessment brief.

**Tool:** Claude Code (Anthropic), model `claude-opus-5`
**Usage:** heavy. The AI drafted the documentation, wrote the pipeline code and the tests, and
ran the analysis. It was directed and audited throughout rather than accepted as delivered.
Seven corrections are documented below; the five substantive ones were prompted by the
candidate challenging a claim or an untested assumption, and each turned up a real defect.

---

## Token accounting

| # | Date | Session | Approx. tokens (in / out) |
|---|---|---|---|
| 1 | 2026-09-20 | Requirements audit and documentation scaffold | ~90k / ~13k |
| 2 | 2026-09-20 | Environment audit, `gh` install, decisions folded into docs | ~35k / ~6k |
| 3 | 2026-09-20 | Fork, Section 1, Section 2, tests | ~210k / ~48k |
| 4 | 2026-09-20 | Data quality contract and assumption audit | ~95k / ~22k |
| 5 | 2026-09-20 | Phase 4/5 reports, clean-clone verification, check coverage audit | ~120k / ~30k |
| 6 | 2026-09-20 | Requirements audit, axis-order enforcement, integration tests | ~85k / ~24k |
| 7 | 2026-09-20 | Record tracing, tie-break revision, overlap check | ~110k / ~28k |
| | | **Total** | **~745k / ~171k** |

Figures are estimated from context size rather than exact client-reported counts.

---

## Session log

### Session 1 - Requirements audit and documentation scaffold

**Asked for:** review the emailed brief against the upstream GitHub documentation and report
discrepancies, with the brief overriding GitHub where they conflict; identify where the
calculations need optimising; propose a rule for service requests falling at the intersection
of two or more polygons; assess whether the City has full polygon coverage; look for coordinate
inversion and general data-quality issues; verify `sr_hex_truncated.csv` against `sr_hex.csv`;
return a plan. Constraints: no pipeline code, no dataset downloads.

**Did:** read the upstream README in full; queried the GitHub API for branches, commits and
issues; ran HEAD-only requests against the six S3 objects to confirm availability and sizes
without downloading them; researched the status of the AWS S3 Select API; drafted `README.md`,
`AI_log.md`, `docs/discrepancies.md` and `docs/decisions.md`.

### Session 2 - Environment and decisions

**Asked for:** four design decisions (descope the truncated-file check; run both join methods
over the full dataset and categorise disagreements; report coverage gaps rather than failing on
them; the AI-correction example is the candidate's to write). Then: can the GitHub CLI be
installed, and what would make setup easier?

**Did:** audited installed tooling, git configuration and disk space; verified cp314 wheel
availability across the geospatial stack on PyPI; installed GitHub CLI 2.101.0. Did **not**
authenticate it - that requires the candidate's own credentials. Wrote `docs/environment.md`.

**Found:** git identity was unset, which would have produced commits unattributable to the
candidate's GitHub profile on a fork whose commit history is assessed.

### Session 3 - Sections 1 and 2

**Asked for:** fork the repository and implement Sections 1 and 2, with tests written alongside
Section 2 rather than afterwards.

**Did:** forked and cloned; implemented S3 Select extraction with non-binary conformance
scoring; implemented the R0-R4 assignment rule, coordinate quality gate, dual-method comparison
and reference validation; wrote 30 tests.

**Results:** Section 1 - conformance 1.000000, all 3,832 features byte-identical to the
reference, 98.2% transfer reduction, 4.2x faster than a naive download. Section 2 - 99.996920%
exact agreement with `sr_hex.csv.gz`.

### Session 4 - Data quality contract and assumption audit

**Asked for:** "I asked for data quality checks which would include consistency. Even though the
data we are working with may be clean, if the system is used with other data that is not 100%
clean, this may produce errors. What data quality metrics have you put in place and if none,
why not?" Then: re-check and validate everything that had been guessed or assumed.

**Did:** audited existing coverage, built `config/sr_schema.yaml` and `src/sr_validation.py`,
fixed a consistency bug, calibrated every threshold against measurement, and re-validated ten
asserted constants. See corrections 2 and 3.

### Session 5 - Reports, verification and check coverage

**Asked for:** finish Phases 4 and 5. Then: "For the checks that we have in place, does the
data trigger all of them? If not, can we create synthetic data to ensure that the error logging
and all logic we have in place fires?"

**Did:** added the coverage analysis and the generated results document; verified that a clean
clone from GitHub installs and runs end to end at exit code 0; audited check coverage and built
the synthetic fixtures. See correction 5.

**Also fixed two reporting bugs found by reading the generated output:** the naive baseline was
reusing the download cache, so it measured a local disk read rather than a 108 MB transfer and
reported S3 Select as 0.5x "faster" than a baseline that never touched the network. And the
reference-match verdict was coded as "zero disagreements", rendering a 99.996920% match as FAIL
while the pipeline exited 0 - incoherent against the non-binary scoring used everywhere else,
and against the documented decision to keep the geometric route knowing it differs on 29
records.

---

### Session 6 - Requirements audit and axis ordering

**Asked for:** "Please do a full audit of what was coded against the requirements. Double-check
the code to ensure there are no gaps. Also, are the latitude and longitude variable of type
geometry? If not, is it possible that we can get the latitude and longitude swapped in the input
data, and do we have checks in place if this is the case?"

**Did:** audited the implementation line by line against the literal wording of the upstream
README; found and closed five gaps; implemented the three schema rules that had been declared
but never enforced; added integration and axis-order test suites. Re-ran the clean-clone
verification: 107 tests pass and the full pipeline runs cold from a fresh clone in 42.5s at exit
code 0. See correction 6.

---

### Session 7 - Record tracing and the tie-break

**Asked for:** trace a record through the pipeline step by step; then one of the three unmatched
records; then one of the 26 adjacent-cell disagreements. Then: "Make the correction. Explore the
tie-break. What happens when the coordinate is at the boundary and the centroid of the 2
adjoining polygons has the exact distance to the coordinate?" Then whether a polygon overlap
check was worth adding.

**Did:** traced three records end to end with real values at every stage; corrected the stated
root cause of the C4 disagreements; measured the tie-break criterion and replaced it; added and
tested the exact-tie case; added a collection-level polygon overlap check. See correction 7.

**Also answered:** a question about a value of "AA" appearing instead of NULL. No such value was
ever written or present - the classifier's null-token set contains `"na"` and `"n/a"`, easily
misread. Worth stating plainly that those tokens are **defensive rather than observed**: the
supplied data contains exactly one non-numeric coordinate value, the empty string. Unlike every
threshold in the config, that token set is not calibrated against this dataset.

---

## Corrections and improvements

The brief requires at least one documented instance where AI output was corrected. There are
seven below, split by who caught them, because that distinction is the point of the section.

**Candidate-driven (2, 3, 5, 6, 7)** - Naveen's questions caused these. Each began as a
challenge to a claim the AI had made, or to an assumption it had left unexamined, and each
turned up a real defect. These are the substantive ones.

**AI-caught (1, 4)** - found by the tool mid-task. Recorded for completeness, but they do not
satisfy the brief's requirement, and are labelled as such rather than quietly padding the list.

### 1. AI self-correction - summarised source mistaken for verbatim

The first attempt to read the upstream README used a fetch tool that returns an
*LLM-summarised* rendering rather than the source. The summary was fluent and plausible, and it
silently dropped the fact that the "AWS S3 SELECT" hyperlink points at the **S3 Glacier Select**
documentation (finding B2), omitted the malformed `s3://` URI (B3), and paraphrased the
specification of the `0` sentinel, losing the wording the B4 ambiguity turns on.

Auditing a document for discrepancies against a *paraphrase* of it is self-defeating. The raw
markdown was fetched instead and the audit redone against it.

*Caught by the AI, so this does not satisfy the brief's requirement.*

### 2. Candidate-driven - the data quality checks were lopsided

**This is the primary example.**

After Section 2 was working and validating at 99.9969%, Naveen asked what data quality metrics
were in place, noting that the supplied data being clean says nothing about how the system
behaves on a source that is not.

The honest answer was that the checks were badly asymmetric. The **hexagon** side had a proper
contract from the start - `config/hex_schema.yaml`, twelve weighted rules, non-binary scoring.
The **service request** side had **nothing**: no column assertions, no null-rate ceilings, no
temporal validation, no uniqueness check, no row-count sanity. The pipeline consumed 941,634
rows of input it never checked. Pointed at a renamed column it would raise `KeyError`; at a
column gone entirely null, or a ten-row truncated extract, it would have produced confident and
wrong output.

Worse, the AI had *written down* this exact requirement in `docs/discrepancies.md` B10 - "assert
the expected header on load so a future upstream rename fails loudly" - and then not implemented
it. It had measured clean data and concluded the data was clean, which is a coincidence, not a
check.

**The bug this surfaced.** `classify_coordinates` used **OR** across latitude and longitude:

```python
missing = lat_null | lon_null          # wrong
```

So a record with a latitude but no longitude was classed `MISSING`, handed the no-geolocation
sentinel `0`, and counted as a legitimate ungeolocated record. The fault would have vanished
into an expected total of 212,364 with nothing downstream revealing it. This dataset contains
zero such records, so it never manifested - which is precisely the failure mode the question
was about. It is now:

```python
missing = lat_null & lon_null          # both absent
partial = lat_null ^ lon_null          # exactly one: a hard violation
```

**What the new contract then found in the supplied data:**

1. **5,483 rows (0.58%) complete before they are created.** Investigated before adjusting any
   threshold: every one is sub-hour, median -4 seconds, worst -15m41s. That is clock skew
   between the systems recording creation and completion, not a logical fault. The rule was
   split by magnitude rather than loosened - gross inversions beyond an hour keep a limit of
   zero, because no amount of drift explains a day backwards.
2. **`reference_number` is 37% blank**, against an assumed ceiling of 5%.

Both thresholds had been set by intuition and both were wrong. Every null ceiling is now
calibrated against the measured baseline with headroom, with the observed figure recorded
beside it.

**Changed:** added `config/sr_schema.yaml` and `src/sr_validation.py`; fixed the OR/AND bug and
added the `PARTIAL` class; split the temporal rule by magnitude; calibrated all ceilings from
measurement; added 13 tests that feed the validator *deliberately broken* data, since testing
only against the clean supplied dataset would prove nothing about whether the checks fire.

### 3. Candidate-driven - assumptions asserted as facts

Naveen then asked for everything guessed or assumed to be re-checked and validated. Ten
asserted constants were audited against the data (`docs/discrepancies.md` section F). Eight held
up. Two did not:

**The real error.** The AI had stated three times across the documentation that H3 resolution-8
cells "average approximately 0.737 km squared". That is H3's **global** mean. H3 projects cells
onto an icosahedron, so area varies with position: measured across the actual 3,832 Cape Town
cells the mean is **0.697990 km squared** - 5.3% smaller. The derived estimate of ~3,300
hexagons was consequently 13.9% low against 3,832 actual. Recomputed with the measured area it
predicts ~3,503, with the remaining ~9% being cells straddling the municipal boundary.

Nothing downstream depended on it, and it had been flagged at the time as "an estimate to be
confirmed, not a measurement". But it was repeated as though established, and a reader would
reasonably have taken it as fact. `h3.cell_area()` on the real cells costs milliseconds and is
exact.

**The overstatement.** The README claimed coordinate de-duplication would be "the single largest
algorithmic win" because service requests "cluster heavily" on repeated addresses. Measured:
460,413 unique pairs from 729,270 rows - a 1.58x reduction. Real, but modest, and not the
headline saving. Corrected.

Also corrected: CoCT area 2,446 to 2,445 km squared, and a "~3x" threshold ratio restated as its
actual 3.43x.

### 4. AI self-correction - a test that silently skipped instead of failing

While writing the tie-break tests, the fixture located H3 vertices shared between adjacent cells
by rounding coordinates to 10 decimal places. That nudged the derived point about 5e-12 degrees
off the true boundary, so it fell *strictly inside* one polygon and the test **skipped rather
than failing**. The suite was green while not exercising the tie-break at all.

Probing directly showed H3 emits **bit-identical** coordinates for a shared vertex, so exact
comparison finds them: an exact vertex intersects 3 polygons and an exact edge midpoint
intersects 2. Both cases now assert the correct rule and candidate count.

Worth recording as the more dangerous failure mode: not a visibly wrong answer, but a passing
test that was not testing the thing it claimed to.

*Caught by the AI while writing the tests, so this does not satisfy the brief's requirement. It
was originally logged here as candidate-driven, which overstated the candidate's part in it;
corrected when the log was reviewed.*

---

### 5. Candidate-driven - three quarters of the checks had never fired

After the data contract was in place and the pipeline was validating at 99.9969%, Naveen asked
whether the supplied data actually triggers all of the checks, and whether synthetic data was
needed to make the error logging and the rest of the logic fire.

It did not, and by a wide margin. An audit of the run manifest found **11 of 48 checks
exercised**. The other **37 (77%) had never executed once**, including every warning and error
path in the codebase:

| Group | Fired on real data | Dormant |
|---|---|---|
| Coordinate classes | 2 of 7 | `partial`, `inverted`, `null_island`, `out_of_bounds`, `unparseable` |
| Assignment rules | 3 of 6 | `R2_boundary_unique`, `R3_tiebreak`, `invalid_coordinates` |
| Disagreement categories | 2 of 6 | C1, C2, C3, C5 |
| **Hexagon conformance rules** | **0 of 12** | all |
| Service request contract rules | 4 of 13 | all range, pattern and uniqueness rules |
| **Consistency violations** | **0 of 3** | all |
| **Coverage hole detection** | **0 of 1** | fully-enclosed hole |

Worse, `src/validation.py` had **no tests at all**. That module is the twelve-rule conformance
scorer which is Section 1's headline deliverable. It scores 1.000000 on the supplied data and
had never been demonstrated capable of returning anything else - indistinguishable, from the
outside, from a function that returns the constant 1.0.

This is the root cause of corrections 2 and 3 appearing in a third place: confident numbers on
clean data, with most of the logic underneath unverified. The AI had built the checks, watched
them report healthy values, and treated that as evidence they worked.

**Changed:** added `tests/synthetic.py`, which constructs the inputs the real data does not
contain - corrupted hexagon features, a frame containing every coordinate class with expected
counts, points on shared edges and vertices, timestamps inverted by a month, columns emptied
entirely. Added `tests/test_hex_validation.py` and `tests/test_dormant_paths.py`, which drive
every remaining path and assert on what an operator would actually see: the rule that drops,
the exception raised, the artifact written, the log line emitted. Test count went from 41 to
**83**, and all 48 checks are now exercised by data or by test.

**Three further defects surfaced while writing them**, which is the point of the exercise:

1. A test asserting that `centroid_within_polygon` detects axis inversion **failed** - and the
   test was wrong, not the code. A *consistent* inversion leaves the feature internally
   coherent, so the centroid still sits inside its own polygon in the swapped space and the
   topological rule cannot see it. The bounds rules are what catch it. The limitation is now
   asserted explicitly rather than assumed, and the complementary inconsistent case has its own
   test.
2. `hex_collection` sliced an arbitrary 20 cells from a 37-cell disk, which could omit one of
   the three cells meeting at a vertex. The tie-break test then silently exercised the weaker
   two-candidate case while still passing - the same failure shape as correction 4, reproduced
   by the AI in a new fixture.
3. `R2_boundary_unique` turns out to be unreachable on any continuous tiling, since every
   interior boundary point touches at least two cells and routes to R3.

### 6. Candidate-driven - documented requirements that were never implemented

Naveen asked for a full audit of the code against the requirements, and separately whether
latitude and longitude are a geometry type and what happens if they arrive swapped.

Auditing against the **literal wording** of the upstream README rather than a remembered
summary of it found five gaps. Four were real defects:

1. **Five imports sat inside functions**, against an explicit instruction in the README:
   "place `import` and `library()` commands at the top of your scripts". Checking the
   dependency graph showed it is a clean DAG, so no circular import justified them. They were
   defensive habit, not necessity.
2. **No integration test existed**, though the README names "unit and even integration tests"
   for Data Engineering candidates - and though Phase 5 of the plan the AI itself wrote listed
   one.
3. **`must_be_valid: true  # no self-intersection` was declared in the schema and never
   enforced.** The `geometry_valid` score was only the minimum of the type, position-count and
   closure rules, none of which detect a bow-tie. A self-intersecting hexagon scored as valid.
4. **`rings: 1` and `axis_order: lon_lat` were likewise declared and never enforced** - comments
   describing intent, presented in a configuration file as though they were checks.

Dead configuration is worse than missing configuration. Anyone auditing `hex_schema.yaml` would
reasonably have concluded self-intersection was covered. The file asserted a guarantee the code
did not provide.

**The integration test then earned itself within a minute.** Moving `import json` out of `run()`
to satisfy gap 1 removed it without adding it at module top. **All 83 unit tests still passed** -
not one of them calls `run()`. The first integration test failed with `NameError: name 'json' is
not defined`, on a fault that would have broken the real pipeline on its next execution. The
unit suite verified every rule in isolation and was blind to the module being unable to run.

**On the latitude/longitude question.** They are two independent *text* columns, not a geometry
type; nothing in the data binds them together or records which is which. The risk is sharpened
by two libraries in this pipeline taking the pair in opposite orders - `shapely` wants
`(longitude, latitude)`, `h3` wants `(latitude, longitude)` - so transposing either is a
one-character edit that raises no error and returns a plausible answer. `tests/test_axis_order.py`
now pins both conventions, asserts our own call sites, and verifies that swapped input is
classified as `INVERTED` rather than merely out of range. One test matters more than the rest:
it asserts the configured latitude and longitude ranges stay **disjoint**, since that property is
what makes inversion detectable at all, and widening the bounds would silently remove the
capability.

**Changed:** imports to module top; `tests/test_integration.py` (9 tests) and
`tests/test_axis_order.py` (11 tests); `geometry_simple`, `geometry_single_ring` and
`axis_order` rules implemented; `coordinate_axis_order` added to the service request contract so
a wholesale swap reports as inversion rather than as "longitude out of range". 83 tests to
**107**.

**One self-inflicted error along the way:** the YAML patch used `str.replace` without a count,
and `  completion_after_creation:` is a substring of the four-space-indented weights entry, so
the block was injected twice and broke the schema. The suite caught it immediately.

### 7. Candidate-driven - a stated root cause that was wrong, and a rule that was worse

Naveen asked for a record to be traced through the pipeline, then for one of the 26
adjacent-cell disagreements specifically, then to explore the tie-break. Each step invalidated
something the AI had previously asserted.

**The stated root cause was wrong.** Earlier commits explained the 26 disagreements as the
supplied polygons "drifting slightly from the true H3 cell boundaries". Measuring it:

```
supplied polygon vertices vs h3.cell_to_boundary()
  max per-vertex deviation : 0.0000 m  (identical to within 1e-6)
```

The vertices are exact. The difference lies **between** them - a GeoJSON polygon joins its
vertices with straight lines in longitude/latitude space, while an H3 edge follows a geodesic in
the library's icosahedral projection. The curves meet at every vertex and separate slightly in
between. All four disagreeing coordinates sit within **2 mm** of a seam, the closest at 0.1289
mm; of 460,413 unique pairs only two lie within 1 mm.

**The tie-break rule itself was then measured, and was worse.** `docs/decisions.md` justified
nearest-centroid as approximating "what `h3.latlng_to_cell` itself does". Sampling 4,000 points
against the cell H3 assigns them to:

| Distance from boundary | Nearest-centroid disagrees with H3 |
|---|---|
| 0 - 1 m | **55.6%** |
| 1 - 5 m | 18.2% |
| > 10 m | 0.0% |

Overall agreement is 99.75%, which reads well and is actively misleading. The entire
disagreement is concentrated near boundaries, and **the tie-break only ever runs on points that
are on a boundary**. In its sole operating regime the criterion was close to a coin flip, and
the reassuring headline number was measuring the regime where the rule never applies.

H3 cell membership is defined by the library's own projection, not by spherical proximity to a
centre, so the approximation was never necessary. The rule now leads with the library's
assignment, constrained to the candidate set so the geometric join still decides which polygons
are eligible.

**On the exact-tie question.** Naveen asked what happens when two centroids are exactly
equidistant. It is reachable rather than hypothetical: haversine depends on `sin^2(dlon/2)` and
`sin^2` is even, so two centroids mirrored about a point at the same latitude give bit-identical
distances. Criterion 3 (lexicographic index) resolves it, `margin_m` is `0.0`, and the case is
now constructed and tested directly, including stability under input reordering.

**On the overlap question.** Asked whether a polygon overlap check was worth adding, the answer
was yes - not because it finds anything here (it finds nothing; all 10,979 adjacent pairs share
edges as zero-area lines) but because the existing guard was *point-driven*: it only fired where
a service request happened to land in an overlap, so an overlap in an empty area was invisible.
It checks the cause in the input rather than the symptom in the output.

**One AI-caught slip during the same session**, worth recording because of what it repeats: the
patch updating `docs/decisions.md` to the new tie-break **failed silently** while the commit
went through regardless, leaving the document describing the old rule. That is correction 6's
failure mode - a document asserting behaviour the code does not have - recurring within the
hour, in the very commit that documented correction 6's lesson.

## Standing lesson

Five of the seven corrections share one root cause: **the AI validated against the data in front
of it and reported the result as a general property.** Clean data scored well, so the checks
looked adequate; a rounded fixture still passed, so the test looked adequate; a published
constant was close enough, so it went unchecked. In each case the output was confident and the
gap invisible until someone asked what would happen with different input.

The pattern recurred even after it had been named. Correction 5 is correction 2 in a different
layer, and the fixture fault inside it repeats correction 4 exactly. Recognising a failure mode
in retrospect did not stop the AI reproducing it; what caught it each time was the candidate
asking a pointed question about a part of the system that looked fine.

**Correction 6 exposed a second, distinct failure mode: writing a requirement down and treating
that as having met it.** It happened twice. In `docs/discrepancies.md` B10 the AI wrote that the
expected header should be asserted on load "so a future upstream rename fails loudly", then did
not implement it - that gap became correction 2. In `docs/plan.md` Phase 5 it listed an
integration test, then did not write one - that gap became correction 6. The schema file did the
same thing in miniature, declaring `must_be_valid` and `axis_order` as configuration while no
code read either.

Documentation and intent are cheap to produce and read as progress. Both times, the written
record made the work look more complete than it was, and the discrepancy was only visible to
someone who went back and checked the code against the document rather than reading the
document alone.

**Correction 7 shows the second mode surviving even its own diagnosis.** The commit that
recorded "dead documentation asserting behaviour the code does not have" as a lesson was
followed, within the hour, by a documentation patch that failed silently while its commit
succeeded - leaving `decisions.md` describing a tie-break rule the code no longer had.

Correction 7 also sharpened the first mode. The claim that nearest-centroid "approximates what
H3 does" was never tested, and its 99.75% agreement looked like confirmation. That number
averages over a population the rule never sees. Measured in the regime where the rule actually
operates - points on a boundary - it was wrong more than half the time. A summary statistic
computed over the wrong population is not weak evidence; it is misleading evidence, and it read
as reassurance for several sessions.
