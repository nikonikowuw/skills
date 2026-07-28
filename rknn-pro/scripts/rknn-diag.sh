#!/usr/bin/env bash
# Read-only Rockchip RKNN/RGA/MPP diagnostic collector.

set -u
umask 077

usage() {
  cat <<'EOF'
Usage: rknn-diag.sh [-o REPORT] [--binary PATH] [--force]

Collects a read-only Rockchip device/runtime baseline. The default report name
contains a timestamp so an earlier report is not overwritten.
EOF
}

report="rknn-diag-report-$(date +%Y%m%d-%H%M%S).txt"
target_binary=""
force=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -o|--output)
      [[ $# -ge 2 ]] || { echo "missing value for $1" >&2; exit 2; }
      report="$2"
      shift 2
      ;;
    --binary)
      [[ $# -ge 2 ]] || { echo "missing value for $1" >&2; exit 2; }
      target_binary="$2"
      shift 2
      ;;
    --force)
      force=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -e "$report" && $force -ne 1 ]]; then
  echo "refusing to overwrite existing report: $report (use --force)" >&2
  exit 1
fi

section() {
  printf '\n== %s ==\n' "$1" >>"$report"
}

capture() {
  printf '\n$ %s\n' "$*" >>"$report"
  "$@" >>"$report" 2>&1 || true
}

capture_shell() {
  local label="$1"
  local command="$2"
  printf '\n$ %s\n' "$label" >>"$report"
  sh -c "$command" >>"$report" 2>&1 || true
}

{
  echo "Rockchip diagnostic report"
  echo "Collected: $(date -Iseconds 2>/dev/null || date)"
  echo "Hostname: $(hostname 2>/dev/null || echo unknown)"
} >"$report"

section "Device identity"
capture_shell "board serial candidates" 'grep -i "^[[:space:]]*Serial" /proc/cpuinfo 2>/dev/null || { serial=$(cat /sys/class/soc/serial_number 2>/dev/null || tr "\000" "\n" </proc/device-tree/serial-number 2>/dev/null); [ -n "$serial" ] && printf "Device ID: %s\n" "$serial"; }'
capture_shell "device-tree model" 'tr "\000" "\n" </sys/firmware/devicetree/base/model 2>/dev/null || tr "\000" "\n" </proc/device-tree/model 2>/dev/null'
capture_shell "device-tree compatible" 'tr "\000" "\n" </sys/firmware/devicetree/base/compatible 2>/dev/null || tr "\000" "\n" </proc/device-tree/compatible 2>/dev/null'

section "Kernel and rootfs"
capture uname -a
capture uname -m
capture cat /etc/os-release

section "Drivers and device nodes"
capture_shell "Rockchip-related modules" 'lsmod 2>/dev/null | grep -Ei "rockchip|rga|mpp|vcodec|rknpu|iep"'
capture_shell "media, RGA, NPU, DRM, and DMA-heap nodes" 'ls -l /dev/rknpu* /dev/rknn* /dev/rga* /dev/media* /dev/video* /dev/dri/renderD* /dev/dma_heap/* 2>/dev/null'
capture_shell "RGA driver version" 'cat /sys/kernel/debug/rkrga/driver_version 2>/dev/null || cat /proc/rkrga/driver_version 2>/dev/null'
capture_shell "NPU driver version" 'cat /sys/kernel/debug/rknpu/version 2>/dev/null'
capture_shell "recent Rockchip driver messages" 'dmesg 2>/dev/null | grep -Ei "rknpu|rknn|rga|mpp|vcodec|dma.?buf" | tail -n 120'

section "Userspace libraries and headers"
capture_shell "dynamic linker Rockchip entries" 'ldconfig -p 2>/dev/null | grep -Ei "rknn|rga|rockchip_mpp|libmpp"'
capture_shell "Rockchip library candidates" 'find /usr /usr/local /opt -maxdepth 6 -type f \( -name "librknnrt.so*" -o -name "librga.so*" -o -name "librockchip_mpp.so*" -o -name "libmpp.so*" \) 2>/dev/null'
capture_shell "Rockchip header candidates" 'find /usr /usr/local /opt -maxdepth 7 -type f \( -name "rknn_api.h" -o -name "rknn_matmul_api.h" -o -name "im2d.h" -o -name "RgaApi.h" -o -name "rga.h" -o -name "rk_mpi.h" -o -name "mpp_buffer.h" -o -name "mpp_err.h" \) 2>/dev/null'
capture_shell "Runtime version strings" 'for lib in /usr/lib*/librknnrt.so* /usr/local/lib*/librknnrt.so* /opt/*/lib*/librknnrt.so*; do if [ -r "$lib" ]; then echo "-- $lib"; strings "$lib" 2>/dev/null | grep -Ei "api version|driver version|librknn|rknnrt" | head -n 30; fi; done'
capture_shell "RGA and MPP version strings" 'for lib in /usr/lib*/librga.so* /usr/lib*/librockchip_mpp.so* /usr/lib*/libmpp.so* /usr/local/lib*/librga.so* /usr/local/lib*/librockchip_mpp.so*; do if [ -r "$lib" ]; then echo "-- $lib"; strings "$lib" 2>/dev/null | grep -Ei "version|mpp|rga_api" | head -n 20; fi; done'

section "Memory"
capture free -m

if [[ -n "$target_binary" ]]; then
  section "Target binary"
  if [[ -r "$target_binary" ]]; then
    capture ldd "$target_binary"
    capture readelf -d "$target_binary"
  else
    echo "Target binary is not readable: $target_binary" >>"$report"
  fi
fi

printf 'Wrote diagnostic report to %s\n' "$report"
