#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
source "$SCRIPT_DIR/lib/common.sh"
# shellcheck source=bin/lib/bootstrap.sh
source "$SCRIPT_DIR/lib/bootstrap.sh"

WHEELHOUSE_DIR="${WHEELHOUSE_DIR:-$PROJECT_ROOT/../_wheels/$(basename "$PROJECT_ROOT")}"
WHEELHOUSE_PART_MB="${WHEELHOUSE_PART_MB:-45}"
SELECT_PY="$SCRIPT_DIR/lib/wheelhouse_select.py"

resolve_target_env() {
	TARGET_PYVER="${WHEELHOUSE_TARGET_PYTHON_VERSION:-}"
	[[ -z "$TARGET_PYVER" ]] && TARGET_PYVER="$("$PYTHON" -c 'import platform; print(platform.python_version())')"
	TARGET_SYSPLAT="${WHEELHOUSE_TARGET_SYS_PLATFORM:-}"
	[[ -z "$TARGET_SYSPLAT" ]] && TARGET_SYSPLAT="$("$PYTHON" -c 'import sys; print(sys.platform)')"
	TARGET_MACHINE="${WHEELHOUSE_TARGET_PLATFORM_MACHINE:-}"
	[[ -z "$TARGET_MACHINE" ]] && TARGET_MACHINE="$("$PYTHON" -c 'import platform; print(platform.machine())')"
	TARGET_IMPL="${WHEELHOUSE_TARGET_IMPLEMENTATION:-cpython}"
	print_status "config" "Target: python $TARGET_PYVER, $TARGET_SYSPLAT/$TARGET_MACHINE ($TARGET_IMPL)"
}

driver_prune_list() {
	local str_keep
	DROP_PACKAGES=()
	[[ -z "${DB_BACKEND:-}" ]] && return 0
	case "$(printf '%s' "$DB_BACKEND" | tr '[:upper:]' '[:lower:]')" in
	postgresql) str_keep=psycopg ;;
	mysql | mariadb) str_keep=mysql-connector-python ;;
	oracle) str_keep=oracledb ;;
	mssql) str_keep=pyodbc ;;
	sqlite) str_keep="" ;;
	*)
		print_status "warning" "DB_BACKEND='$DB_BACKEND' is not a known backend — every native-DB driver is being pruned"
		str_keep=""
		;;
	esac
	local str_pkg
	for str_pkg in psycopg mysql-connector-python oracledb pyodbc; do
		[[ "$str_pkg" == "$str_keep" ]] || DROP_PACKAGES+=("$str_pkg")
	done
}

export_and_select() {
	local path_export="$1" path_selected="$2"
	local -a args_drop=()
	local str_pkg

	print_status "info" "Exporting locked dependencies ..."
	OUTPUT_FILE="$path_export" bash "$SCRIPT_DIR/export_deps.sh" >/dev/null

	for str_pkg in "${DROP_PACKAGES[@]:-}"; do
		[[ -n "$str_pkg" ]] && args_drop+=(--drop "$str_pkg")
	done
	print_status "info" "Selecting requirements for the target environment ..."
	"$PYTHON" "$SELECT_PY" select \
		--requirements "$path_export" --out "$path_selected" \
		--target-python-version "$TARGET_PYVER" \
		--target-sys-platform "$TARGET_SYSPLAT" \
		--target-platform-machine "$TARGET_MACHINE" \
		--target-implementation "$TARGET_IMPL" \
		${args_drop[@]+"${args_drop[@]}"}
}

download_wheels() {
	local path_selected="$1" dir_wheels="$2"
	local -a args_pip=(-m pip download --no-deps --dest "$dir_wheels" -r "$path_selected")

	ensure_dir "$dir_wheels"
	if [[ -n "${WHEELHOUSE_PIP_PLATFORM:-}" ]]; then
		args_pip+=(
			--platform "$WHEELHOUSE_PIP_PLATFORM"
			--python-version "$TARGET_PYVER"
			--implementation "$TARGET_IMPL"
			--only-binary=:all:
		)
		[[ -n "${WHEELHOUSE_PIP_ABI:-}" ]] && args_pip+=(--abi "$WHEELHOUSE_PIP_ABI")
	fi
	print_status "info" "Downloading wheels to $dir_wheels ..."
	"$PYTHON" "${args_pip[@]}"
}

build_wheelhouse() {
	local dir_tmp dir_wheels

	print_status "section" "Building offline wheelhouse -> $WHEELHOUSE_DIR"
	ensure_dir "$WHEELHOUSE_DIR"
	dir_tmp="$(mktemp -d)"
	# shellcheck disable=SC2064
	trap "rm -rf '$dir_tmp'" EXIT
	dir_wheels="$dir_tmp/wheels"

	resolve_target_env
	driver_prune_list
	export_and_select "$dir_tmp/requirements.txt" "$dir_tmp/selected.txt"
	download_wheels "$dir_tmp/selected.txt" "$dir_wheels"

	print_status "info" "Packing the wheelhouse (${WHEELHOUSE_PART_MB} MB parts) ..."
	"$PYTHON" "$SELECT_PY" pack \
		--wheels-dir "$dir_wheels" \
		--zip-path "$WHEELHOUSE_DIR/wheelhouse.zip" \
		--manifest "$WHEELHOUSE_DIR/manifest.json" \
		--part-size-mb "$WHEELHOUSE_PART_MB"

	print_status "success" "Wheelhouse ready: $WHEELHOUSE_DIR (copy it beside the offline clone)"
}

assemble_wheelhouse() {
	local dir_source="${1:-$WHEELHOUSE_DIR}"
	local dir_out="${2:-$WHEELHOUSE_DIR/wheels}"

	print_status "section" "Assembling offline wheelhouse from $dir_source"
	"$PYTHON" "$SELECT_PY" assemble \
		--source "$dir_source" --wheels-out "$dir_out" \
		--manifest "$dir_source/manifest.json"
	print_status "success" "Wheels ready at $dir_out — install with:"
	print_status "info" "  pip install --no-index --find-links $dir_out -r requirements-lock.txt"
	print_status "info" "  (built with DB_BACKEND? the lock still names pruned drivers — install $dir_out/*.whl instead)"
}

main() {
	bootstrap_init
	case "${1:-build}" in
	build) build_wheelhouse ;;
	assemble)
		shift
		assemble_wheelhouse "$@"
		;;
	*)
		print_status "error" "Usage: build_wheelhouse.sh [build|assemble [source] [wheels-out]]"
		return 2
		;;
	esac
}

main "$@"
