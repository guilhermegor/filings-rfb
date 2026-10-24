<!-- readme-archetype: library -->
# filings-rfb

<p align="center"><img src="assets/logo_lorem_ipsum.png" width="200" alt="filings-rfb logo"></p>

[![Project Status: Active](https://www.repostatus.org/badges/latest/active.svg)](https://www.repostatus.org/#active)
![Python Version](https://img.shields.io/badge/python-3.10%2B-blue.svg)
![PyPI Version](https://img.shields.io/pypi/v/filings-rfb)
[![Snyk Vulnerabilities](https://snyk.io/test/github/guilhermegor/filings-rfb/badge.svg)](https://snyk.io/test/github/guilhermegor/filings-rfb)
[![Snyk License](https://snyk.io/advisor/python/filings-rfb/badge.svg)](https://snyk.io/advisor/python/filings-rfb)
![PyPI Downloads](https://static.pepy.tech/badge/filings-rfb)
[![Linting](https://img.shields.io/badge/linting-ruff_|_codespell-blue)](https://github.com/astral-sh/ruff+https://github.com/codespell-project/codespell)
![Formatting: isort](https://img.shields.io/badge/formatting-isort-%231674b1)
![Test Coverage](./coverage.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Open Issues](https://img.shields.io/github/issues/guilhermegor/filings-rfb)
![Contributions Welcome](https://img.shields.io/badge/contributions-welcome-darkgreen.svg)

<!-- slug: overview -->
## Overview

Simple and efficient Python library to interact with Secretariat of Federal Revenue of Brazil (Receita Federal Brasileira) public data

<!-- slug: getting-started -->
## Getting Started

Python 3.10+ and [Poetry](https://python-poetry.org/) are the only prerequisites.

<!-- slug: install -->
### Install

```bash
git clone https://github.com/guilhermegor/filings-rfb.git
cd filings-rfb
poetry install --no-root
```

<!-- slug: usage -->
### Usage

Run the project through its entry points under `src/`; replace this paragraph with the
commands your users run first.

<!-- slug: project-structure -->
## Project Structure

```text
filings-rfb/
├── .github/        workflows, CODEOWNERS, PR template
├── .specs/         feature specs and backlog trackers
├── bin/            gate scripts and helpers
├── docs/           published documentation
├── src/            application code
├── tests/
│   ├── unit/
│   └── integration/
├── pyproject.toml
└── poe_tasks.toml  task runner entry points
```

<!-- slug: development -->
## Development

```bash
poetry run pytest tests/unit/ -v
poetry run pytest tests/integration/ -v
```

<!-- slug: public-api -->
## Public API

The public surface is whatever the package `__init__.py` lists in `__all__`; everything
under `_internal/` is private.

- `read_lookup(str_table, path_zip, str_url, str_etag)` reads one of the six RFB CNPJ lookup
  tables (`CNPJ_LOOKUP_NAMES`) into a typed, provenance-stamped DataFrame.

<!-- slug: publishing -->
## Publishing

Releases go out from the release workflows under `.github/workflows/`; the git tag is the
version.

<!-- slug: contributing -->
## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the branch, commit and review rules.

<!-- slug: license -->
## License

This project is licensed under MIT; see [LICENSE](LICENSE).

<!-- slug: authors -->
## Authors

- guilhermegor — [GitHub](https://github.com/guilhermegor) | [LinkedIn](https://www.linkedin.com/in/guilhermegor)

<!-- slug: useful-links -->
## Useful Links

- [GitHub Repository](https://github.com/guilhermegor/filings-rfb)
- [Issue Tracker](https://github.com/guilhermegor/filings-rfb/issues)
