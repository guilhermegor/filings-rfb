# **FAQ**

Answers to common questions about using and developing this library. Add project-specific
entries as they come up in issues.

> **See also:** [Usage](usage.md) · [Examples](examples.md) · [Contributing](contributing.md).

---

## How do I install it?

```bash
pip install <project_name>
```

Replace with the real distribution name and any extras (e.g. `pip install "<project_name>[web]"`).

## How do I add or update a dependency?

Use Poetry so the lock file stays authoritative:

```bash
poetry add <package>          # runtime dependency
poetry add --group dev <package>   # dev-only tool
```

Every package the code imports must be a **direct** dependency — never rely on it arriving
transitively through another package.

## Which Python versions are supported?

See the `python = "..."` constraint in `pyproject.toml`; CI runs the test matrix against each.

## How is the version determined?

The version is the **git tag** (via poetry-dynamic-versioning); `pyproject.toml` holds a `0.0.0`
placeholder. Cut a release from the release workflow — see [Contributing](contributing.md).

## What is the `cnpj.tar.gz` at the root of the RFB share, and does the library use it?

No, the library ignores it. It is a 63,954,782,749-byte (59.6 GiB) single-stream gzip of a
tar, last modified 2026-01-28 and never refreshed since. It holds only the nine monthly
folders `2025-05` to `2026-01`, byte-identical to the per-month zips that remain on the
share, so it adds no data, cannot back-fill anything before `2025-05`, and cannot be
read selectively (a gzip stream has no seek points). Download the `YYYY-MM/<file>.zip`
parts you need instead. The evidence is in `.specs/features/cnpj-tarball/design.md`.
