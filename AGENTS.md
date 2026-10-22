# AGENTS.md

Guidance for agents working in this repository.

## Engineering principles

Read `PRINCIPLES.md` for the single-responsibility and function-design rules this project follows.

## Shared conventions

The boundary rules, data-handling guardrails, runtime type-checking notes, naming and
file-naming conventions, tooling summary and the project-memory rule are shared by every
BlueprintX skeleton and live in `.claude/CLAUDE.md` (single source:
`templates/common/CLAUDE.md`). Read that file before editing code: only Claude Code
loads it on its own, other agents must be told to. This file keeps only what is
specific to this skeleton.

⚠️ The shared boundary rule 1 (the seam knows the vendor) has one tier-specific twist here:
a caller imports the seam **package-qualified** —
`from <project_name>._internal.utils.http_downloader import download_file` — never a bare
`from utils…`, which resolves only by accident of `sys.path` and breaks once the wheel is
installed.

## What this template is

A **PyPI-ready Python library starter**. A clean, importable package with CI, pre-commit,
tests, docs, and PyPI + Test-PyPI release workflows ready to go. It is scaffolded by
BlueprintX into a new project directory; the scaffold replaces the `<project_name>` package
directory and the `pyproject.toml` placeholders via `envsubst`.

## Layout

```
src/<project_name>/
    __init__.py            # the public API surface (control it with __all__)
    main.py                # library core / entry point — rename or split as it grows
    _internal/             # PRIVATE — ships in the wheel, but not a public API
        utils/             # vendored helpers (dtypes, tabular_reader, retry/, http_downloader,
                           #   text, zip_extractor, br_identifiers, typing/)
        config/            # ALL private structural declarations (one config/CLAUDE.md maps them)
            contracts/     # FileContract declarations (one per input source)
            ports/         # private behavioural ABCs (hexagonal ports; ABCTypeCheckerMeta) — opt-in
            # schemas/     # (opt-in) Pydantic models mirroring an external standard
tests/
    unit/  integration/  performance/
```

**Public vs private.** Consumers import `<project_name>` (your core). Everything under
`<project_name>._internal` is vendored support code: it ships inside the wheel (so imports
resolve after `pip install`), but the leading underscore marks it off-limits — keep it out
of your public `__all__`. The internal imports are package-qualified
(`from <project_name>._internal.utils.dtypes import …`).

## Architecture

- **One public class per module/file.** The public class is named after the file
  (`user_service.py` → `UserService`). When helpers share no state and need no lifecycle,
  prefer **module-level functions** over a utility class. A private/shared base class gets
  its **own** `_`-prefixed file (`_base_reader.py`) — never share a module with a public
  class.
- **Separate I/O from logic**: pure functions in the core, side effects at the edges.
- Reach for a class only when there is **state + lifecycle**, **interface conformance**, or
  **dependency injection** — otherwise a module of functions is the right shape.
- **No redundant package-name subfolder.** When the package's whole purpose is one domain
  (e.g. `calendars`), do **not** nest a subfolder that repeats the package name
  (`src/<project_name>/<project_name>-ish/`) — the package name already conveys the scope. Keep
  public modules **flat** at `src/<project_name>/` (`src/<project_name>/calendar_br.py`), and put
  non-exported abstract bases / internals under `_internal/`.
- **On migration, reuse the target's own implementation.** When lifting code in from another
  repo, if this project already has an equivalent module (its own `_internal` typing engine, a
  helper), rewrite the imports to **this** project's version and discard the source's duplicate —
  never vendor a second copy (DRY). The scaffold's own `rewrite_internal_imports` embodies this.

## Conventions (inherited from `templates/python-common/`)

- **Ruff**: linter + formatter. Line-length 99, 4-space indent, double quotes, NumPy docstrings.
- **Pre-commit**: ruff, pydocstyle, codespell, commitizen, gitlint, unit + integration
  tests, coverage badge.
- **Tests**: `pytest` — `poe unit_tests`. Write
  pytest-style functions with fixtures, not `unittest.TestCase`.
- **Explicit column typing & Brazilian identifiers** — if the library touches pandas, type
  every DataFrame on load via `apply_dtypes` (`_internal.utils.dtypes`, never pandas'
  inference), route reads through `_internal.utils.tabular_reader`, and use
  `_internal.utils.br_identifiers` for CNPJ/CPF (alphanumeric-aware for the 2026 CNPJ).
- **No `.env`** — a distributable library has no runtime env to seed (unlike the service
  tiers), so none is shipped. This does not block the opt-in OTLP log exporter
  (`_internal/utils/otel_logging.py`, blueprintx#438): it reads
  `OTEL_EXPORTER_OTLP_ENDPOINT` etc. from the **consumer's own process environment** at call
  time — the same "the host configures the env, the library ships no file" pattern
  `ts_lib.sh` already uses. `configure_otel_logging(logger)` is injected, never auto-run on
  import, matching the dependency-injection rule below.
- **Logging via dependency injection** — never hard-import a logging backend in a helper;
  inject a logger (stdlib default), as `_internal/utils/retry/log_emitter.py`'s `LogEmitter`
  shows. The
  in-repo `logs.py` helper is **opt-in** at scaffold time; see `_internal/utils/CLAUDE.md`.
- **Every imported package is a direct dependency.** If a module `import`s a package, declare
  it in `pyproject.toml` — even when it is already installed transitively via another dep. A
  transitive presence is an accident of another package's tree and breaks silently the day that
  package drops or version-caps it. Run `poetry add <pkg>` for anything you import.

  **This is now enforced, not advised**: `bin/lint_deps.sh` runs `deptry` over `src/` in
  `poe lint`, the `lint-deps` pre-commit hook and CI. Its first run found the rule already
  broken in the tiers that ship it, which is the argument for the gate — the DDD tiers imported
  pandas in five `utils/` modules while declaring it nowhere, reaching them only through a
  business-day calendar that happens to depend on it. Two things worth knowing before working
  around it:

  - **A guarded import is still an import.** `try: import numpy / except ModuleNotFoundError:`
    degrades gracefully at runtime and changes nothing about the declaration — that pattern is
    why `numpy` went undeclared for as long as it did.
  - **Configuration lives in `pyproject.toml`'s `[tool.deptry]` block, never in a shared
    `deptry.toml`.** deptry takes its dependency list from the same file it takes its settings
    from, so `--config <other>` silently re-points it at a manifest that declares nothing.

## Releasing to PyPI

Two workflows ship under `.github/workflows/` (present only when a GitHub remote is set up):

- `release-test-pypi.yaml` — publish to **Test PyPI** first (`workflow_dispatch`).
- `release-pypi.yaml` — publish to **PyPI**, cut a GitHub release, then deploy the **versioned
  docs** with `mike deploy --update-aliases <X.Y> latest` (skipped for prereleases, so a suffixed
  version never moves `latest`).

Both validate the `version` input before anything else runs: `X.Y.Z`, optionally followed by a
PEP 440 pre/post/dev suffix (`1.2.3`, `1.2.3rc1`, `1.2.3-rc.1`, `1.2.3.post1`). A rejected value
means retyping it, not deleting a pushed tag.

**Docs are versioned via [mike](https://github.com/jimporter/mike)** and served from the
`gh-pages` branch — `docs.yaml` is a strict *build check only* and never deploys. Pages must be
set to "Deploy from a branch → gh-pages" via `poe enable_pages`, which waits until the first
release creates that branch. See `docs/contributing.md`.

Both gate on the version being greater than what is already published, build with Poetry,
and fall back to `twine` if `poetry publish` is unavailable. Configure these repository
secrets and a GitHub Environment named **`release`**:

- `PYPI_TOKEN` — a PyPI API token.
- `TEST_PYPI_TOKEN` — a Test PyPI API token.

## Extending this template

- Keep `src/<project_name>/` as the importable package root; grow the public API there.
- Add sub-packages as the project grows — do not dump everything into `main.py`.
- Mirror the test folder hierarchy to match the package structure.
- Drop `_internal/config/contracts` (and the pandas deps) if the library never reads
  tabular inputs.
