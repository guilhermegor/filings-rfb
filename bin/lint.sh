#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

cd "$SCRIPT_DIR/.."

POETRY="bash $SCRIPT_DIR/poetry_exec.sh"

print_status info "ruff check --fix"
$POETRY run ruff check --fix .

print_status info "ruff format"
$POETRY run ruff format .

print_status info "mypy (from src/)"
(cd src && bash "$SCRIPT_DIR/poetry_exec.sh" run mypy --config-file ../mypy.ini .)

print_status info "codespell"
$POETRY run codespell .

print_status info "pydocstyle"
$POETRY run pydocstyle .

print_status info "docstring/signature agreement"
$POETRY run python bin/check_docstrings.py

print_status info "layer import policy"
$POETRY run python bin/check_layer_imports.py

print_status info "ORM model-definition guards"
$POETRY run python bin/check_orm_model_guards.py

print_status info "comment language boundary"
$POETRY run python bin/check_comment_language.py

print_status info "comment budget"
$POETRY run python bin/check_comment_budget.py --require-baseline

print_status info "env docs sync"
$POETRY run python bin/check_env_docs_sync.py

print_status info "function length"
$POETRY run python bin/check_function_length.py

print_status info "fixture scope (proxy — pair with pytest-randomly, blueprintx#442)"
$POETRY run python bin/check_fixture_scope.py

print_status info "identifier masking (a masked CPF/CNPJ in SQL matches zero rows)"
$POETRY run python bin/check_identifier_masking.py

print_status info "cyclomatic complexity"
bash bin/check_complexity.sh

print_status info "secret scan (gitleaks)"
bash bin/check_secrets.sh

print_status info "runtime type-checker application"
$POETRY run python bin/check_typing.py

print_status info "__all__ export completeness"
$POETRY run python bin/check_all_exports.py

print_status info "numeric dtype policy"
$POETRY run python bin/check_dtypes.py

print_status info "ingestion provenance stamp"
$POETRY run python bin/check_provenance.py

print_status info "docs skeleton (slug + nav)"
$POETRY run python bin/check_docs_sections.py

print_status info "docs code references (symbols + import paths)"
$POETRY run python bin/check_docs_code_refs.py

print_status info "unix filename validity"
bash bin/check_unix_filenames.sh

print_status info "shell"
bash bin/lint_shell.sh

print_status info "sql"
bash bin/lint_sql.sh

print_status info "yaml"
bash bin/lint_yaml.sh

print_status info "github actions"
bash bin/lint_actions.sh

print_status info "dockerfiles"
bash bin/lint_docker.sh

print_status info "direct dependencies"
bash bin/lint_deps.sh

print_status success "lint OK — every gate passed"
