# Rockchip Known Crash and Stability Patterns

Use this page to map source findings and board logs to documented failure modes. Re-check the live
source when versions differ; these references are evidence anchors, not substitutes for the
installed BSP and headers.

## Evidence Labels

- **Official constraint**: Rockchip documentation, maintained header/source, or Linux kernel docs.
- **Official history**: Rockchip changelog describing when a capability or stability fix appeared.
- **Community case**: issue report in an official repository; use as a search/reproduction clue
  unless a maintainer or official document confirms the cause.

## RGA DMA-BUF Lifecycle Cascade Failure

### Summary

A single RGA `wrapbuffer_fd` lifecycle gap triggers a **5-stage cascade failure** that takes down the entire RGA pipeline. This is the most common cause of sustained RGA failures in production detection pipelines on RK3576 (and potentially RK3588).

### Symptom Sequence (in order)

```
1. "Cannot get dst channel buffer" / "failed to map buffer"    ← ROOT TRIGGER
2. "abort! finished 0 failed 0 running_abort 0 todo_abort 0"   ← pre-commit cancel
3. "job hardware has timeout" + "INTR[0x840700]" + "soft reset" ← HW hang
4. "no core match" → "job assign failed" → "task[0] job_commit failed" ← full pipeline stall
5. "mpp_rkvdec2 ... timeout ... resetting"                      ← decoder back-pressure
```

Each step is an **effect**, not a new cause. Fix step 1 and the rest disappear.

### Root Cause

The algorithm pipeline uses `wrapbuffer_fd()` **per-frame** to wrap the destination DMA-BUF fd. Key pathology:

```cpp
// ❌ WRONG — per-frame wrapbuffer_fd
target = wrapbuffer_fd(destination_fd, width, height, RK_FORMAT_RGB_888, width, height);
```

`wrapbuffer_fd()` internally calls `importbuffer_fd()` only when librga decides it needs a new handle — it may **reuse a cached handle** from a previous call. If the Engine (or OS) recycles file descriptors, the cache returns a stale handle:

1. Frame N: `wrapbuffer_fd(fd_55, ...)` → librga creates and caches `handle_A` for `fd_55`.
2. Frame N ends: The buffer pool reclaims the source buffer and closes `fd_55`.
3. Frame N+1: The RKNN model's static input buffer (or a new source buffer) happens to be assigned `fd_55` by the kernel.
4. Frame N+1 calls `wrapbuffer_fd(fd_55, ...)` → librga sees `fd_55` in its cache and returns the **stale `handle_A`**.
5. RGA job submitted → Hardware tries to access memory via `handle_A` (which points to freed or invalid memory) → IOMMU page fault (`Cannot get dst channel buffer`).

**The "Mixed Handle" Trap**: You might try to fix the destination buffer by importing it once and using `wrapbuffer_handle`, while leaving the dynamic source buffer as `wrapbuffer_fd`. **This will fail.** librga logs a warning: `librga only supports the use of handles only or no handles` and may abort or corrupt the operation. You must use handles for *all* buffers or *none*.

**Why it's amplified on RK3576**: The RGA scheduler directs **99.2% of jobs to core 4** (core 8 is largely idle). A single bad job on core 4 triggers `soft reset` on that core, and because the scheduler doesn't route around the dead core, no core is available at all.

### Evidence Patterns

| Evidence | What to check |
|---|---|
| `Cannot get dst channel buffer` | The `dst_fd` passed to `wrapbuffer_fd` or `importbuffer_fd` was already closed or the underlying buffer was reclaimed |
| `no core match` + `job assign failed` | Check `/proc/interrupts` — compare rga2 core counts; expect > 10:1 imbalance |
| `soft reset complete` followed by more `Cannot get dst` | Confirm the same dst buffer lifecycle pattern persists after reset |
| Per-frame `wrapbuffer_fd` without `importbuffer_fd` | Code pattern: search for `wrapbuffer_fd` calls in a loop/per-frame context with no matching `importbuffer_fd`/`releasebuffer_handle` |

### Fix

#### P0 — DMA-BUF buffer lifecycle (fix the root cause)

Replace all `wrapbuffer_fd` calls with explicit handle management to bypass the internal fd-cache and satisfy the "all handles or no handles" rule.

**1. Static Buffers (Destination / RKNN Input)**: Import once at initialization.

```cpp
// === Init (once per model load) ===
rga_buffer_handle_t dst_handle = importbuffer_fd(dst_fd, dst_size);
if (dst_handle == 0) { // Note: handle is int, 0 means failure in older versions, <=0 in newer
    // handle error
}

// === Per frame ===
rga_buffer_t dst = wrapbuffer_handle(dst_handle,
                                     width, height,
                                     RK_FORMAT_RGB_888,
                                     width_stride, height_stride);
// ... RGA operation ...
// (do NOT releasebuffer_handle here — reuse the handle next frame)

// === Shutdown ===
releasebuffer_handle(dst_handle);
```

**2. Dynamic Buffers (Source from Engine)**: Import and release **every frame** using RAII.

```cpp
class LocalHandleGuard {
public:
    ~LocalHandleGuard() { if (handle >= 0) releasebuffer_handle(handle); }
    int handle = -1;
};

// === Per-frame ===
LocalHandleGuard src_guard;
src_guard.handle = importbuffer_fd(source_fd, source_size); 
// Or importbuffer_virtualaddr(source_ptr, source_size) if Host memory
rga_buffer_t src = wrapbuffer_handle(src_guard.handle, ...);
```

**Why this works**: `importbuffer_fd()` creates a fresh, explicitly managed handle, bypassing librga's internal fd-cache. `releasebuffer_handle` ensures the handle is destroyed at the end of the frame, so recycled fds won't collide. Using `wrapbuffer_handle` for both source and destination satisfies librga's uniform handle requirement.

#### P1 — RGA core load balancing (fix the amplification)

```cpp
// Set core affinity to use both RGA2 cores
// Call once at app startup, after librga init
im_set_core_mask(IM_SCHEDULER_RGA2_CORE0 | IM_SCHEDULER_RGA2_CORE1);
// Or alternate frames:
// if (frame_count % 2 == 0)
//     im_set_core_mask(IM_SCHEDULER_RGA2_CORE0);
// else
//     im_set_core_mask(IM_SCHEDULER_RGA2_CORE1);
```

#### P2 — Error visibility

Before calling `improcess`/`imresize`, add buffer size validation:

```cpp
// Validate DMA-BUF size against format requirements
off_t buf_bytes = lseek(dst_fd, 0, SEEK_END);
size_t required = static_cast<size_t>(width_stride) * height_stride * 3;  // RGB_888
if (buf_bytes < static_cast<off_t>(required)) {
    fprintf(stderr, "[RGA] dst buffer too small: %jd < %zu\n",
            (intmax_t)buf_bytes, required);
}
```

### RK3576-specific context

| Property | Value |
|---|---|
| RGA cores | 2 (core 4 = `27920f00`, core 8 = `27930f00`) |
| Hardware version | `3.e.19357` |
| librga version | 1.10.4 |
| Driver version | v1.3.9 |
| Core mask enums | `IM_SCHEDULER_RGA2_CORE0`, `IM_SCHEDULER_RGA2_CORE1` |
| Diagnosis | `cat /proc/interrupts | grep rga2` — compare core 4 vs core 8 |

### Also check

- Does the algorithm share the same DMA-BUF between RGA output and NPU input simultaneously? If so, add a fence or sync point (`rknn_mem_sync` with `RKNN_MEMORY_SYNC_FROM_DEVICE`).
- Is `importbuffer_fd` called with the correct `size`? The size must match the full buffer accounting for stride alignment, not just `width * height * bpp`.
- Is `imcheck` called before every operation? It catches stride/format/rect violations before they reach hardware.

### References

- Board baseline: `.agents/context/rknn-context/linaro-alip-rk3576-k6.1.118-dev.md` (RGA capability analysis section)
- RGA API: [rga-api-reference.md](rga-api-reference.md)
- Original diagnosis: RGA DMA-BUF lifecycle cascade failure on RK3576


Rockchip's official RGA FAQ documents these patterns:

| Pattern or log | Audit implication | Evidence |
|---|---|---|
| RGA debug `check` mode says memory/alignment is checked and over-threshold memory can crash the kernel | Treat RGA size/stride violations as potential system-crash risks; never enable this mode casually on production | Official constraint |
| `Bad address` | Commonly an out-of-bounds or invalid src/src1/dst memory address | Official constraint |
| `err ws[...]` / `Error srcRect` | Require `x_offset + width <= width_stride`; apply the same rule to height | Official constraint |
| `failed to get vma/pte`, `set mmu info error`, `map ... memory failed` | Compare actual mapped/allocated bytes with bytes derived from format and physical strides | Official constraint |
| `dma_buf_get fail fd[...]` | Validate fd creation, ownership, lifetime, and availability before RGA submission | Official constraint |
| DRM virtual address passed after kernel kmap was released | Can cause kernel crash or bad page-table access; require compatible DRM allocation flags/kernel support or use a safe fd path | Official constraint |
| `RGA_MMU unsupported Memory larger than 4G` | Verify selected RGA core addressability and use DMA32/below-4G allocation where required | Official constraint |
| IRQ error or RGA timeout | First exclude out-of-bounds, invalid FBC mode, buffer still owned/locked elsewhere, bus faults, and resource contention | Official constraint |
| RGA handle cleanup messages at process exit | Pair each `importbuffer_*` with one `releasebuffer_handle`; repeated import needs repeated release | Official constraint |
| `Only get buffer X byte ... current required Y byte` | Import size must match the later format/strides; do not reuse an NV12-sized handle as RGBA | Official constraint |

Official source:
https://github.com/airockchip/librga/blob/master/docs/Rockchip_FAQ_RGA_EN.md

Useful community cases in the official librga tracker include padded-stride plus DMA-addressability
failures, invalid fd lifetime, and repeated virtual-address conversion crashes. Before using a case,
read its current comments and match SoC, kernel, librga, driver, allocator, format, and call form.

Issue search:
https://github.com/airockchip/librga/issues

## RKNN Runtime Memory, Cache, and Compatibility

The maintained RKNN API header documents:

- `rknn_mem_sync` is for cacheable memory accessed by both CPU and device.
- When input automatic cache flush is disabled, the user must flush before `rknn_run`.
- When output automatic cache invalidation is disabled, CPU access to `output_mem->virt_addr`
  requires `rknn_mem_sync(..., RKNN_MEMORY_SYNC_FROM_DEVICE)`.
- RKNN exposes distinct errors for allocation failure, invalid context/input/output, device/runtime
  mismatch, incompatible precompiled model, optimization-version mismatch, and target mismatch.

Official headers:

- https://github.com/airockchip/rknn-toolkit2
- https://github.com/airockchip/rknn_model_zoo/blob/main/3rdparty/rknpu2/include/rknn_api.h

The RKNN Toolkit2 changelog records relevant runtime evolution:

- v1.1.0: cache flushing for fd-pointed internal tensor memory and improved multi-thread/process
  stability;
- v1.2.0: improved zero-copy implementation;
- v1.3.0: `w_stride`/`h_stride` support and memory API changes;
- later releases continue to list bug fixes and operator/runtime changes.

Official history:
https://github.com/airockchip/rknn-toolkit2/blob/master/CHANGELOG.md

`failed to submit`, zero-length outputs, segmentation faults, or random results can also result from
runtime/driver/model mismatches or unsupported operators. Do not classify such a log as memory
corruption without the allocation/layout/lifetime path and version evidence.

Issue search:
https://github.com/airockchip/rknn-toolkit2/issues

## MPP Memory Exhaustion and Lifetime

Rockchip MPP's official readme states:

- in pure internal decode mode, frames may not be returned before decoder close; the official
  readme explicitly says "memory leak or crash may happen";
- internal mode can consume uncontrolled memory;
- half-internal mode permits group limits;
- external mode needs correct externally allocated buffer sizes;
- a safe decode allocation is `hor_stride * ver_stride * 2` including extra information;
- H.264/H.265 commonly need more than 20 buffers and other codecs commonly need around 10.

Official source:
https://github.com/rockchip-linux/mpp/blob/develop/readme.txt

The maintained `mpp_buffer.h` also defines reference counting, group limits, DMA32, contiguity,
kmap, cache synchronization, import/commit, and get/put contracts. Audit the installed header when
the local API differs.

Official source:
https://github.com/rockchip-linux/mpp/blob/develop/inc/mpp_buffer.h

## DMA-BUF and Fence Contracts

Linux kernel DMA-BUF documentation establishes that DMA-BUF is a shared object with exporter,
importer, mapping, and synchronization responsibilities. Relevant audit rules include:

- request `O_CLOEXEC` atomically to avoid fd leaks and cross-exec buffer exposure;
- treat fd size discovery as exporter/kernel dependent;
- pair CPU access and synchronization correctly;
- preserve dma-fence ordering and avoid buffer reuse/destruction while operations are in flight;
- uncontrolled or cyclic fence dependencies can cause hangs and timeouts.

Official source:
https://docs.kernel.org/driver-api/dma-buf.html

## How to Use Community Reports

For a matching issue:

1. Record issue URL, date, state, affected versions, SoC, allocator, and exact log.
2. Read maintainer replies and linked commits or FAQ sections.
3. Reproduce the invariant locally in source or on the selected board.
4. Classify it as **Community case** until official evidence confirms the cause.
5. Prefer the vendor's current fix or compatibility recommendation over copied workaround code.

Do not add a permanent hard rule to this skill from one unresolved report alone.
