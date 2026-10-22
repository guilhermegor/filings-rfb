# CLAUDE.md — docs/

Guidance for working inside this project's `docs/` directory.

## Published vs non-published

MkDocs **builds every `.md` under `docs/` into the site**, even files absent from
`nav:` (they are merely unlisted, still reachable by URL). So a backlog, spec, or
internal note dropped at the `docs/` root *will* ship to readers and can mislead
them.

Keep working documents outside `docs/`, in `.specs/`. A few legacy files and
folders still sit inside `docs/` but are excluded from the build; `exclude_docs` in
`mkdocs.yml` is the authoritative list. It uses `.gitignore` syntax, which has no inline comments: a trailing `# ...` becomes part of the pattern and silently disables the exclusion, so keep any comment on its own line.

- `.specs/backlog/` — work-to-do backlogs and follow-up notes (outside `docs/`, so
  never published). For any non-trivial branch, keep a
  **per-branch work ledger** here at `.specs/backlog/<kebab-topic>_YYYYMMDD_HHMMSS.md`
  (timestamped filename, set at creation, never renamed) recording **what was done**
  and **what remains / is open**, updated as the work proceeds. Tracked in git but
  outside the site source, so knowledge survives across sessions. Distinct from
  generalizable lessons: the ledger is *this branch's* state. When every item is done,
  tick the last box and add a "Completed — kept as a record" note — do **not** delete it;
  a finished ledger is the team-reviewable record of what was done and why.
- Any new non-published folder must be added to `exclude_docs` in the same commit.

## Published pages

Everything else under `docs/` (e.g. `index.md`, `architecture.md`, the `api/` reference section) is a
published page. Register new published pages in `mkdocs.yml` `nav:` in the same
commit they are created, or MkDocs silently omits them from navigation — the
`check-docs-sections` gate (pre-commit + CI) enforces this on the canonical **English
slugs** (`index`/`usage`/`examples`/`api/index`/`faq`/`contributing`/`changelog`), not on
the localized nav titles.

The API reference is a **directory** (`docs/api/` — `index.md` overview + `reference.md`),
never a single `api.md`: it grows once per shipped unit, and splitting it later rots every
published deep link. Group new API pages by the codebase's own top-level split. Brand assets
live in `docs/assets/` (placeholder `logo.png`, wired as `theme.logo`/`favicon` + the
landing image), with size/position/border tuned inline on the `<img>` (`width` / `align` /
`style="border-radius"`) in `docs/index.md` and `README.md`.
