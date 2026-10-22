# **Contributing**

Everything you need to develop, test, and release this library.

> **See also:** [Usage](usage.md) · [API Reference](api/index.md) · the repository's root
> `CONTRIBUTING.md` holds the authoritative branch/PR and commit-message policy.

---

## Setting up for development

The project ships both a `Makefile` and a parallel `tasks.sh`, so use whichever suits your
machine — **`bash bin/venv.sh`**.

```bash
bash bin/venv.sh        # create the Poetry venv + install deps
bash bin/ensure_env.sh  # seed .env from .env.example
bash bin/precommit.sh   # install the git hooks
```

`init` composes `ensure_env` (seed `.env`), `venv` (create the Poetry virtualenv, install **all**
dependencies including dev + docs), and `precommit` (install the git hooks). Poetry is
auto-installed if missing.

## Tests and linting

```bash
poe unit_tests          # poetry run pytest tests/unit/
poe integration_tests   # poetry run pytest tests/integration/
poe lint                # ruff + mypy + codespell + pydocstyle + shell/sql/yaml gates
```

CI runs the same gates on every pull request; keep them green locally before pushing.

## Verifying the built package

Before opening a release PR, confirm the wheel actually builds and imports — this catches
packaging mistakes (a missing `__init__`, an unshipped `_internal/` subpackage) that source-tree
tests never surface:

```bash
poe install_dist_locally    # python -m build → install → smoke-import → report the built wheel
```

## Publishing the documentation (versioned, via mike)

The published site is **versioned**: a consumer pinned to an older release reads *that
release's* docs, not HEAD. [mike](https://github.com/jimporter/mike) maintains the version tree
on the `gh-pages` branch and MkDocs-Material renders the version dropdown.

Two workflows split the work:

| Workflow | Trigger | What it does |
|---|---|---|
| `Docs - Strict Build Check` (`docs.yaml`) | every push + PR | `mkdocs build --strict` only — catches broken links/nav before a release. **Never deploys.** |
| `Release to PyPI` (`release-pypi.yaml`) | manual release | after the PyPI publish succeeds, deploys the released version with `mike deploy --update-aliases <X.Y> latest` |

Because the deploy runs **after** publishing, the site only ever advertises versions that
actually shipped. Notes:

- **Granularity is `X.Y`** — `1.4.2` and `1.4.7` share the `1.4` entry; the `latest` alias
  always tracks the newest release and is the default landing version.
- **Prereleases never move `latest`** — a version with a suffix (`1.2.3rc1`) builds and
  publishes, but the docs deploy job is skipped.

### One-time Pages setup

mike serves from the **`gh-pages` branch**, so Pages must be set to *Deploy from a branch →
gh-pages*. The workflow's `GITHUB_TOKEN` cannot change that (it is a GitHub App token without
repo-admin rights), so do it with your own `gh` auth:

```bash
poe enable_pages
```

This already runs inside `poe init` (after bootstrap), and is **idempotent and
non-blocking** — it warns and continues if `gh` is absent/unauthenticated, no remote resolves,
or you are not a repo admin (a fork), so it never breaks `init`.

**Ordering matters:** the `gh-pages` branch does not exist until the first release deploy
creates it. Until then `enable_pages` deliberately leaves Pages untouched (so the site is never
pointed at an empty branch) and tells you to re-run it. So: cut the first release, then run
`poe enable_pages` once. Manual alternative: *Settings → Pages → Build and deployment →
Source: Deploy from a branch → `gh-pages` / `/`*.

## Pull requests

1. Branch off the default branch following the prefix policy (`feat/…`, `fix/…`, …).
2. Fill out the PR template completely.
3. Ensure the CI checks (tests, lint, docs build) pass — they are the merge gate.

## Releasing

Releases are **tag-driven and secret-free** when the project is connected to a GitHub remote:

- The version is the **git tag** (via `poetry-dynamic-versioning`); `pyproject.toml` holds a
  `0.0.0` placeholder. Do not hand-edit it. Trigger a release from the Actions tab
  (`Release to PyPI` / `Release to Test PyPI`, `workflow_dispatch` with the version), or by pushing
  a `vX.Y.Z` tag.
- The release workflow runs the **full test suite** as a hard gate, builds with `python -m build`,
  and publishes via **OIDC trusted publishing** (`pypa/gh-action-pypi-publish`) — no stored
  `PYPI_TOKEN`.
- The changelog is regenerated from tags at release/build time (`poe changelog` locally); CI never
  commits `CHANGELOG.md` back to the protected default branch.

### Maintainer setup — trusted publisher (one time, before the first release)

Register a **trusted publisher** on **both** [pypi.org](https://pypi.org) and
[test.pypi.org](https://test.pypi.org). Every claim must match the workflow exactly or the upload
fails with an opaque `invalid-publisher`:

| Claim | Value |
|-------|-------|
| Owner / repository | your GitHub `<owner>` / `<repo>` |
| Workflow filename | `release-pypi.yaml` (PyPI) / `release-test-pypi.yaml` (Test PyPI) |
| Environment | `release-pypi` / `release-test-pypi` |
| PyPI **Project Name** | must equal the distribution name (`name` in `pyproject.toml`) |

The GitHub Release step exists only in `release-pypi.yaml`, not in the Test PyPI workflow, so a change there is never rehearsed; diff the two workflows when editing either.

For the very first upload the project does not exist yet — register a **pending publisher** at the
account level (not under an existing project's settings). Publishing from a laptop instead of CI is
the one case that still needs an API token; OIDC works only from GitHub Actions.

### Choosing publish targets

The scaffold wires the release workflows for the official public registry (PyPI) and a staging
registry (Test PyPI). To publish to a **private / non-official** source instead — a git source
(`pip install git+https://…`), a private PEP 503 index, or (for ecosystems that support it) GitHub
Packages — wire the consumer-side source in `pyproject.toml` with an explicit-priority guard
against dependency confusion (`poetry`'s `priority = "explicit"`; `pip --index-url`, never
`--extra-index-url`).

## Branding the docs site

The scaffold ships a **placeholder** brand image at `docs/assets/logo.png`, wired as the header
logo/favicon (`theme.logo` / `theme.favicon` in `mkdocs.yml`) and as the landing hero on
`docs/index.md`. To brand your site:

1. Replace `docs/assets/logo.png` with your own asset (keep the filename, or update the two
   `mkdocs.yml` paths and the `<img>` in `docs/index.md`).
2. Tune size, position and border inline on the `<img>` — `width="200"` (scale),
   `align="right"` (position) and `style="border-radius: 15px;"` (rounded) — in `docs/index.md`.

## Repository protection & security (one-time, scripted)

`poe init` runs three admin-gated helpers. They are **idempotent and non-blocking**: without
`gh`, without auth, without a GitHub remote, or without repo-admin rights they warn and skip, so
`init` still completes for contributors and offline scaffolds. Re-run any of them alone later:

| Target | What it provisions |
|--------|--------------------|
| `poe enable_pages` | GitHub Pages source (gh-pages branch for versioned docs, else Actions) |
| `poe enable_repo_rules` | The `pr-quality-gate` branch ruleset + the merge settings the PR gate needs |
| `poe enable_security` | Private vulnerability reporting, Dependabot alerts, Dependabot security updates |

### The `pr-quality-gate` ruleset

Applied to `~DEFAULT_BRANCH` (that ref survives a branch rename), looked up **by name** so a
re-run updates in place instead of creating a duplicate:

| Rule | Setting | Why |
|------|---------|-----|
| `pull_request` | `required_approving_review_count: 0` | ⚠️ **Must be 0.** GitHub forbids approving your own PR, so any value ≥ 1 locks a solo maintainer out of merging their own work. Zero still forces every change through a PR — that is the real guardrail. |
| `pull_request` | `required_review_thread_resolution: true` | Makes review comments **binding**: an unresolved thread blocks the merge instead of being decorative. |
| `code_scanning` | CodeQL, security `high_or_higher`, alerts `errors` | Alerts stay at `errors`: `errors_and_warnings`/`all` start blocking merges on stylistic queries, duplicating ruff/mypy with noise. |
| `copilot_code_review` | `review_on_push: true` | Its **own rule type** — not a `pull_request` parameter (that returns HTTP 422 and makes the feature look UI-only). |
| `non_fast_forward`, `deletion` | on | No force-push, no branch deletion on the default branch. |
| `required_status_checks` | **empty by default** | ⚠️ Deliberate. A required check whose name never reports blocks **every** PR forever. Populate `REQUIRED_CHECKS` in `bin/enable_repo_rules.sh` from a real PR — `gh api repos/:owner/:repo/commits/<sha>/check-runs --jq ".check_runs[].name"` — then re-run. |

**Deliberately not enabled:** *Require code quality results* (subjective AI severity on the merge
path — ruff, mypy and the `bin/check_*.py` gates already enforce quality deterministically) and
*Restrict code coverage* (preview; the floor is single-sourced in `.coveragerc` `fail_under`).

### Automatic vs manual — the boundary is repo config vs account plan

**Nothing here needs a click.** Every *repository* setting above is scripted. What is **not**
scriptable is your *account's* entitlement: the `copilot_code_review` rule only fires if the author
has access to Copilot code review, and **code review is not part of Copilot Free**. Without a
qualifying plan the rule sits correctly configured and **inert** — no review appears and nothing
errors. That silence is the trap, because the ruleset JSON looks perfect either way.

Every other rule (PR required, CI green, CodeQL clean) works regardless of any Copilot plan, so
the ruleset is worth applying unconditionally. Copilot Pro is free for verified students,
teachers and popular-OSS maintainers.

> Do **not** diagnose this with `gh api user/copilot_billing` → 404: that endpoint is for
> org/enterprise seat management and 404s for a personal account even when Copilot Free is active.

### Security

`SECURITY.md` at the repo root is auto-detected by GitHub (no API call) and flips *Security
policy* to Enabled; `poe enable_security` turns on the matching private-reporting intake plus
Dependabot alerts and security updates. Ordinary version bumps are separate — see
`.github/dependabot.yml`, which uses `versioning-strategy: lockfile-only` so it refreshes
`poetry.lock` (keeping CI honest about what consumers install) without ever rewriting your
`pyproject` ranges.

## Automated PR flow (the quality gate)

Every PR is classified by `bin/pr_gate.py` (workflow `pr-gate.yaml`), which labels it, posts one
sticky comment with a per-axis status table, and hands the **safe classes** to GitHub's native
auto-merge. Two rules are the whole design:

**Classified by PATH, never by diff size.** The dangerous change is *semantic*, not big: a
one-character edit to a schema/contract constant is the smallest possible diff and the most
dangerous — and every test still passes, because the tests assert the contract that was written.
So size never decides eligibility; the changed paths do. (The one place size still matters — an
`XL` diff is vetoed — is **waived for a lockfile-only diff**, whose line count tracks how many
dependency hashes moved, not risk.)

| Risk class | Paths | Auto-merge? |
|------------|-------|-------------|
| `src` | `src/` | ❌ defines what "passing" means |
| `tests` | `tests/` | ❌ defines what "passing" means |
| `other` | anything unmatched | ❌ unknown = unsafe (default-deny) |
| `ci` | `.github/`, `bin/`, `Makefile`, `tasks.sh`, `.pre-commit-config.yaml` | ✅ |
| `deps` | `pyproject.toml`, `poetry.lock`, `requirements.txt` | ✅ (the test suite is the gate) |
| `docs` | `docs/`, `mkdocs.yml`, `README.md`, `CHANGELOG.md`, … | ✅ |

**Consent is opt-OUT.** The safe classes auto-merge with **no label**; add `do-not-merge` to force
a human merge. Native auto-merge **bypasses nothing** — GitHub holds the merge until every required
check of the ruleset is green, so the gate only decides *eligibility*, never *whether it passed*.

Edit the risk table (the `RISK_PATHS` constant) in `bin/pr_gate.py` for your project's real layout.

### ⚠️ After changing gate policy, backfill the open PRs

The gate runs on `pull_request` events, so a PR that was **already open** when you change the
policy (the classification/consent rules in `pr_gate.py`, or `allow_auto_merge` /
`delete_branch_on_merge`) is **never re-evaluated** — it keeps the labels and auto-merge state it
got under the old rules until some new event touches it. That is not a bug; the gate simply never
ran again. So after merging a policy change, run the backfill:

```bash
gh workflow run pr-gate.yaml -f backfill=true   # re-evaluates every open PR
# for a Dependabot PR, `gh pr comment <n> --body "@dependabot rebase"` also works
```

### Bot-merged PRs and the reconciler

A PR merged by **native auto-merge** (a bot action) does **not** close its linked issue and does
**not** delete its branch, even with `delete_branch_on_merge` on — bot-performed actions are
deliberately inert to prevent automation recursion. `pr-reconcile.yaml` fixes both: it closes the
`Closes #N` issues and deletes the head branch of merged PRs. Its **scheduled daily run is the
actual fix** — scheduled events are exempt from the "no new workflow runs" suppression that also
swallows the fast `pull_request: [closed]` path for a bot merge. Latency is up to one day; that is
the accepted cost of not needing a personal access token.

### The work-ledger gate

`bin/check_backlog_ledger.py` (pre-commit + CI) fails a branch that touches `src/` or CI paths but
adds no `.specs/backlog/<kebab>_YYYYMMDD_HHMMSS.md` ledger with a `- [ ]` checklist — making the
per-branch work-ledger convention structural instead of a thing you remember. Routine
docs/deps/tests-only branches need none.
