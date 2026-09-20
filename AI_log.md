# AI Usage Log

Disclosure of generative-AI assistance, as required by the challenge README ("log all of the
work that you asked AI assistance to undertake, including any prompts, the model used as well
number of tokens") and by the assessment brief.

**Tool:** Claude Code (Anthropic), model `claude-opus-5`
**Usage:** heavy. The AI drafted the documentation, wrote the pipeline code and the tests, and
ran the analysis. It was directed and audited throughout rather than accepted as delivered.
Five corrections are documented below; the three substantive ones were prompted by the
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
| | | **Total** | **~550k / ~119k** |

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

## Corrections and improvements

The brief requires at least one documented instance where AI output was corrected. There are
five below, split by who caught them, because that distinction is the point of the section.

**Candidate-driven (2, 3, 5)** - Naveen's questions caused these. Each began as a challenge to
a claim the AI had made, or to an assumption it had left unexamined, and each turned up a real
defect. These are the substantive ones.

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

## Standing lesson

Four of the five corrections share a root cause: **the AI validated against the data in front
of it and reported the result as a general property.** Clean data scored well, so the checks
looked adequate; a rounded fixture still passed, so the test looked adequate; a published
constant was close enough, so it went unchecked. In each case the output was confident and the
gap invisible until someone asked what would happen with different input.

The pattern recurred even after it had been named. Correction 5 is correction 2 in a different
layer, and the fixture fault inside it repeats correction 4 exactly. Recognising a failure mode
in retrospect did not stop the AI reproducing it; what caught it each time was the candidate
asking a pointed question about a part of the system that looked fine.
