# Zero-Copy Pipeline Guide

## Goal

Keep video or camera frames in shared DMA-capable memory from producer to consumer, and avoid unnecessary CPU copies or remaps.

## Kernel-Level Ground Truth

The Linux V4L2 DMA-BUF importer API documents that:

- A device that supports streaming I/O can accept DMA-BUF-backed buffers via `V4L2_MEMORY_DMABUF`.
- DMA-BUF file descriptors are queued via `VIDIOC_QBUF`.
- Single-plane and multi-plane APIs both support DMA-BUF-backed queueing.

The Linux dma-buf documentation describes the model as:

- Shared buffers exposed as file descriptors
- Cross-device and cross-subsystem sharing
- Synchronization through `dma-fence` and `dma-resv`

That means a zero-copy design still needs correct synchronization. No memcpy does not mean no waits.

## Rockchip-Specific Pipeline Shape

On Rockchip Linux systems, the common high-performance path is:

`V4L2 capture or MPP decode -> DMA-BUF fd -> RGA -> DMA-BUF fd -> RKNN Runtime -> postprocess -> display or encoder`

The critical design question at each hop is:

- Does the next stage consume the same fd directly
- Or does the code map to CPU memory, repack, and submit a new buffer

## MPP Guidance

Rockchip MPP documentation describes three decoder memory modes. For zero-copy-oriented work:

- Pure internal mode is easy to start with and gives the application less pool control. Its returned
  `MppBuffer` may still expose a DMA-BUF fd usable by downstream hardware.
- Half internal mode gives the application group limits and lifecycle control.
- Pure external mode is useful when the application/display allocator must own the pool; the MPP
  README describes it as efficient for its zero-copy display workflow, not as a prerequisite for
  every decode-to-accelerator handoff.

When MPP output feeds display or another accelerator, inspect the selected mode and pool ownership,
then verify whether the returned `MppBuffer` fd, size, layout, synchronization, and lifetime are
actually import-compatible. Allocation mode alone does not prove or disprove zero-copy.

### What Pure External Mode Implies In Practice

MPP's README states that pure external mode requires an empty `MppBufferGroup` populated from an
external allocator. Its stride-based size and codec buffer-count examples are historical rules of
thumb for that documented path, not universal allocation contracts. At information change, use
`mpp_frame_get_buf_size(frame)` and the reported format/strides, then confirm the actual capacity
with `mpp_buffer_get_size`. Bound the group from measured stream requirements and memory budget.

Design consequence:

- If a project wants decode-to-display or decode-to-preprocess zero-copy, it should own buffer-pool design explicitly instead of relying on decoder-private allocation.
- If buffer count is too low, the pipeline may look like a performance problem when it is actually backpressure.

## RGA Guidance

Rockchip's RGA FAQ documents several constraints that matter in zero-copy paths:

- `dma_fd` is generally the recommended memory type for balancing efficiency and usability.
- Virtual-address submission is slower and more CPU-sensitive.
- Different image formats have alignment requirements, especially stride and YUV geometry.
- Driver and `librga` version mismatches can cause compatibility mode or failures.
- `importbuffer_fd()` is intentionally expensive and should not be done every frame if the buffer set is reusable.

Design consequence:

- Prefer passing DMA-BUF fds into RGA.
- Keep a per-stage record of `format`, `width`, `height`, `w_stride`, `h_stride`, and plane layout.
- If RGA starts failing with parameter errors, check alignment and driver or library compatibility before rewriting the pipeline.
- If RGA is called on a rolling pool of buffers, import once and reuse `buffer_handle` objects rather than import and release every frame.

### RGA Alignment Rules That Commonly Bite

The RGA FAQ makes several specific points:

- Alignment requirements differ by hardware generation, format, and read mode.
- In common raster modes, RGA2-family RGB888/NV12 width strides use a 4-pixel multiple while RGA3
  uses 16; RGA3 RGB565 and RGBA8888 have their own 8- and 4-pixel multiples.
- Raster YUV logical dimensions and offsets are even; ten-bit and non-linear modes add stricter rules.

The FAQ shows a concrete `imcheck()` failure where logical NV12 width 1281 is not even. Padding the
stride alone does not make odd logical YUV geometry valid. Consult the exact RGA generation table
and use `imcheck()` for the complete request.

Use that as a first-pass filter when RGA rejects an otherwise plausible pipeline.

### DMA-BUF Is Better, Not Free

The RGA FAQ compares memory types and recommends `dma_fd` as the practical balance between efficiency and usability. It also notes that:

- Virtual-address paths add CPU cost for page-table work.
- Cacheable buffers can still trigger expensive cache synchronization even when using `dma_fd`.
- Common allocator behavior can change the cost profile.

Therefore:

- `dma_fd` is the preferred default, but high CPU with `dma_fd` can still be real.
- If CPU remains high, compare allocator behavior and cacheability before concluding the zero-copy design failed.

## Common Copy Traps

- V4L2 dequeue to CPU pointer, then memcpy into a new RKNN input buffer
- MPP decode to internal buffers, then software conversion before display or inference
- RGA called with virtual addresses because DMA-BUF wrapping was skipped
- RKNN output always read back to CPU even when only lightweight metadata is needed
- Hidden colorspace conversion in a stage that does not accept the upstream format

## What To Prove Before Claiming Zero-Copy

- Buffer producer type
- Original allocation owner
- Exported fd count and lifetime
- Which subsystem imports the fd next
- Whether any stage maps the buffer into CPU space for a full-frame walk
- Whether cache synchronization is required because a stage uses CPU-visible cached memory
- Whether fences or dequeue waits dominate runtime even though copies are gone

## Debug Procedure

1. Draw the exact buffer lineage from source to sink.
2. Log every fd import, wrap, map, unmap, and release.
3. Time each stage separately.
4. Compare a DMA-BUF path against a virtual-address path if unsure where the CPU is burning time.
5. If RGA is present, enable its logs or debug nodes before assuming the bottleneck is inference.
6. If decode is involved, inspect whether the external-buffer path is really active or only planned in comments.

## Sources

- Linux kernel V4L2 DMA-BUF importer API: https://docs.kernel.org/userspace-api/media/v4l/dmabuf.html
- Linux kernel dma-buf overview: https://docs.kernel.org/driver-api/dma-buf.html
- Rockchip MPP README (snapshot `df4864b`): https://github.com/rockchip-linux/mpp/blob/df4864bd1e907cbfd427c397348976c5b2b05ee9/readme.txt
- Rockchip librga FAQ (snapshot `2b32edc`): https://github.com/airockchip/librga/blob/2b32edcb97b601b25683e2941d888c8515da6d55/docs/Rockchip_FAQ_RGA_EN.md
