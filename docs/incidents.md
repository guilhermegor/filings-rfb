# **Incident Records**

What broke in this project, and what changed so it cannot break that way again. This page
keeps debugging knowledge inside the codebase instead of in git history and one person's
memory — the knowledge a team already paid for once should not have to be paid for twice.

> **See also:** [Usage](usage.md) · [Contributing](contributing.md) · [Changelog](changelog.md).

## Not an ADR, and not a lessons store

An **ADR** records a decision made *before* something went wrong. An incident record documents
one made *because* something already did — different trigger, different audience. If this
project adopts ADRs later, keep the two separate rather than merging them into one grab-bag.

This is also not a copy of a scaffolding tool's own "lessons learned" store. That kind of store
answers "what should every future generated project inherit" — this page answers "what bit
*this* codebase, and what did we do about it." Different audience, different lifetime.

## Published on purpose — redact before you write

This page ships in the published docs site, same as [Usage](usage.md). An incident can carry
production detail (a hostname, a query, a customer-facing symptom) that should not reach a
public site — redact or generalize it before committing the entry, the way an external
postmortem omits internal specifics. If this project's site is genuinely public and entries
cannot stay redacted, exclude `incidents.md` via `exclude_docs` in `mkdocs.yml` instead of
leaving it half-written.

## Format

Five fields, in this order. Keep each to a few sentences — the entry stops getting written the
day it takes an hour to fill in.

- **Symptom** — what was observed, not what was wrong.
- **How it was found** — the tool, command, or accident that surfaced it; "we were careful"
  does not belong here.
- **Root cause** — measured, not assumed.
- **The change** — what now makes this class of failure impossible, or loud instead of silent.
- **How we'd know it regressed** — the gate, test, or assertion that would catch it coming back.

---

## TEMPLATE — replace with this project's first real incident

Delete this section once you have an entry of your own. It stays only so a reader can see what
a filled-in entry looks like — an empty page teaches readers there is nothing to read here.

### 2026-08-16 — Reconfiguring the logger leaked a file handle every time

**Symptom.** `logging.FileHandler` objects accumulated across the process lifetime whenever
the logger was reconfigured (e.g. rotating to a new dated log file). Harmless in a short-lived
script; in a long-running service the leaked file descriptors build up.

**How it was found.** Not by the test suite — `ResourceWarning` is not shown by default in
Python. It surfaced only when the suite ran with `-W always`, while measuring something
unrelated. The defect was invisible by construction, not by anyone's oversight.

**Root cause.** The reconfiguration path called `logger.handlers.clear()` to detach the old
handler before attaching a new one. Clearing the list drops the Python *reference*; it does not
close the OS file descriptor, which stays open until garbage collection runs.

**The change.** Close every existing handler explicitly before detaching it, so the descriptor
is released immediately instead of at GC time. One call site — `handlers.clear()` appeared
exactly once in the whole codebase, so no sibling caller was left unfixed.

**How we'd know it regressed.** A test reconfigures the logger twice and asserts the first
handler's `.stream is None` after the second call — `close()` sets that attribute the moment the
descriptor is released, so the assertion does not depend on garbage-collection timing.
⚠️ Measured separately: promoting bare `ResourceWarning` to `error:` in `pytest.ini` does **not**
catch this alone — it is raised from `__del__`, an *unraisable* context pytest downgrades to
`PytestUnraisableExceptionWarning`, so both warning classes must be promoted together or the
suite still passes over a real leak.
