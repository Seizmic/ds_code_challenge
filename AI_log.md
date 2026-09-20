# AI Usage Log

Disclosure of generative-AI assistance, as required by the challenge README ("log all of the
work that you asked AI assistance to undertake, including any prompts, the model used as well
number of tokens") and by the assessment brief.

**Tool:** Claude Code (Anthropic), model `claude-opus-5`
**Usage posture:** AI used for documentation drafting, requirements auditing and design
critique. All findings that depend on the actual datasets are marked as *unverified* until
executed and checked by hand.

---

## Token accounting

Token counts are reported per session. Figures are taken from the client's own usage reporting
where available and are otherwise estimates, flagged as such.

| # | Date | Session | Approx. tokens (in / out) |
|---|---|---|---|
| 1 | 2026-09-20 | Requirements audit and documentation scaffold | ~90k / ~13k *(estimated)* |
| 2 | 2026-09-20 | Environment audit, `gh` install, decisions folded into docs | ~35k / ~6k *(estimated)* |

*Running total will be updated per session. Session 1 figures are an estimate derived from
context size rather than an exact client-reported count; later entries will use exact figures
where the client exposes them.*

---

## Session 1 - 2026-09-20 - Requirements audit and documentation scaffold

### What was asked

A single briefing covering: review the emailed challenge requirements against the upstream
GitHub documentation and report discrepancies (with the brief overriding GitHub where they
conflict); identify where the calculations need optimising; propose a rule for service requests
falling at the intersection of two or more polygons so they do not produce multiple results;
assess whether the City of Cape Town has full coverage from the supplied polygons; look for
coordinate inversion and general data-quality issues; verify that `sr_hex_truncated.csv` is
genuinely a truncation of `sr_hex.csv` and contains no orphan records; and return a plan.
Explicit constraints: **write no pipeline code and retrieve no datasets**, but begin drafting
`README.md` and `AI_log.md`.

### What the AI actually did

- Fetched and read the upstream `README.md` in full.
- Queried the GitHub API for repository metadata, branches, commit history and issues.
- Ran **HEAD-only** HTTP requests against the six S3 objects to confirm availability and
  sizes. No object bodies were downloaded, honouring the "do not retrieve the datasets"
  constraint.
- Researched the current status of the AWS S3 Select API.
- Drafted `README.md`, `AI_log.md`, `docs/discrepancies.md` and `docs/decisions.md`.

### Human review still outstanding

- [ ] Verify the Cape Town bounding-box figures in `docs/discrepancies.md` D2 against an
      authoritative source. They were produced from the model's general knowledge and are
      currently marked approximate.
- [ ] Verify the ~0.737 km squared H3 resolution-8 average cell area and the ~2,446 km squared
      CoCT area used in the D4 coverage estimate.
- [ ] Confirm the S3 Select deprecation claim (B1) against current AWS documentation before
      relying on it in the submission.
- [ ] Replace the estimated token figures above with exact counts.

---

## Session 2 - 2026-09-20 - Environment audit and decisions

### What was asked

Four design decisions were given (descope the truncated-file check; run both join methods over
the full dataset and categorise the disagreements; report coverage gaps rather than failing on
them; the AI-correction example is the candidate's to write). Then: could the GitHub CLI be
installed, and what would make setup easier?

### What the AI actually did

- Audited installed tooling, git configuration and free disk space.
- Queried the PyPI API for cp314 wheel availability across the geospatial stack, prompted by
  Python 3.14.3 being new enough that wheel lag was a plausible blocker.
- Installed GitHub CLI 2.101.0 via `winget` at user scope. **Did not** authenticate it -
  that requires the candidate's own credentials.
- Recorded the decisions in `docs/decisions.md`, added the disagreement-category design, and
  wrote `docs/environment.md`.

### Human review still outstanding

- [ ] Re-confirm the cp314 wheel availability at implementation time; PyPI state can move.

---

## Corrections and improvements

The brief requires at least one documented instance where AI output was corrected.

### 1. AI self-correction during session 1 - summarised source mistaken for verbatim

The first attempt to read the upstream README used a fetch tool that returns an
*LLM-summarised* rendering of the page rather than its source. The summary was fluent and
plausible, and it silently:

- dropped the fact that the "AWS S3 SELECT" hyperlink points at the **S3 Glacier Select**
  documentation (finding B2, which only exists because the raw markdown was read);
- omitted the malformed `s3://` URI (B3);
- paraphrased the specification of the `0` sentinel, losing the precise wording that the
  ambiguity in B4 turns on;
- reported the active branch as `main` while the raw fetch had succeeded against `master`.

Auditing a document for discrepancies against a *paraphrase* of that document is
self-defeating: every finding in `docs/discrepancies.md` section B depends on exact wording.
The raw markdown was fetched instead and the audit redone against it, and the branch question
was settled properly by querying the API - `main` is the default, `master` is a stale
duplicate, and the two READMEs are byte-identical today (B8).

*Noted as a process correction. This was caught by the AI itself, so it does **not** satisfy the
brief's requirement below.*

### 1b. AI self-correction during session 2 - near-miss false alarm on wheel availability

The script written to check PyPI wheel availability matched only on CPython ABI tags
(`cp311`...`cp314`). `geopandas` and `boto3` are pure Python and ship **universal**
`py3-none-any` wheels, which carry no such tag, so the script reported them as source-only.
Taken at face value this would have produced a confident and wrong warning that two core
dependencies had no wheels for Python 3.14. Caught on re-inspection and verified with a second
query before anything was reported.

Worth recording because it is the more dangerous failure mode: not a visibly wrong answer, but
a plausible one produced by a subtly wrong test.

*Also caught by the AI, so this too does **not** satisfy the requirement below.*

### 2. Correction by the candidate

> **TO BE COMPLETED BY NAVEEN.**
>
> The brief requires an example where *you* corrected the tool's output. This must be a real
> correction made during implementation, and it cannot be written on your behalf without
> defeating the purpose of the requirement - the assessors have said they read this section and
> that critical use counts in the candidate's favour.
>
> Good candidates are likely to surface during Sections 1 and 2. Record: what the AI produced,
> what was wrong with it, how you found out, and what you changed it to.
