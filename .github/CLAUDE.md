# `.github/` — CI and recurrent automation

Guidance for Claude Code and contributors working in this project's `.github/`.

## What ships by default

The scaffold ships **event-driven** CI only — workflows triggered by `push` and
`pull_request`. Nothing here runs on a clock. That is deliberate: a scheduled
job runs whether or not anyone needs it, costs runner minutes, and can fail
silently long after the person who added it has moved on.

**Add a time-triggered job only when the project genuinely needs one, and write
down *why* in the workflow file.**

## Recurrent (scheduled) workflows

To run a workflow on a schedule, add an `on.schedule` trigger with a cron
expression:

```yaml
on:
  schedule:
    - cron: '0 3 * * 1'   # 03:00 UTC every Monday
  workflow_dispatch: {}    # also allow a manual run from the Actions tab
```

Gotchas that bite people:

- **Cron is UTC**, always — not your local timezone. Convert deliberately.
- **Minimum granularity is 5 minutes**; anything finer is rejected.
- **Runs can be delayed** (sometimes by many minutes) when GitHub's runner pool
  is busy — never rely on exact timing.
- **Scheduled workflows auto-disable after ~60 days of repository inactivity**
  (no pushes). They resume only when someone pushes or re-enables them.
- Always pair `schedule` with `workflow_dispatch` so you can trigger a run
  on demand without waiting for the next tick.

Common legitimate uses: nightly end-to-end tests, a scheduled CodeQL / security
scan, a stale-issue/PR bot, cache warming, scheduled data refresh.

## Dependency updates (Dependabot)

Dependabot version updates are a worked example of "recurrent automation". They
live in `.github/dependabot.yml`, and the `schedule.interval` key is
**mandatory** — there is no manual-only cadence. Pick one:

- `daily` — fast-moving app with active maintainers watching the PR queue.
- `weekly` — the typical default.
- `monthly` — low-churn project or a stable library.

```yaml
version: 2
updates:
  - package-ecosystem: "npm"          # "pip" for Python projects; also "docker", "gomod", …
    directory: "/"
    schedule:
      interval: "weekly"              # daily | weekly | monthly — choose per project
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
```

### Want updates with no cadence?

Enable **Dependabot security updates** instead — they are *event-driven* (a PR
opens only when a CVE advisory matches a dependency), need **no**
`dependabot.yml`, and run on no schedule at all. Turn them on in
*Settings → Code security → Dependabot*, or via the API:

```bash
gh api -X PUT repos/{owner}/{repo}/vulnerability-alerts
gh api -X PUT repos/{owner}/{repo}/automated-security-fixes
```

## Publishing packages — prefer OIDC / trusted publishing over stored tokens

When a release workflow publishes a package to a registry, default to the registry's **OIDC /
trusted-publishing** flow — **never** a stored long-lived API token committed as a secret. The
principle is registry-agnostic; only the concrete action differs:

| Ecosystem | OIDC / trusted publishing |
|-----------|---------------------------|
| Python (PyPI / Test PyPI) | `pypa/gh-action-pypi-publish@release/v1`, no `password:` |
| npm | trusted publishing (2025) + `--provenance` |
| Rust (crates.io), RubyGems | trusted publishing (OIDC) |
| Go | no token at all — publishing is a signed VCS tag |

Rules:

- Set `permissions: id-token: write` on the publish job and bind it to a **GitHub Environment**
  (per-index, self-documenting: `release_pypi`, `release_test_pypi`, `release_npm`, …).
- **Never commit a long-lived token.** Fall back to a short-lived scoped token **only** where the
  registry/CI lacks OIDC (trade-off: OIDC works only from CI — keep a token if you must publish
  from a laptop).
- The trusted publisher's claims (owner, repo, **exact workflow filename**, environment) and its
  registered project name must match the running workflow, or the upload fails with an opaque
  `invalid-publisher`. Register a *pending publisher* before the first release.

Why: no long-lived secret to store, leak, or rotate; the upload token is short-lived and bound to
this repo/workflow/environment. This is each registry's own recommended path.

## Gate parity — every gate in BOTH pre-commit and CI

CI runs its gates as **explicit steps** in `tests.yaml`, not via `pre-commit run`, so adding a
hook to `.pre-commit-config.yaml` does **not** cover CI. Every lint/static/test gate must be
wired into **both** files, in the same change — otherwise a `--no-verify` commit or an
uninstalled hook slips straight past branch-protection CI (which runs the workflow, not local
hooks). The gate set that must stay mirrored: `ruff check`, **`ruff format --check`** (distinct
from `ruff check`), `mypy`, `check-docstrings`, **`check-typing`**, the shell/sql/yaml lints,
unit + integration tests, and the **coverage floor**.

- **Single-source the coverage floor.** `.coveragerc` `[report] fail_under` is the one value;
  pre-commit's `coverage-check` and the CI `Run Coverage Gate` both read it — never duplicate a
  `--cov-fail-under=NN` literal. The CI coverage gate runs on **every** PR (the badge step is
  main/tags-only, so without it a PR could drop below the floor uncaught).
- **Version-floor consistency.** `requires-python`, `ruff target-version`, `mypy.ini
  python_version`, and the CI `python-version` matrix must all agree. Pin mypy's `python_version`
  to the **floor** (not the newest) so a too-new construct fails locally, not only on the CI
  floor leg. Derive the matrix from `requires-python` — no leg below the floor.

## Validating CI locally with `act`

`act` runs the workflow in a local Docker container — a fast loop for the legs it can run,
complementary to (not a replacement for) pushing so the full matrix runs on GitHub's runners.

- It only runs **Linux** — narrow every invocation with `--matrix os:ubuntu-latest`; let
  GitHub cover the `macos`/`windows` legs.
- Validate the **risky single leg**, not the whole matrix — e.g. a newest-Python leg where a dep
  may lack wheels: `act --matrix os:ubuntu-latest --matrix python-version:3.14 -j test`.
- **Docker Desktop on Linux** puts its socket at `~/.docker/desktop/docker.sock` — export
  `DOCKER_HOST=unix://$HOME/.docker/desktop/docker.sock` or `act` reports the daemon is down.

## Kanban board and labels

If you accepted the scaffolder's offer, the repo has a `<repo> kanban` GitHub Project and the
house labels (`type:*`, `hitl`, `afk`, `oracle:*`, `do-not-merge`, `state:blocked`). `Estimate`, `Size` and
`Priority` are project fields, not labels. The board's views and workflows have no public API:
enable auto-add and "item closed -> Done" in the project's Workflows page.

## Blocked work

Work that cannot start because an upstream is unfinished carries the `state:blocked` label and a
`**Blocked by:**` line at the start of a body line, naming each blocker as `repo#N`, or as
`decision: <why>` when the blocker is a choice nobody has made yet. `ISSUE_TEMPLATE/feature_or_fix.md`
carries the line and an `issue-template-guard:` directive; a tool that reads the directive rejects a
`state:blocked` issue without the line. A `decision:` blocker is never auto-cleared by a reconciler.

Use the native `blocked_by` relationship as an extra mirror for same-repo blockers; it cannot name
a blocker in another repository, so the body line is the record.

If you accepted the scaffolder's board, it has the `state:blocked` label, a `Blocked` Status option
(first, before `Backlog`) and a `Blocker` field (`Internal | External | Decision`). **A board you
created yourself has none of these: add them by hand.** When you add `Blocked` to an existing
board, send every existing option with its `id` (`updateProjectV2Field` replaces the whole set
and mints a new option for any without one, leaving every item's Status empty), and snapshot the
board to JSON first.

The scaffold ships no reconciler that clears a `Blocked` item when its blocker closes; that is
operator tooling, not project code.
