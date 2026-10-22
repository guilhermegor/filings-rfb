#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=bin/lib/bootstrap.sh
source "$SCRIPT_DIR/lib/bootstrap.sh"

bool_poetry_ok=false

resolve_actionlint_mode() {
	if [[ "$bool_poetry_ok" == true ]] && run_poetry run actionlint --version >/dev/null 2>&1; then
		printf 'poetry'
		return 0
	fi
	if command -v actionlint >/dev/null 2>&1 && actionlint --version >/dev/null 2>&1; then
		printf 'system'
		return 0
	fi
	printf ''
}

discover_workflows() {
	[ -d .github/workflows ] || return 0
	find .github/workflows \( -name '*.yaml' -o -name '*.yml' \) -type f | sort
}

main() {
	cd "$SCRIPT_DIR/.."

	mapfile -t list_workflows < <(discover_workflows)

	if [ "${#list_workflows[@]}" -eq 0 ]; then
		if [ -d .github/workflows ]; then
			print_status "error" "no workflow files found under .github/workflows — actionlint would pass vacuously"
			return 1
		fi
		print_status "warning" "skip: no .github/workflows directory (offline scaffold)"
		return 0
	fi

	PYTHON="$(resolve_python 2>/dev/null)" || true
	export PYTHON
	if resolve_poetry; then
		bool_poetry_ok=true
	fi

	local str_mode
	str_mode="$(resolve_actionlint_mode)"
	if [ -z "$str_mode" ]; then
		if [ "${LINT_ACTIONS_REQUIRED:-0}" = "1" ]; then
			print_status "error" "actionlint is required here but absent — a skipped gate in CI is a gate reporting its own blindness as OK"
			return 1
		fi
		print_status "warning" "skip: actionlint absent (see the CI job, or install from https://github.com/rhysd/actionlint)"
		return 0
	fi

	export SHELLCHECK_OPTS="--severity=warning --exclude=SC1091"

	print_status "info" "actionlint [$str_mode]: ${#list_workflows[@]} workflow(s)"
	if [ "$str_mode" = poetry ]; then
		run_poetry run actionlint "${list_workflows[@]}"
	else
		actionlint "${list_workflows[@]}"
	fi
	print_status "success" "actionlint OK"
}

main "$@"
