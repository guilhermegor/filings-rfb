# **Usage**

Examples for installing and using this library.

> **See also:** [API Reference](api/index.md)

---

## Installation

```bash
pip install <package-name>
```

Or with Poetry:

```bash
poetry add <package-name>
```

---

## Basic usage

```python
from <package_name>.main import main

main()
```

---

## Cataloguing the RFB CNPJ share

The Receita Federal publishes the CNPJ open data as one folder per reference month
(`YYYY-MM`) on a public WebDAV share. `filings_rfb.ingestion.cnpj._share` lists what is
there, without authentication, so a reader never builds a URL by hand:

```python
from filings_rfb.ingestion.cnpj._share import (
    file_url,
    latest_reference_month,
    list_files,
    list_reference_months,
)

list_reference_months()          # ['2023-05', ..., '2026-10']
str_month = latest_reference_month()

for cls_file in list_files(str_month):
    print(cls_file.str_name, cls_file.int_size, cls_file.str_etag, cls_file.dt_last_modified)

file_url(str_month, "Empresas0.zip")   # plain-GET download URL, no redirect
```

- `list_files` returns one `WebdavEntry` per file: `str_name`, `int_size` (bytes),
  `str_etag` (as the server sends it, quotes included) and `dt_last_modified` (UTC).
- Requesting a month the share does not publish raises `ValueError`; there is no silent
  fallback to another month.
- Every listing is a live request, so it reflects what RFB publishes now. If RFB rotates the
  share, change `SHARE_TOKEN` in `_share.py` and nothing else.

---

## Running from the Makefile

```bash
poe run            # runs src/<package_name>/main.py
```

---

## Running tests

```bash
poe unit_tests         # unit tests only
poe integration_tests  # integration tests only
poe test_cov           # unit tests + coverage report + badge
```

---

## Linting and formatting

```bash
poe lint          # ruff check + ruff format + codespell + pydocstyle
```

---

## Publishing to PyPI

Two GitHub Actions workflows handle releases (present when the repo has a GitHub remote):

- **`release-test-pypi.yaml`** — publish to [Test PyPI](https://test.pypi.org) first.
- **`release-pypi.yaml`** — publish to [PyPI](https://pypi.org) and cut a GitHub release.

Trigger either from the **Actions** tab (`workflow_dispatch`) with the version to release.
Both gate on the new version being greater than the latest already published, build with
Poetry, and fall back to `twine` if `poetry publish` is unavailable.

Configure once, in repository settings:

- Secrets `PYPI_TOKEN` and `TEST_PYPI_TOKEN` (API tokens from each index).
- A GitHub **Environment** named `release`.
