# Environment & Setup

Audit of this machine against what Sections 0-2 need. Performed 2026-09-20.

---

## Machine audit

| Tool | Status | Note |
|---|---|---|
| git | 2.48.1 | OK |
| **gh** | **2.101.0** | **Installed 2026-09-20** via `winget`, user scope. Not yet authenticated. |
| Python | **3.14.3** | See below - checked, and it is fine |
| pip | 26.1.1 | OK |
| winget | 1.29.290 | OK |
| Docker | 29.2.1 | Available, not required |
| make | missing | Not required - use a `run.ps1` / `run.sh` entrypoint instead |
| conda / uv / choco / scoop | missing | Not required |
| Free disk | 38 GB | Ample; the pipeline needs roughly 2 GB including intermediates |

---

## Python 3.14 - checked, no blocker

Python 3.14 is recent enough that the geospatial stack was worth verifying rather than
assuming. Current PyPI state:

| Package | Latest | cp314 wheel? |
|---|---|---|
| shapely | 2.1.2 | Yes |
| h3 | 4.5.0 | Yes |
| pyarrow | 25.0.1 | Yes |
| pandas | 3.0.6 | Yes |
| numpy | 2.5.3 | Yes |
| pyproj | 3.8.0 | Yes |
| geopandas | 1.1.4 | Pure Python (`py3-none-any`) |
| boto3 | 1.43.98 | Pure Python (`py3-none-any`) |

Every compiled dependency publishes a cp314 wheel, so nothing builds from source. **No version
downgrade is needed.**

### The real version risk is the assessors' machine, not ours

The challenge is explicit: *"If your repo does not clone and run, we will not attempt to fix
it."* Whatever we build has to run on **their** interpreter, which is unlikely to be 3.14.
Mitigations:

- Target **Python >= 3.11** in code, and declare it in `README.md` and `pyproject.toml`.
- Pin `requirements.txt` to exact versions, but avoid syntax or stdlib behaviour that is 3.14-only.
- `pandas 3.0` and `numpy 2.x` both carry breaking changes from the 1.x/2.x era - pin them
  explicitly so the assessors resolve the same versions we tested against, rather than whatever
  their cache happens to hold.

---

## What is blocked on you

### 1. Authenticate the GitHub CLI

This is the only hard blocker. It is an interactive flow against your own credentials and
cannot be done from this session.

```bash
gh auth login
```

Choose *GitHub.com* then *HTTPS*, and authenticate in the browser. Then confirm:

```bash
gh auth status
```

**Note:** `gh` was added to `PATH` by the installer, but an already-open shell will not see it.
Open a **new** terminal first.

### 2. Set your git identity - currently unset

`user.name` and `user.email` are **not configured**. The challenge grades commit history
("committing regularly with clear, meaningful commit messages"), so commits must be attributed
correctly. Without this, git either refuses to commit or invents a local identity like
`Navee@DESKTOP-...(none)`, and the commits will not link to your GitHub profile.

```bash
git config --global user.name "Naveen Rajhkoomar"
git config --global user.email "you@example.com"
```

Use the email **associated with your GitHub account** - if your address is private, use the
`@users.noreply.github.com` address GitHub provides, otherwise the commits will not be
attributed to you on the fork.

### 3. Confirm the fork name

Default is `ds_code_challenge`, matching upstream. Say if you want something else.

---

## Setup, once the above is done

Fully scriptable from here:

```bash
gh repo fork cityofcapetown/ds_code_challenge --clone --remote
```

Then, in the clone:

```bash
py -3.14 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

The four drafted documents move into the clone, and the upstream README is preserved as
`docs/upstream_README.md` so the discrepancy register stays auditable against the exact text it
was written from.

---

## Things you do *not* need

- **An AWS account.** The challenge supplies credentials, and the pipeline fetches them at
  runtime. Do **not** configure a personal AWS profile - S3 Select is closed to new customers,
  so a personal account would actively break Section 1. See `discrepancies.md` B1.
- **Docker.** Available, but adds friction for assessors who then need to build an image.
- **`make`.** A plain script entrypoint is more portable across their machines anyway.
