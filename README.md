<img src="img/city_emblem.png" alt="City Logo"/>

# City of Cape Town - DS Code Challenge: Sections 0-2

Response to the [City of Cape Town Data Science Unit code challenge](https://github.com/cityofcapetown/ds_code_challenge).

**Scope: Sections 0 (setup), 1 (data extraction) and 2 (initial data transformation) only.**
Sections 3-6 are deliberately out of scope, as directed by the brief - their omission is
intentional, not incomplete work.

> **Status: planning and documentation. No pipeline code has been written yet.**
> This README describes the intended design. Sections marked *(planned)* are not yet
> implemented, and the run instructions will not work until they are. See
> [docs/plan.md](docs/plan.md) for the execution schedule.

---

## Contents

| Document | What it covers |
|---|---|
| [docs/discrepancies.md](docs/discrepancies.md) | Audit of the brief against the upstream README; documentation defects; planned data-quality checks |
| [docs/decisions.md](docs/decisions.md) | The multi-polygon tie-break rule and the join error threshold, with motivation |
| [docs/plan.md](docs/plan.md) | Execution plan and time budget |
| [docs/environment.md](docs/environment.md) | Prerequisites, machine audit, setup steps |
| [AI_log.md](AI_log.md) | AI tool usage, as required by the challenge |

---

## Quick start *(planned)*

Requires **Python 3.11 or newer** (developed and tested on 3.14).

```bash
pip install -r requirements.txt
python -m src.main
```

A single entrypoint runs end to end with no human interaction, as the challenge requires.
Input data is downloaded automatically and cached under `data/raw/`; reruns reuse the cache.

**Credentials.** The challenge supplies dummy AWS credentials, fetched automatically at
runtime. The pipeline deliberately **does not** fall back to an ambient AWS profile or to
`AWS_*` environment variables - see [Known constraints](#known-constraints) for why that
matters more than it looks.

---

## Repository layout *(planned)*

```
.
├── README.md
├── AI_log.md
├── requirements.txt
├── config/
│   └── hex_schema.yaml          # Section 1 target schema (standalone, as required)
├── src/
│   ├── main.py                  # single end-to-end entrypoint
│   ├── config.py
│   ├── logging_setup.py
│   ├── s3_io.py                 # S3 Select + cached downloads
│   ├── extract_hex.py           # Section 1
│   ├── transform_join.py        # Section 2
│   ├── validation.py            # schema conformance + reference comparison
│   └── quality_checks.py        # coordinate inversion, coverage, bounds
├── tests/
├── data/                        # gitignored; raw / interim / processed / quality
└── docs/
```

---

## Approach

### Section 1 - Data extraction

Read the resolution-8 features out of `city-hex-polygons-8-10.geojson` (**108.3 MB**) using
AWS S3 Select, so that filtering happens server-side and only the resolution-8 subset
(**~1.97 MB**, a **~98% reduction**) crosses the network. Validate the result against
`city-hex-polygons-8.geojson`.

Schema conformance is scored **non-binary**: rather than pass/fail, each rule contributes a
weighted component (required fields present, types correct, H3 indices well-formed and
parseable at the right resolution, geometry valid, coordinates in range), producing a score in
`[0, 1]` against a documented threshold. The target schema lives in `config/hex_schema.yaml`
as a standalone file, per the challenge's explicit instruction.

Reported metrics: wall time, `BytesScanned` and `BytesReturned` from the S3 Select `Stats`
event, peak memory, and the reduction ratio against a naive full-download baseline.

### Section 2 - Initial data transformation

Assign every service request to exactly **one** H3 resolution-8 hexagon, validating against
`sr_hex.csv.gz`. Records with empty `Latitude`/`Longitude` receive index `0`, as specified.

Two design points carry the weight here, both detailed in
[docs/decisions.md](docs/decisions.md):

- **Points falling in two or more polygons** resolve through a strict, deterministic rule
  (interior-first, then nearest-centroid, then index order). Without this, a one-to-many join
  silently duplicates service requests and inflates every downstream count. Occurrences are
  summarised in the logs and written in full to a reviewable side-car dataset under
  `data/quality/`.
- **The join error threshold** is calibrated against the measured baseline rather than picked
  as a round number, and is applied only to genuine failures - not to the legitimate
  missing-coordinate case.

Each index is computed twice, by geometric join and by the H3 library directly, and the
agreement rate between the two routes is reported as a validation artifact.

---

## Performance

Optimising latency and resource use is an explicit requirement of both sections. Planned
measures:

| Measure | Rationale |
|---|---|
| Server-side filtering via S3 Select | Avoids transferring 108 MB to extract ~2 MB |
| Streaming the S3 Select event stream | Bounded memory; avoids buffering the full payload |
| Coordinate de-duplication before the spatial join | Joins only *unique* coordinate pairs, then broadcasts back. **Measured: 460,413 unique pairs from 729,270 rows — 1.58x less join work.** Worth keeping, but a smaller win than anticipated; the headline saving is Section 1's transfer reduction, not this. |
| Vectorised spatial predicates (shapely 2.x STRtree, built once) | Avoids per-row Python iteration |
| Column pruning and explicit dtypes when reading the SR data | Reduces parse time and memory |
| ETag-keyed on-disk caching | Inputs are static since 2021/2022, so reruns skip the network entirely |

Every stage is timed, and timings land in the run manifest rather than only in the logs.

---

## Known constraints

**AWS S3 Select has been closed to new customers since July 2024.** Existing customers, which
includes the City's account, retain full access - which is precisely why the challenge supplies
credentials rather than expecting candidates to bring their own. Running Section 1 against a
personal or newly created AWS account will fail. The pipeline therefore requires the supplied
credentials explicitly and fails with a clear message rather than silently picking up a local
profile. See [docs/discrepancies.md](docs/discrepancies.md) B1.

The upstream README also links to the **S3 Glacier Select** SQL reference in place of the S3
Select reference; this implementation targets S3 Select (`SelectObjectContent`). See B2.

---

## Attribution

Forked from [cityofcapetown/ds_code_challenge](https://github.com/cityofcapetown/ds_code_challenge).
Generative AI usage is disclosed in [AI_log.md](AI_log.md).
