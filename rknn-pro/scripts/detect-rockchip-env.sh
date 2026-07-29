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

print_header "System"
uname -a || true

print_header "OS Release"
show_file_if_present /etc/os-release

print_header "Device Tree Model"
show_file_if_present /sys/firmware/devicetree/base/model

print_header "Compatible"
show_file_if_present /sys/firmware/devicetree/base/compatible

print_header "CPU Info"
show_file_if_present /proc/cpuinfo

print_header "Rockchip-Related Modules"
lsmod 2>/dev/null | grep -Ei 'rockchip|rga|mpp|vcodec|rknpu|iep' || true

print_header "Media Devices"
for path in /dev/media* /dev/video* /dev/rga /dev/dri/renderD*; do
  [[ -e "$path" ]] && printf '%s\n' "$path"
done

print_header "RGA Driver Version"
show_file_if_present /sys/kernel/debug/rkrga/driver_version
show_file_if_present /proc/rkrga/driver_version

print_header "RGA Debug Node"
show_file_if_present /sys/kernel/debug/rkrga/debug
show_file_if_present /proc/rkrga/debug

print_header "RKNN Runtime Candidates"
find /usr /usr/local -maxdepth 4 \( -name 'librknnrt.so' -o -name 'librknn_api.so' -o -name 'rknn_server' \) 2>/dev/null || true

print_header "librga Candidates"
find /usr /usr/local -maxdepth 4 \( -name 'librga.so' -o -name 'librga.so.*' \) 2>/dev/null || true

print_header "MPP Candidates"
find /usr /usr/local -maxdepth 4 \( -name 'librockchip_mpp.so' -o -name 'libmpp.so' \) 2>/dev/null || true

print_header "Version Strings"
for lib in \
  /usr/lib*/librga.so* \
  /usr/local/lib*/librga.so* \
  /usr/lib*/librknnrt.so* \
  /usr/local/lib*/librknnrt.so*; do
  if [[ -r "$lib" ]]; then
    printf '\n-- %s\n' "$lib"
    strings "$lib" 2>/dev/null | grep -E 'version|rga_api|RKNN|librknn' | head -n 20 || true
  fi
done
