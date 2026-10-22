#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=bin/lib/bootstrap.sh
source "$SCRIPT_DIR/lib/bootstrap.sh"

OUTPUT_FILE="${OUTPUT_FILE:-$PROJECT_ROOT/requirements-lock.txt}"

export_deps() {
	local path_out="$OUTPUT_FILE"
	local str_output
	local int_status

	print_status "info" "Exporting locked dependencies to ${path_out##*/} ..."
	set +e
	str_output="$(run_poetry export \
		--format requirements.txt \
		--output "$path_out" \
		--without-hashes 2>&1)"
	int_status=$?
	set -e

	if [[ "$int_status" -eq 0 ]]; then
		local int_lines
		int_lines="$(wc -l <"$path_out" | tr -d ' ')"
		print_status "success" "Wrote ${path_out##*/} ($int_lines requirement lines)"
		return 0
	fi

	print_status "error" "poetry export failed (exit $int_status). Poetry said:"
	printf '%s\n' "$str_output" >&2
	print_status "error" "Resolved Poetry: ${POETRY_CMD[*]}"
	print_status "error" "An 'unknown command' above means THAT Poetry lacks the export plugin"
	print_status "error" "(not that it is uninstalled). Add it to the same install:"
	print_status "error" "  ${POETRY_CMD[*]} self add poetry-plugin-export"
	return "$int_status"
}

main() {
	bootstrap_init
	wire_corporate_ca
	ensure_poetry
	export_deps
}

main "$@"
