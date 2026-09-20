<img src="img/city_emblem.png" alt="City Logo"/>

# City of Cape Town - DS Code Challenge: Sections 0-2

Response to the [City of Cape Town Data Science Unit code challenge](https://github.com/cityofcapetown/ds_code_challenge).

**Scope: Sections 0 (setup), 1 (data extraction) and 2 (initial data transformation).**
Sections 3-6 are deliberately out of scope as directed - their omission is intentional, not
unfinished work.

---

## Quick start

Requires **Python 3.11 or newer** (developed and tested on 3.14.3). No AWS account needed -
the challenge supplies credentials, which the pipeline fetches at runtime.

```bash
pip install -r requirements.txt
python -m src.main
```

That runs end to end with no human interaction, in about 35 seconds. Input data is downloaded
automatically and cached under `data/raw/`, so reruns skip the network.

| Command | Purpose |
|---|---|
| `python -m src.main` | Both sections, end to end |
| `python -m src.main --section 1` | Extraction only |
| `python -m src.main --baseline` | Also run the naive download baseline for comparison |
| `python -m src.main --join-method library` | Publish the H3 library assignment instead |
| `python -m pytest tests/ -q` | 118 tests |

---

## Results

Full generated detail in **[docs/results.md](docs/results.md)**, which is written by the
pipeline from the run manifest so it cannot drift from what the code did.

| | Result |
|---|---|
| **Section 1** schema conformance | **1.000000** (PASS) |
| **Section 1** polygon overlap | **0** of 10,979 adjacent pairs |
| **Section 1** validation vs reference | **3,832 / 3,832** features, every geometry byte-identical |
| **Section 1** transfer reduction | **98.2%** - 1.9 MB returned from a 103 MB object |
| **Section 1** vs naive download | **3.8x faster** |
| **Section 2** validation vs `sr_hex.csv.gz` | **99.996920%** exact match (941,605 / 941,634) |
| **Section 2** input data conformance | **0.995299** (PASS) over 941,634 rows |
| Method agreement (geometric vs H3 library) | 99.998697% |
| Coordinate inversion / null-island / out-of-bounds | **0** |
| Full pipeline runtime | ~35s |

---

## Documentation

| Document | What it covers |
|---|---|
| [docs/results.md](docs/results.md) | **Generated** results, coverage analysis, method comparison |
| [docs/discrepancies.md](docs/discrepancies.md) | Brief vs upstream audit, documentation defects, data findings, assumption audit |
| [docs/decisions.md](docs/decisions.md) | Multi-polygon tie-break rule and join error threshold, with motivation |
| [docs/environment.md](docs/environment.md) | Prerequisites and machine audit |
| [docs/plan.md](docs/plan.md) | Execution plan |
| [AI_log.md](AI_log.md) | AI usage and the seven documented corrections |

---

## Approach

### Section 1 - Data extraction

Reads the resolution-8 features out of `city-hex-polygons-8-10.geojson` (103 MB) with AWS S3
Select, so filtering happens server-side and only ~1.9 MB crosses the network. Validated
against `city-hex-polygons-8.geojson`.

Two implementation details carry most of the risk:

- **Record framing.** `SelectObjectContent` payload events do not align to record boundaries,
  so a JSON record can straddle two events. Parsing each chunk independently corrupts exactly
  those records, silently and on a small fraction of the data. The reader buffers and splits on
  the record delimiter, and raises rather than skipping anything unparseable.
- **The 1 MB record ceiling.** Querying the document as a whole would breach it. The
  `S3Object[*].features[*]` path expression streams one ~500-byte record per feature instead.

Schema conformance is scored **non-binary** in two senses: each rule contributes the *fraction*
of features satisfying it, and the aggregate is a weighted mean graded against pass/warn/fail
bands rather than one cutoff. The contract lives in
[`config/hex_schema.yaml`](config/hex_schema.yaml) as a standalone file, per the challenge's
explicit requirement.

### Section 2 - Initial data transformation

Assigns all 941,634 service requests to exactly one H3 resolution-8 hexagon, joining from
`sr.csv.gz` - **not** `sr_hex.csv.gz`, which already contains the answer and would make the
join circular. `sr_hex.csv.gz` is reserved for validation.

- **Points in two or more polygons** resolve through a strict deterministic rule: strict
  interior first, then the cell H3 itself assigns, then nearest centroid, then index order.
  Without it a one-to-many join silently duplicates service requests and inflates every
  downstream count. The rule originally led with nearest centroid; measurement showed that
  criterion disagrees with H3 for **more than half** of points within a metre of a boundary -
  the only regime the tie-break ever runs in. Full rationale in
  [docs/decisions.md](docs/decisions.md).
- **The error threshold** is calibrated against the measured baseline rather than picked as a
  round number, and applies only to genuine failures - not to the legitimate
  missing-coordinate case, which the spec mandates receives index `0`.
- **Every index is computed twice**, geometrically and via the H3 library, and disagreements
  are categorised rather than averaged away.

---

## Data quality

Both inputs have an explicit contract; neither is trusted. The service request contract
([`config/sr_schema.yaml`](config/sr_schema.yaml)) exists because the supplied data being
clean says nothing about how the pipeline behaves on a source that is not.

| Layer | Checks |
|---|---|
| Structural (fatal) | Required columns, minimum row count |
| Geometry | Ring count, self-intersection, axis order, **polygon overlap across the collection** |
| Per-column | Null-rate ceilings, ID pattern and uniqueness, coordinate ranges, timestamp parseability |
| Cross-column | Coordinate pair completeness, completion-after-creation (split by magnitude), duplicate IDs |
| Spatial | Six-class coordinate classification, inversion hard-gate, R0-R4 outcome accounting |
| Output | Dual-method agreement, C1-C5 disagreement categorisation, reference validation |

Every threshold is calibrated against a measured baseline, with the observed figure recorded
beside it in the config. Tests feed the validators **deliberately broken** data - half-populated
coordinates, a dead column, a month-backwards timestamp, a truncated extract - because testing
only against the clean supplied dataset would prove nothing about whether the checks fire.

Findings on the supplied data are in [docs/results.md](docs/results.md) and
[docs/discrepancies.md](docs/discrepancies.md). In summary: no coordinate inversion, no
null-island, no out-of-bounds; 5,483 rows (0.58%) complete before they are created, all
sub-hour and therefore clock skew rather than a logical fault; and the supplied polygons do
**not** quite achieve full coverage - three real service requests fall outside them.

---

## Performance

| Measure | Effect |
|---|---|
| Server-side filtering via S3 Select | 98.2% less data transferred; 3.8x faster than downloading and filtering |
| Streaming the S3 Select event stream | Bounded memory; the full payload is never buffered |
| Coordinate de-duplication before the join | 460,413 unique pairs from 729,270 rows - 1.58x less join work |
| Vectorised spatial predicates (shapely 2.x STRtree) | No per-row Python iteration |
| ETag-keyed download cache | Inputs are static since 2021/2022, so reruns skip the network |

Every stage is timed into `data/quality/run_manifest.json` as well as the log, so timings can
be asserted on and compared between runs.

The naive baseline deliberately **bypasses** the cache. Reading a warm cache from local disk
does not measure what the naive approach costs, and briefly made S3 Select appear 0.5x "faster"
than a baseline that never touched the network.

---

## Known constraints

**AWS S3 Select has been closed to new customers since July 2024.** Existing customers, which
includes the City's account, retain access - which is why the challenge supplies credentials
rather than expecting candidates to bring their own. Running Section 1 against a personal AWS
account will fail. The pipeline therefore requires the supplied credentials explicitly, never
falls back to an ambient profile, and detects that specific failure to report it usefully. See
[docs/discrepancies.md](docs/discrepancies.md) B1.

The upstream README also links to the **S3 Glacier Select** SQL reference in place of the S3
Select one; this implementation targets S3 Select (`SelectObjectContent`). See B2.

---

## Attribution

Forked from [cityofcapetown/ds_code_challenge](https://github.com/cityofcapetown/ds_code_challenge).
The original challenge README is preserved at [docs/upstream_README.md](docs/upstream_README.md).
Generative AI usage is disclosed in [AI_log.md](AI_log.md).
