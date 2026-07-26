#!/usr/bin/env bash
set -euo pipefail
umask 077

out_dir="${1:-rockchip-debug-$(date +%Y%m%d-%H%M%S)}"
if [[ -e "$out_dir" ]]; then
  echo "refusing to overwrite existing debug path: $out_dir" >&2
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
capture lsmod lsmod
capture dmesg dmesg

for path in \
  /sys/firmware/devicetree/base/model \
  /sys/firmware/devicetree/base/compatible \
  /sys/kernel/debug/rkrga/driver_version \
  /sys/kernel/debug/rkrga/debug \
  /proc/rkrga/driver_version \
  /proc/rkrga/debug; do
  if [[ -r "$path" ]]; then
    name="$(echo "$path" | tr '/' '_')"
    capture "$name" cat "$path"
  fi
done

capture media_devices sh -lc 'ls -l /dev/media* /dev/video* /dev/rga /dev/dri/renderD* 2>/dev/null'
capture library_scan sh -lc "find /usr /usr/local -maxdepth 4 \\( -name 'librga.so*' -o -name 'librknnrt.so*' -o -name 'librockchip_mpp.so' -o -name 'libmpp.so' \\) 2>/dev/null"

printf 'Wrote debug bundle to %s\n' "$out_dir"
