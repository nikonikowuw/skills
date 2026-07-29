#!/usr/bin/env bash
set -euo pipefail

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sanitizer="$script_dir/sanitize-ascend-evidence.py"
output_dir=""
deployment="host"
device_index="0"
target_binary=""

usage() {
  printf '%s\n' \
    "Usage: collect-ascend-debug.sh --output <directory> [options]" \
    "  --deployment <host|container|vm|other>" \
    "  --device-index <non-negative integer>" \
    "  --target-binary <executable-or-shared-object>"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output) output_dir="${2:-}"; shift 2 ;;
    --deployment) deployment="${2:-}"; shift 2 ;;
    --device-index) device_index="${2:-}"; shift 2 ;;
    --target-binary) target_binary="${2:-}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ -z "$output_dir" ]]; then
  printf '%s\n' "--output is required; refusing to create an implicit bundle." >&2
  exit 2
fi
if [[ ! "$deployment" =~ ^[a-zA-Z0-9._-]+$ ]]; then
  printf '%s\n' "Invalid deployment label." >&2
  exit 2
fi
if [[ ! "$device_index" =~ ^[0-9]+$ ]]; then
  printf '%s\n' "--device-index must be a non-negative integer." >&2
  exit 2
fi
if [[ -n "$target_binary" && ! -r "$target_binary" ]]; then
  printf 'Target binary is not readable: %s\n' "$target_binary" >&2
  exit 2
fi
if [[ -e "$output_dir" ]]; then
  printf 'Output already exists: %s\n' "$output_dir" >&2
  exit 2
fi

mkdir -m 700 -p "$output_dir"

sanitize_stream() {
  python3 "$sanitizer"
}

capture() {
  local name="$1"
  shift
  if "$@" 2>&1 | sanitize_stream >"$output_dir/$name.txt"; then
    return 0
  fi
  printf '%s\n' "[command unavailable or failed; inspect before treating this field as evidence]" \
    >>"$output_dir/$name.txt"
}

host_token="unavailable"
if [[ -r /etc/machine-id ]]; then
  host_token=$(python3 "$sanitizer" --derive-token host </etc/machine-id)
elif [[ -r /var/lib/dbus/machine-id ]]; then
  host_token=$(python3 "$sanitizer" --derive-token host </var/lib/dbus/machine-id)
fi

{
  printf '== Device Context: %s device-%s ==\n' "$deployment" "$device_index"
  printf 'Host Token: %s\n' "$host_token"
  printf 'Deployment: %s\n' "$deployment"
  printf 'Device Index: %s\n' "$device_index"
  printf 'Collected UTC: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '%s\n' "Review every file and remove project-sensitive values before sharing."
} >"$output_dir/00-context.txt"

capture cann_env sh -lc 'printf "ASCEND_HOME_PATH=%s\n" "${ASCEND_HOME_PATH:-}"; printf "ASCEND_TOOLKIT_HOME=%s\n" "${ASCEND_TOOLKIT_HOME:-}"; printf "ASCEND_AICPU_PATH=%s\n" "${ASCEND_AICPU_PATH:-}"; printf "LD_LIBRARY_PATH=%s\n" "${LD_LIBRARY_PATH:-}"'
capture ascend_tools sh -lc 'for tool in npu-smi atc aoe aclprof msprof msame ais_bench ais_infer; do command -v "$tool" 2>/dev/null || true; done'
capture atc_version atc --version
capture library_scan sh -lc "find /usr/local/Ascend /usr /usr/local -maxdepth 6 \\( -name 'libascendcl.so*' -o -name 'libacl_dvpp.so*' -o -name 'libacl_op_compiler.so*' -o -name 'libge_runner.so*' -o -name 'libascend_hal.so*' -o -name 'libhi_mpi_vpc.so*' -o -name 'libacl_tdt_channel.so*' \\) 2>/dev/null"
capture header_scan sh -lc "find /usr/local/Ascend /usr /usr/local -maxdepth 6 \\( -name 'acl.h' -o -name 'acl_dvpp.h' -o -name 'acl_rt.h' -o -name 'acl_mdl.h' \\) 2>/dev/null"
capture python_acl sh -lc 'python3 - <<PY
try:
    import acl
    print("python acl module: present")
    print(getattr(acl, "__file__", "unknown path"))
except Exception as exc:
    print("python acl module: not importable")
    print(type(exc).__name__ + ": " + str(exc))
try:
    import torch_npu
    print("torch_npu module: present", getattr(torch_npu, "__version__", "unknown"))
except Exception:
    print("torch_npu module: not importable")
PY'

search_roots=()
for root in "${ASCEND_HOME_PATH:-}" "${ASCEND_TOOLKIT_HOME:-}" /usr/local/Ascend /opt/Ascend; do
  if [[ -n "$root" && -d "$root" ]]; then
    search_roots+=("$root")
  fi
done
if [[ ${#search_roots[@]} -gt 0 ]]; then
  capture 40-library-header-scan find "${search_roots[@]}" -maxdepth 7 \
    \( -name 'libascendcl.so*' -o -name 'libacl_dvpp.so*' -o -name 'libacl_op_compiler.so*' \
    -o -name 'libge_runner.so*' -o -name 'acl.h' -o -name 'acl_rt.h' \
    -o -name 'acl_mdl.h' -o -name 'acl_dvpp.h' \)
else
  printf '%s\n' "No standard Ascend installation root was found." >"$output_dir/40-library-header-scan.txt"
fi

if [[ -n "$target_binary" ]]; then
  capture 50-target-linkage ldd -- "$target_binary"
  capture 51-target-dynamic readelf -d -- "$target_binary"

  linked_libraries=$(ldd -- "$target_binary" 2>/dev/null | awk '/libascendcl|libacl_dvpp/ { for (i = 1; i <= NF; i++) if ($i ~ /^\//) print $i }' | sort -u)
  if [[ -n "$linked_libraries" ]]; then
    while IFS= read -r library; do
      safe_name=$(basename "$library" | tr -cd 'A-Za-z0-9._-')
      if readelf -Ws -- "$library" 2>&1 | rg 'aclInit|aclFinalize|aclrt|aclmdl|acldvpp' | sanitize_stream >"$output_dir/52-symbols-$safe_name.txt"; then
        :
      else
        printf '%s\n' "Symbol inspection failed for $library" >"$output_dir/52-symbols-$safe_name.txt"
      fi
    done <<<"$linked_libraries"
  else
    printf '%s\n' "No linked Ascend libraries found; inspect dlopen paths if the project loads them dynamically." \
      >"$output_dir/52-symbols.txt"
  fi
else
  printf '%s\n' "No --target-binary supplied; actual linkage and exported symbols were not collected." \
    >"$output_dir/50-target-linkage.txt"
fi

combined_evidence="$output_dir/ascend-evidence.txt"
for evidence_file in "$output_dir"/[0-9][0-9]-*.txt; do
  printf '\n== Evidence File: %s ==\n' "$(basename "$evidence_file")" >>"$combined_evidence"
  cat "$evidence_file" >>"$combined_evidence"
done

printf 'Wrote sanitized evidence bundle to %s\n' "$output_dir"
printf 'Combined renderer input: %s\n' "$combined_evidence"
printf '%s\n' "Inspect every file before sharing; automated redaction is not a confidentiality guarantee."
