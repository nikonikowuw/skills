# Rockchip Known Crash and Stability Patterns

Use this page to map source findings and board logs to documented failure modes. Re-check the live
source when versions differ; these references are evidence anchors, not substitutes for the
installed BSP and headers.

## Evidence Labels

- **Official constraint**: Rockchip documentation, maintained header/source, or Linux kernel docs.
- **Official history**: Rockchip changelog describing when a capability or stability fix appeared.
- **Community case**: issue report in an official repository; use as a search/reproduction clue
  unless a maintainer or official document confirms the cause.

## RGA Memory, Layout, and Kernel-Facing Failures

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
https://github.com/airockchip/librga/blob/2b32edcb97b601b25683e2941d888c8515da6d55/docs/Rockchip_FAQ_RGA_EN.md

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
- external mode needs correctly sized externally allocated buffers;
- the README's stride-based size and codec pool-count examples are rules of thumb for its
  documented path, not universal contracts;
- current code should use the information-change frame's `mpp_frame_get_buf_size`, verify the
  attached `MppBuffer` capacity, and bound the pool for the actual codec/stream/BSP.

Official source:
https://github.com/rockchip-linux/mpp/blob/df4864bd1e907cbfd427c397348976c5b2b05ee9/readme.txt

The maintained `mpp_buffer.h` also defines reference counting, group limits, DMA32, contiguity,
kmap, cache synchronization, import/commit, and get/put contracts. Audit the installed header when
the local API differs.

Official source:
https://github.com/rockchip-linux/mpp/blob/df4864bd1e907cbfd427c397348976c5b2b05ee9/inc/mpp_buffer.h

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
