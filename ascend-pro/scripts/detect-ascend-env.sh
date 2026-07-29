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

run_if_present "npu-smi info" npu-smi info
run_if_present "npu-smi board" npu-smi info -t board
run_if_present "npu-smi usages" npu-smi info -t usages

print_header "CANN Environment"
printf 'ASCEND_HOME_PATH=%s\n' "${ASCEND_HOME_PATH:-}"
printf 'ASCEND_TOOLKIT_HOME=%s\n' "${ASCEND_TOOLKIT_HOME:-}"
printf 'ASCEND_AICPU_PATH=%s\n' "${ASCEND_AICPU_PATH:-}"

print_header "Ascend Tools"
for tool in npu-smi atc aoe aclprof msprof msame ais_bench ais_infer; do
  command -v "$tool" 2>/dev/null || true
done

run_if_present "ATC Version" atc --version

print_header "Ascend Library Candidates"
find /usr/local/Ascend /usr /usr/local -maxdepth 6 \
  \( -name 'libascendcl.so*' \
  -o -name 'libacl_dvpp.so*' \
  -o -name 'libacl_op_compiler.so*' \
  -o -name 'libge_runner.so*' \
  -o -name 'libascend_hal.so*' \
  -o -name 'libhi_mpi_vpc.so*' \
  -o -name 'libacl_tdt_channel.so*' \) 2>/dev/null || true

print_header "Ascend Header Candidates"
find /usr/local/Ascend /usr /usr/local -maxdepth 6 \
  \( -name 'acl.h' -o -name 'acl_dvpp.h' -o -name 'acl_rt.h' -o -name 'acl_mdl.h' \) 2>/dev/null || true

print_header "Version Strings"
while IFS= read -r lib; do
  if [[ -r "$lib" ]]; then
    printf '\n-- %s\n' "$lib"
    strings "$lib" 2>/dev/null | grep -Ei 'ascend|cann|acl|version|runtime' | head -n 30 || true
  fi
done < <(find /usr/local/Ascend /usr /usr/local -maxdepth 6 \( -name 'libascendcl.so*' -o -name 'libacl_dvpp.so*' \) 2>/dev/null || true)
