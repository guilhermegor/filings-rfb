#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib/common.sh"

require_gh() {
	if ! command -v gh >/dev/null 2>&1; then
		print_status "warning" "gh CLI not found — skipping security toggles (run 'poe enable_security' later)"
		return 1
	fi
	if ! gh auth status >/dev/null 2>&1; then
		print_status "warning" "gh not authenticated — skipping security toggles (run 'gh auth login', then 'poe enable_security')"
		return 1
	fi
	return 0
}

resolve_repo() {
	gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true
}

enable_toggle() {
	local str_repo="$1" str_path="$2" str_label="$3"
	if gh api -X PUT "repos/$str_repo/$str_path" >/dev/null 2>&1; then
		print_status "success" "$str_label enabled"
	else
		print_status "warning" "Could not enable $str_label (needs repo-admin rights, or it is unavailable for this repo) — check Settings → Code security"
	fi
}

enable_secret_scanning() {
	local str_repo="$1"
	local json_body='{"security_and_analysis":{"secret_scanning":{"status":"enabled"},"secret_scanning_push_protection":{"status":"enabled"}}}'
	if gh api -X PATCH "repos/$str_repo" --input - <<<"$json_body" >/dev/null 2>&1; then
		print_status "success" "Secret scanning + push protection enabled"
	else
		print_status "warning" "Could not enable secret scanning / push protection (private repos need the paid Secret Protection SKU, or repo-admin rights) — check Settings → Code security"
	fi
}

main() {
	print_status "section" "GitHub Security Toggles"
	if ! require_gh; then
		return 0
	fi

	local str_repo
	str_repo="$(resolve_repo)"
	if [ -z "$str_repo" ]; then
		print_status "warning" "No GitHub remote resolved — skipping (push the repo to GitHub first)"
		return 0
	fi

	enable_toggle "$str_repo" "private-vulnerability-reporting" "Private vulnerability reporting"
	enable_toggle "$str_repo" "vulnerability-alerts" "Dependabot alerts"
	enable_toggle "$str_repo" "automated-security-fixes" "Dependabot security updates"
	enable_secret_scanning "$str_repo"
}

main "$@"
