#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

STR_HADOLINT_IMAGE="hadolint/hadolint:v2.12.0-alpine@sha256:3c206a451cec6d486367e758645269fd7d696c5ccb6ff59d8b03b0e45268a199"

resolve_hadolint_mode() {
	if command -v hadolint >/dev/null 2>&1 && hadolint --version >/dev/null 2>&1; then
		printf 'system'
		return 0
	fi
	if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
		printf 'docker'
		return 0
	fi
	printf ''
}

discover_dockerfiles() {
	find . \
		\( -path ./.git -o -path ./.venv -o -path ./node_modules -o -path ./.mypy_cache \) -prune \
		-o \( -iname 'Dockerfile' -o -iname 'Dockerfile.*' -o -iname '*.dockerfile' \) -type f -print |
		sort
}

main() {
	cd "$SCRIPT_DIR/.."

	local str_discovered
	if ! str_discovered="$(discover_dockerfiles)"; then
		print_status "error" "Dockerfile discovery failed — refusing to lint a partial list"
		return 1
	fi
	mapfile -t list_dockerfiles <<<"$str_discovered"
	[ "${#list_dockerfiles[@]}" -eq 1 ] && [ -z "${list_dockerfiles[0]}" ] && list_dockerfiles=()

	if [ "${#list_dockerfiles[@]}" -eq 0 ]; then
		print_status "info" "skip: no Dockerfile in this project (hadolint has nothing to lint)"
		return 0
	fi

	local str_mode
	str_mode="$(resolve_hadolint_mode)"
	if [ -z "$str_mode" ]; then
		if [ "${LINT_DOCKER_REQUIRED:-0}" = "1" ]; then
			print_status "error" "hadolint is required here but neither the binary nor a running Docker daemon is available — a skipped gate in CI is a gate reporting its own blindness as OK"
			return 1
		fi
		print_status "warning" "skip: hadolint absent (install from https://github.com/hadolint/hadolint, or start Docker)"
		return 0
	fi

	print_status "info" "hadolint [$str_mode]: ${#list_dockerfiles[@]} Dockerfile(s)"
	if [ "$str_mode" = system ]; then
		hadolint "${list_dockerfiles[@]}"
	else
		docker run --rm -v "$PWD:/repo:ro" -w /repo "$STR_HADOLINT_IMAGE" \
			hadolint "${list_dockerfiles[@]}"
	fi
	print_status "success" "hadolint OK"
}

main "$@"
