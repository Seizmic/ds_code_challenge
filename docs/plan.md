# Execution Plan

> **Status: complete.** All five phases delivered. Results in [results.md](results.md).

Budget: **~8 hours** (per the brief) against a deadline of **23:59 SAST, Tue 22 Sep 2026**.
Today is Sun 20 Sep 2026, leaving roughly two calendar days.

Nothing below has been started. Phase 0 is blocked on your sign-off.

---

## Phase 0 - Prerequisites (~10 min)

**Complete as of 2026-09-20.**

1. ~~Decide the open questions in [decisions.md](decisions.md)~~ - done.
2. ~~Install the GitHub CLI~~ - done. `gh` 2.101.0, user scope, via winget.
3. ~~`gh auth login`~~ - done.
4. ~~Set git identity~~ - done.
5. ~~Fork and clone~~ - done. `Seizmic/ds_code_challenge`, verified **public**, `origin` on the
   fork and `upstream` on `cityofcapetown`. Forked at upstream `48907f2`, the commit the
   discrepancy register was written against.
6. ~~Move drafted documents into the repo~~ - done. The City's original README is preserved at
   [upstream_README.md](upstream_README.md) so the discrepancy register stays auditable against
   the exact text it was written from.

---

## Phase 1 - Scaffold and data reconnaissance (~1h)

The first real task is **inspecting structure, not processing data**, because two unknowns
block the design and both are cheap to resolve:

1. **The schema of `city-hex-polygons-8-10.geojson`.** Does each feature carry an explicit
   `resolution`/`level` property, or must resolution be inferred from the H3 index? *This
   determines the Section 1 S3 Select SQL.* Resolve by pulling the first few KB via an HTTP
   range request - no need to touch the 108 MB.
2. **Coordinate axis order** in both GeoJSON files, and the exact dtype and literal used for the
   `0` sentinel in `sr_hex.csv.gz` (discrepancies B4, B5).

Also: project skeleton, `requirements.txt` with pinned versions, logging setup, config module,
ETag-keyed download cache.

**Gate:** do not write the S3 Select query before step 1 is answered.

---

## Phase 2 - Section 1, data extraction (~2h)

1. Naive baseline: full download and filter. Measure it - this is the comparison that makes the
   optimisation claim credible.
2. S3 Select implementation using the supplied credentials, with an explicit failure if they are
   absent (B1).
3. Validate against `city-hex-polygons-8.geojson`: exact index-set equality plus geometry
   comparison within tolerance.
4. Schema conformance scoring, with the target schema in `config/hex_schema.yaml` as a
   standalone file (an explicit requirement).
5. Timing and resource metrics into the run manifest.

**Known traps, to handle rather than discover:**

- **Record-size limit.** S3 Select caps a record at 1 MB. Querying the GeoJSON as a single
  `DOCUMENT` will blow this limit on a 108 MB file. The query must stream per-feature via a
  `S3Object[*].features[*]` path expression so each record stays small. This is the single most
  likely way Section 1 fails.
- **Event-stream framing.** `SelectObjectContent` payload events do **not** align to record
  boundaries. Naively parsing each payload chunk as JSON corrupts records that straddle a chunk.
  Buffer and split on delimiters.
- **No `ScanRange` parallelism.** Scan ranges are unsupported for JSON `DOCUMENT` input, so the
  parallel-split optimisation is unavailable here. Say so explicitly rather than leaving the
  reader wondering why it was not attempted.

---

## Phase 3 - Section 2, transformation and join (~2.5h)

1. Load the SR data with column pruning and explicit dtypes.
2. **Quality gate before the join** - coordinate inversion, bounds, null-island, missing-value
   classification (discrepancies D2, D3). Inversion must be caught here, because an undetected
   axis swap makes the join silently return near-zero matches.
3. De-duplicate coordinate pairs, join only the unique set, broadcast back. Report the
   unique-pair ratio, which quantifies the saving.
4. Geometric join with the R0-R4 rule from [decisions.md](decisions.md).
5. Emit `data/quality/ambiguous_hex_assignments.csv` and `data/quality/join_summary.json`.
6. Calibrate and apply the error threshold.
7. Validate the output against `sr_hex.csv.gz` and classify every mismatch.

---

## Phase 4 - Requested investigations (~1.5h)

Separate from the Section 1-2 deliverables.

| Check | Reference | Output |
|---|---|---|
| **Dual-method comparison over the full dataset** | [decisions.md](decisions.md) section 4 | `docs/method_comparison.md`; per-category counts C1-C5; `data/quality/method_disagreements.csv` |
| Coverage of the CoCT boundary | [discrepancies.md](discrepancies.md) D4 | Missing/extra cell counts and a map of gaps. **Reported, not fatal** - see decisions section 3. |
| Coordinate inversion and general quality | D2, D3 | Per-class row counts with worked examples |
| ~~`sr_hex_truncated.csv` vs `sr_hex.csv`~~ | ~~D1~~ | **Descoped 2026-09-20.** |

The dual-method comparison and the coverage check share evidence: category **C2** (the H3
library returns a cell that the polygon file lacks) is an independent measurement of exactly
the same gaps that D4's set-difference finds. Running them together means the two results
cross-validate, and a disagreement between them is itself informative.

---

## Phase 5 - Tests, documentation, submission (~1h)

1. Unit tests on the tie-break rule (a point on a shared edge; a point on a vertex; a point in a
   sliver gap), the inversion detector, and schema scoring.
2. One integration test running the pipeline end to end on a small fixture.
3. **Clone-and-run verification from a clean directory.** The challenge is explicit: "If your
   repo does not clone and run, we will not attempt to fix it." This step is non-negotiable and
   must not be the thing that gets cut for time.
4. Finalise `README.md`, `AI_log.md` (including your own correction example), and the quality
   report.
5. Re-check upstream for bugfix commits (B9). Confirm the fork is public. Send the link.

---

## If time runs short

Cut in this order, and say in the README what was cut and why:

1. Phase 4 coverage mapping - keep the counts, drop the visualisation.
2. The naive Section 1 baseline - keep the S3 Select metrics, lose the comparison.
3. Integration test - keep the unit tests.

**Never cut:** Phase 5 step 3. A repository that does not run scores zero regardless of what is
inside it.

---

## Principal risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| S3 Select rejected for the calling account (B1) | Medium | Use supplied creds only; fail loudly; document the fallback |
| 1 MB record-size limit breaks the query | **High if unanticipated** | Path-expression streaming, designed in from the start |
| CoCT boundary endpoint unavailable for D4 | Medium | Retry with backoff; cache the boundary in-repo so the pipeline still runs |
| Memory pressure comparing the two SR files | Medium | Hash-based comparison, chunked |
| Upstream pushes a bugfix mid-window | Low | Re-check before submitting |
