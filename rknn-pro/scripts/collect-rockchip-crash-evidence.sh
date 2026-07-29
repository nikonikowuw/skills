#!/usr/bin/env bash
set -euo pipefail
umask 077

pid="${1:-}"
out_dir="${2:-rockchip-crash-evidence-$(date +%Y%m%d-%H%M%S)}"

if [[ -n "$pid" && ! "$pid" =~ ^[0-9]+$ ]]; then
  echo "PID must be numeric: $pid" >&2
  exit 2
fi
if [[ -e "$out_dir" ]]; then
  echo "refusing to overwrite existing evidence path: $out_dir" >&2
  exit 1
fi
mkdir -p -- "$out_dir"

capture() {
  local name="$1"
  shift
  "$@" >"$out_dir/$name.txt" 2>&1 || true
}

capture uname uname -a
capture os_release cat /etc/os-release
capture cpuinfo cat /proc/cpuinfo
capture meminfo cat /proc/meminfo
capture mounts mount
capture dma_heaps sh -lc 'ls -la /dev/dma_heap 2>/dev/null; find /dev/dma_heap -maxdepth 1 -type c -o -type l 2>/dev/null'
capture device_nodes sh -lc 'ls -l /dev/rga /dev/dri/renderD* /dev/video* /dev/media* 2>/dev/null'
capture modules sh -lc "lsmod | grep -Ei 'rockchip|rga|mpp|vcodec|rknpu|iep'"
capture dmesg dmesg -T
capture kernel_journal journalctl -k -b --no-pager
capture coredumps coredumpctl list --no-pager
capture pstore sh -lc 'find /sys/fs/pstore -maxdepth 1 -type f -print -exec sed -n "1,240p" {} \; 2>/dev/null'

for path in \
  /sys/firmware/devicetree/base/model \
  /sys/firmware/devicetree/base/compatible \
  /sys/kernel/debug/rkrga/driver_version \
  /sys/kernel/debug/rkrga/debug \
  /sys/kernel/debug/rkrga/load \
  /sys/kernel/debug/rkrga/mm \
  /proc/rkrga/driver_version \
  /proc/rkrga/debug; do
  if [[ -r "$path" ]]; then
    name="$(echo "$path" | tr '/' '_')"
    capture "$name" cat "$path"
  fi
done

if [[ -n "$pid" && -d "/proc/$pid" ]]; then
  capture process_status cat "/proc/$pid/status"
  capture process_limits cat "/proc/$pid/limits"
  capture process_maps cat "/proc/$pid/maps"
  capture process_smaps_rollup cat "/proc/$pid/smaps_rollup"
  capture process_fds sh -lc "ls -l /proc/$pid/fd; find /proc/$pid/fd -maxdepth 1 -type l | wc -l"
fi

capture rockchip_libraries sh -lc "find /usr /usr/local -maxdepth 5 \
  \( -name 'librga.so*' -o -name 'librknnrt.so*' -o -name 'librockchip_mpp.so*' -o -name 'libmpp.so*' \) 2>/dev/null"

echo "Read-only evidence written to: $out_dir"
echo "No debugfs/procfs controls were modified."
echo "The bundle can contain process paths and device identifiers; keep it access-restricted."
