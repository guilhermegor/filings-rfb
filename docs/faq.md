# **FAQ**

Answers to common questions about using and developing this library. Add project-specific
entries as they come up in issues.

> **See also:** [Usage](usage.md) · [Examples](examples.md) · [Contributing](contributing.md).

---

## How do I install it?

```bash
pip install filings-rfb
pip install "filings-rfb[parquet]"   # optional Parquet export
```

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

The version is the **git tag** (via poetry-dynamic-versioning); `pyproject.toml` carries the
version for Commitizen (`1.0.0` at the first release) but the built wheel takes the tag. Cut a release from the release workflow — see [Contributing](contributing.md).

## What is the `cnpj.tar.gz` at the root of the RFB share, and does the library use it?

No, the library ignores it. It is a 63,954,782,749-byte (59.6 GiB) gzip of a tar (probably a
single gzip member), last modified 2026-01-28 and never refreshed since. It appears to
hold only the nine monthly folders `2025-05` to `2026-01` (inferred from the gzip trailer and byte-range
checks, not a full listing), and the sampled files are byte-identical to the per-month
zips that remain on the share, so it adds no data, cannot back-fill anything before
`2025-05`, and is impractical to read selectively (a gzip stream offers no known seek
points). Download the `YYYY-MM/<file>.zip` parts you need instead. The evidence is in
`.specs/features/cnpj-tarball/design.md`.
