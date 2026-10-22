#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=bin/lib/bootstrap.sh
source "$SCRIPT_DIR/lib/bootstrap.sh"

STR_TARGET="src"

count_python_files() {
	[[ -d "$STR_TARGET" ]] || return 0
	find "$STR_TARGET" -name '*.py' -type f | wc -l
}

main() {
	cd "$SCRIPT_DIR/.."

	local int_files
	int_files="$(count_python_files)"
	if [[ "$int_files" -eq 0 ]]; then
		print_status "error" "No Python files found under $STR_TARGET/ — refusing to report success."
		exit 1
	fi

	PYTHON="$(resolve_python 2>/dev/null)" || true
	export PYTHON
	if ! resolve_poetry >/dev/null 2>&1 || ! run_poetry run deptry --version >/dev/null 2>&1; then
		print_status "error" "deptry not resolvable via 'poetry run' (poetry install --with dev)."
		print_status "error" "There is no PATH fallback on purpose: outside the venv deptry inverts its own verdict — see the header."
		exit 1
	fi

	print_status "info" "deptry: $int_files Python file(s) under $STR_TARGET/"
	run_poetry run deptry "$STR_TARGET"
	print_status "success" "Every imported package is a declared direct dependency."
}

main "$@"
