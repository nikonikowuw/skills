#!/usr/bin/env bash
set -euo pipefail

print_header() {
  printf '\n== %s ==\n' "$1"
}

show_file_if_present() {
  local path="$1"
  if [[ -r "$path" ]]; then
    printf '%s\n' "-- $path"
    cat "$path"
  fi
}

run_if_present() {
  local label="$1"
  shift
  print_header "$label"
  "$@" 2>/dev/null || true
}

print_header "System"
uname -a || true

print_header "OS Release"
show_file_if_present /etc/os-release

print_header "CPU Info"
show_file_if_present /proc/cpuinfo

print_header "Ascend Device Nodes"
for path in /dev/davinci* /dev/davinci_manager /dev/devmm_svm /dev/hisi_hdc; do
  [[ -e "$path" ]] && ls -l "$path"
done

run_if_present "npu-smi info" npu-smi info
run_if_present "npu-smi board" npu-smi info -t board
run_if_present "npu-smi usages" npu-smi info -t usages

print_header "CANN Environment"
printf 'ASCEND_HOME_PATH=%s\n' "${ASCEND_HOME_PATH:-}"
printf 'ASCEND_TOOLKIT_HOME=%s\n' "${ASCEND_TOOLKIT_HOME:-}"
printf 'ASCEND_AICPU_PATH=%s\n' "${ASCEND_AICPU_PATH:-}"

print_header "Ascend Tools"
for tool in npu-smi atc aclprof msame ais_bench; do
  command -v "$tool" 2>/dev/null || true
done

run_if_present "ATC Version" atc --version

print_header "Ascend Library Candidates"
find /usr/local/Ascend /usr /usr/local -maxdepth 6 \
  \( -name 'libascendcl.so*' \
  -o -name 'libacl_dvpp.so*' \
  -o -name 'libacl_op_compiler.so*' \
  -o -name 'libge_runner.so*' \
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
