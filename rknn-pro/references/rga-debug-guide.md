# RGA Debug Guide

Step-by-step debugging for RGA kernel errors on Rockchip Linux systems.

## Quick Triage

When RGA errors appear in `dmesg`:

1. Capture the full error sequence: `dmesg | grep -i rga | tail -40`
2. Check the **Complete Kernel Error → Root Cause Map** in
   [rga-api-reference.md](rga-api-reference.md) for each line.
3. Follow the relevant section below based on the error class.

## Kernel Debug Nodes

RGA driver exposes debug information at `/sys/kernel/debug/rkrga/` (debugfs) or `/proc/rkrga/`
(procfs fallback when debugfs is not mounted).

### Status Queries (read-only)

| Node | Command | What it shows |
| --- | --- | --- |
| Driver version | `cat driver_version` | Kernel RGA driver version string |
| Core load | `cat load` | Per-core workload percentage; identifies overloaded or idle cores |
| Memory sessions | `cat mm_session` | Registered buffer handles and their state; detect leaked handles |
| Request queue | `cat request_manager` | Pending/active task queue; detect job stalls |
| Hardware caps | `cat hardware` | Supported hardware capabilities, core topology, and feature flags |

### Debug Logging (write to enable)

Enable specific kernel log channels by writing to the `debug` node:

```bash
# Enable parameter logging — logs every RGA submission's parameters
echo msg > /sys/kernel/debug/rkrga/debug

# Enable register dump — logs hardware register writes
echo reg > /sys/kernel/debug/rkrga/debug

# Enable timing — logs hardware execution duration per job
echo time > /sys/kernel/debug/rkrga/debug

# Enable interrupt logging — logs IRQ status on completion/error
echo int > /sys/kernel/debug/rkrga/debug

# Enable parameter checking — logs alignment/format validation details
# WARNING: the check mode's memory verification overhead can itself crash the
# kernel on over-threshold memory. Do NOT enable casually on production.
echo check > /sys/kernel/debug/rkrga/debug
```

Multiple modes can be enabled simultaneously. Disable by writing `0`:

```bash
echo 0 > /sys/kernel/debug/rkrga/debug
```

### Frame Dump

Capture RGA input/output frames for visual inspection:

```bash
# Set dump directory (must exist and be writable)
echo /tmp/rga_dump > /sys/kernel/debug/rkrga/dump_path

# Dump next N frames (1 = dump the next single operation)
echo 1 > /sys/kernel/debug/rkrga/dump_image
```

Dumped frames are raw pixel data. View with a tool that accepts raw formats (e.g.
`ffplay -video_size WxH -pixel_format nv12 -f rawvideo /tmp/rga_dump/...`).

## HAL-Level Logging (librga userspace)

For Linux systems, set environment variables before launching the application:

```bash
# Enable librga logs
export ROCKCHIP_RGA_LOG=1

# Set verbosity (0=off, 6=maximum detail)
export ROCKCHIP_RGA_LOG_LEVEL=6

# Then run your application
./your_rknn_app
```

Log levels:
- 0: Off
- 1: Error only
- 2: Warning
- 3: Info
- 4: Debug
- 5: Verbose
- 6: Trace (maximum detail — logs every buffer parameter, stride, format, rect)

For Android: `setprop vendor.rga.log 1` and `setprop vendor.rga.log_level 6`.

## Debugging Workflow by Error Class

### Buffer/Memory Errors

**Symptoms:** `Cannot get dst channel buffer`, `failed to map buffer`, `dma_buf_get fail`,
`failed to get vma/pte`, `set mmu info error`, `Only get buffer X byte...required Y byte`

**Steps:**

1. Enable `msg` debug: `echo msg > /sys/kernel/debug/rkrga/debug`
2. Check `mm_session`: `cat /sys/kernel/debug/rkrga/mm_session` — look for leaked or stale handles.
3. In application code, verify:
   - `importbuffer_fd` called once per buffer pool, not per frame.
   - `releasebuffer_handle` paired with every import.
   - Buffer size passed to `importbuffer_fd` matches `w_stride × h_stride × bpp` (not `width × height`).
   - All buffers use handle-based API or all use fd-based API — no mixing.
4. Check `dmesg` for `Decrement the reference of handle` at process exit — indicates leaked handles.

### Hardware Timeout

**Symptoms:** `job hardware has timeout`, `soft reset complete`, `Rga sync pid X wait 1 task done timeout`

**Steps:**

1. Enable `time` and `int` debug:
   ```bash
   echo time > /sys/kernel/debug/rkrga/debug
   echo int > /sys/kernel/debug/rkrga/debug
   ```
2. Check core load: `cat /sys/kernel/debug/rkrga/load` — identify overloaded/idle cores.
3. Check RGA clock: `cat /sys/kernel/debug/clk/aclk_rga*/clk_rate`
4. Check for IOMMU fault indicator: `INTR[0x840700]` means IOMMU page fault → buffer problem.
5. If `hardware has finished, but the software has timeout!`: CPU scheduling issue — check for
   RT tasks preempting IRQ processing.
6. If timeout follows FBC/AFBC format operations: verify the buffer's physical layout matches the
   declared compressed format and block alignment.

### Parameter Errors

**Symptoms:** `RgaBlit fail: Not a typewriter`, `Error yuv not align to 2`, `err ws[...]`,
`Error srcRect`, `Invalid argument`

**Steps:**

1. Enable `check` and `msg` debug for detailed parameter logs.
2. Call `imcheck` before every operation and log `imStrError(ret)` on failure.
3. Verify alignment:
   - NV12/NV21: logical width, height, x, y offsets all even.
   - RGB888 on RGA3: w_stride multiple of 16.
   - Check the complete alignment table in [rga-api-reference.md](rga-api-reference.md).
4. Verify `x_offset + width ≤ w_stride` and `y_offset + height ≤ h_stride`.
5. Verify scaling ratio within core limits (RGA2: 1/16–16×, RGA3: 1/8–8×).
6. Verify rotation: swap dst width/height for 90°/270° rotation.

### Core Scheduling Errors

**Symptoms:** `rga_policy: invalid function policy`, `job assign failed`, `no core match`

**Steps:**

1. Check `cat /sys/kernel/debug/rkrga/hardware` for available cores and their capabilities.
2. Check if explicit core mask is set: `imconfig(IM_CONFIG_SCHEDULER_CORE, ...)` — remove it to
   test with automatic scheduling.
3. Verify the operation's resolution and format are supported by at least one available core:
   - RGA3 minimum 68×2, RGA2 minimum 2×2.
   - RGA3 scaling max 1/8–8×, RGA2 scaling max 1/16–16×.
4. After a `soft reset`, the recovering core may temporarily be unavailable — check if the error is
   transient or persistent.

### Color Errors (No Crash)

**Symptoms:** Pink/green tint on CSC output, color shift

**Steps:**

1. Check librga/driver version match: `cat /sys/kernel/debug/rkrga/driver_version` and compare
   with `querystring(RGA_VERSION)` or `strings librga.so | grep version`.
2. librga ≥ 1.4.0 requires driver ≥ v1.2.0 — mismatches cause incorrect CSC matrices.
3. Verify RGB↔BGR channel order matches model expectation (not an RGA bug but a pipeline bug).
4. If using explicit CSC mode, verify BT.601 (limit/full) vs BT.709 selection matches the source.

## Version Checking Commands

```bash
# Kernel driver version
cat /sys/kernel/debug/rkrga/driver_version 2>/dev/null || cat /proc/rkrga/driver_version

# librga shared object version
strings $(find /usr/lib* -name 'librga.so*' 2>/dev/null | head -1) | grep -i 'rga.*version'

# RGA core topology and interrupt distribution
cat /proc/interrupts | grep rga

# Available cores and capabilities
cat /sys/kernel/debug/rkrga/hardware 2>/dev/null || echo "debugfs not available"
```

## Collecting Evidence for Bug Reports

When filing an RGA issue or requesting help:

```bash
# Run the bundled diagnostic script if available
<skill-root>/scripts/rknn-diag.sh -o rga-evidence.txt

# Or collect manually:
cat /sys/kernel/debug/rkrga/driver_version
cat /sys/kernel/debug/rkrga/hardware
cat /sys/kernel/debug/rkrga/load
cat /sys/kernel/debug/rkrga/mm_session
cat /proc/interrupts | grep rga
dmesg | grep -i rga | tail -60
uname -r
strings /usr/lib*/librga.so* | grep -i version
```

## Sources

- Rockchip librga FAQ: https://github.com/airockchip/librga/blob/main/docs/Rockchip_FAQ_RGA_EN.md
- Rockchip RGA Developer Guide: https://github.com/airockchip/librga/blob/main/docs/Rockchip_Developer_Guide_RGA_EN.md
- librga issue tracker: https://github.com/airockchip/librga/issues
