#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
tmp_root=$(mktemp -d "${TMPDIR:-/tmp}/ascend-pro-detect.XXXXXX")
bundle="$tmp_root/bundle"

cleanup() {
  rm -rf -- "$tmp_root"
}
trap cleanup EXIT HUP INT TERM

bash "$script_dir/collect-ascend-debug.sh" --output "$bundle" "$@" >&2
for evidence_file in "$bundle"/[0-9][0-9]-*.txt; do
  printf '\n== Evidence File: %s ==\n' "$(basename "$evidence_file")"
  cat "$evidence_file"
done
