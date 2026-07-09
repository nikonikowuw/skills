#!/usr/bin/env bash
set -euo pipefail

out_dir="${1:-ascend-debug-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$out_dir"

capture() {
  local name="$1"
  shift
  "$@" >"$out_dir/$name.txt" 2>&1 || true
}

capture uname uname -a
capture os_release cat /etc/os-release
capture cpuinfo cat /proc/cpuinfo
capture meminfo cat /proc/meminfo
capture groups groups
capture lsmod lsmod
capture dmesg dmesg

capture device_nodes sh -lc 'ls -l /dev/davinci* /dev/davinci_manager /dev/devmm_svm /dev/hisi_hdc 2>/dev/null'
capture npu_smi_info npu-smi info
capture npu_smi_board npu-smi info -t board
capture npu_smi_usages npu-smi info -t usages

capture cann_env sh -lc 'printf "ASCEND_HOME_PATH=%s\n" "${ASCEND_HOME_PATH:-}"; printf "ASCEND_TOOLKIT_HOME=%s\n" "${ASCEND_TOOLKIT_HOME:-}"; printf "ASCEND_AICPU_PATH=%s\n" "${ASCEND_AICPU_PATH:-}"; printf "LD_LIBRARY_PATH=%s\n" "${LD_LIBRARY_PATH:-}"'
capture ascend_tools sh -lc 'for tool in npu-smi atc aclprof msame ais_bench; do command -v "$tool" 2>/dev/null || true; done'
capture atc_version atc --version
capture library_scan sh -lc "find /usr/local/Ascend /usr /usr/local -maxdepth 6 \\( -name 'libascendcl.so*' -o -name 'libacl_dvpp.so*' -o -name 'libacl_op_compiler.so*' -o -name 'libge_runner.so*' -o -name 'libacl_tdt_channel.so*' \\) 2>/dev/null"
capture header_scan sh -lc "find /usr/local/Ascend /usr /usr/local -maxdepth 6 \\( -name 'acl.h' -o -name 'acl_dvpp.h' -o -name 'acl_rt.h' -o -name 'acl_mdl.h' \\) 2>/dev/null"
capture python_acl sh -lc 'python3 - <<PY
try:
    import acl
    print("python acl module: present")
    print(getattr(acl, "__file__", "unknown path"))
except Exception as exc:
    print("python acl module: not importable")
    print(type(exc).__name__ + ": " + str(exc))
PY'

printf 'Wrote debug bundle to %s\n' "$out_dir"
