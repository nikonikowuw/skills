# API Quick Reference

Condensed API signatures for the three core Rockchip subsystems. For full documentation,
see the dedicated reference files:
- [rknn-api-reference.md](rknn-api-reference.md) — complete RKNN Runtime API
- [rga-api-reference.md](rga-api-reference.md) — complete RGA im2d API
- [mpp-api-reference.md](mpp-api-reference.md) — complete MPP decode/encode API

> This file is an index, not a contract. The full reference files above are authoritative within
> this skill, and the installed headers (`rknn_api.h`, `im2d.hpp`/`im2d.h`, `rk_mpi.h`,
> `mpp_buffer.h`) override both. If a signature here disagrees with the target header, trust the
> header and fix this file.

## RKNN Runtime — Core

```c
// Initialize runtime
int rknn_init(rknn_context *ctx, void *model, uint32_t size, uint32_t flag, rknn_init_extend *extend);
// flag: 0 (default), RKNN_FLAG_PRIOR_MEDIUM, RKNN_FLAG_PRIOR_HIGH, RKNN_FLAG_PRIOR_LOW
//       RKNN_FLAG_ASYNC_MASK, RKNN_FLAG_COLLECT_PERF_MASK
// ASYNC_MASK has previous-frame output semantics in current headers; it is not a generic
// nonblocking-run or same-context multithreading guarantee. Read the selected target header.

// Duplicate a context; both parameters are pointers. The header does not promise weight sharing.
int rknn_dup_context(rknn_context *context_in, rknn_context *context_out);

// Query model I/O info
int rknn_query(rknn_context ctx, rknn_query_cmd cmd, void *info, uint32_t info_size);
// cmd: RKNN_QUERY_IN_OUT_NUM, RKNN_QUERY_INPUT_ATTR, RKNN_QUERY_OUTPUT_ATTR, etc.

// Set inputs
int rknn_inputs_set(rknn_context ctx, uint32_t n_inputs, rknn_input inputs[]);

// Run inference (sync)
int rknn_run(rknn_context ctx, rknn_run_extend *extend);

// Get outputs
int rknn_outputs_get(rknn_context ctx, uint32_t n_outputs, rknn_output outputs[], rknn_output_extend *extend);

// Release outputs
int rknn_outputs_release(rknn_context ctx, uint32_t n_outputs, rknn_output outputs[]);

// Destroy context
int rknn_destroy(rknn_context ctx);
```

## RKNN Runtime — Zero-Copy Memory

```c
// Create internal memory (device-side, accessible by NPU)
rknn_tensor_mem *rknn_create_mem(rknn_context ctx, uint32_t size);

// Import a DMA-BUF fd as NPU memory (zero-copy).
// virt_addr: CPU mapping of the buffer (may be NULL when no CPU access is needed; follow the
//            installed header's comment). offset: byte offset of the tensor data inside the fd.
rknn_tensor_mem *rknn_create_mem_from_fd(rknn_context ctx, int32_t fd, void *virt_addr, uint32_t size, int32_t offset);

// Create memory from a physical address (virt_addr is the matching CPU mapping)
rknn_tensor_mem *rknn_create_mem_from_phys(rknn_context ctx, uint64_t phys_addr, void *virt_addr, uint32_t size);

// Set tensor with memory handle. In the current header w_stride is read-only and h_stride is
// write-only; preserve the queried width stride and set height stride from the backing layout.
int rknn_set_io_mem(rknn_context ctx, rknn_tensor_mem *mem, rknn_tensor_attr *attr);

// Destroy memory
int rknn_destroy_mem(rknn_context ctx, rknn_tensor_mem *mem);
```

## RKNN Runtime — NPU Core Mask (multi-core)

```c
// Set which NPU cores to use
int rknn_set_core_mask(rknn_context ctx, rknn_core_mask core_mask);
// The enum includes AUTO, CORE_0, CORE_1, CORE_2, CORE_0_1, CORE_0_1_2 and ALL
// in current headers. Availability is platform/runtime-specific; validate the selected target.
```

## RGA — Buffer Import and Processing (im2d API)

```c
// Import DMA-BUF fd for RGA processing
rga_buffer_handle_t importbuffer_fd(int fd, int size);

// Import virtual address buffer
rga_buffer_handle_t importbuffer_virtualaddr(void *virt_addr, int size);

// Release imported buffer
int releasebuffer_handle(rga_buffer_handle_t handle);

// Create RGA buffer handle from fd/virt
rga_buffer_t wrapbuffer_handle(rga_buffer_handle_t handle, int width, int height, int format, int w_stride, int h_stride);

// Resize
IM_STATUS imresize(const rga_buffer_t src, rga_buffer_t dst, double fx, double fy, int interpolation, int sync);

// Crop (no interpolation parameter; rect must match the dst geometry —
// for crop + resize in one pass use improcess with src/dst rects)
IM_STATUS imcrop(const rga_buffer_t src, rga_buffer_t dst, im_rect rect, int sync);

// Combined op (crop/scale/convert driven by rects and usage flags)
IM_STATUS improcess(rga_buffer_t src, rga_buffer_t dst, rga_buffer_t pat,
                    im_rect srect, im_rect drect, im_rect prect, int usage);

// Color space conversion
IM_STATUS imcvtcolor(rga_buffer_t src, rga_buffer_t dst, int sfmt, int dfmt, int mode);

// Flip / rotate
IM_STATUS imflip(const rga_buffer_t src, rga_buffer_t dst, int mode, int sync);
IM_STATUS imrotate(const rga_buffer_t src, rga_buffer_t dst, int rotation, int sync);

// Validate parameters before calling (returns IM_STATUS). im_rect is passed BY VALUE.
IM_STATUS imcheck(const rga_buffer_t src, const rga_buffer_t dst, const im_rect src_rect, const im_rect dst_rect, int mode_usage);

// Sync — waits for RGA task completion. Older librga releases declare imsync(void);
// newer releases take a fence fd. Follow the installed im2d header.
IM_STATUS imsync(...);
```

## MPP — Decode (External Buffer Mode)

```c
// Create MPP decoder
MPP_RET mpp_create(MppCtx *ctx, MppApi **mpi);
MPP_RET mpp_init(MppCtx ctx, MppCtxType type, MppCodingType coding);

// Decode through MppApi function pointers
MPP_RET ret = mpi->decode_put_packet(ctx, packet);
ret = mpi->decode_get_frame(ctx, &frame);

// Set an external decoder group
ret = mpi->control(ctx, MPP_DEC_SET_EXT_BUF_GROUP, group);

// Create external buffer group (macro over mpp_buffer_group_get; two arguments)
MPP_RET mpp_buffer_group_get_external(MppBufferGroup *group, MppBufferType type);

// Commit MppBufferInfo to a group, or import it as a standalone MppBuffer
MPP_RET mpp_buffer_commit(MppBufferGroup group, MppBufferInfo *info);
MPP_RET mpp_buffer_import(MppBuffer *buffer, MppBufferInfo *info);

// Reset / destroy
MPP_RET mpp_reset(MppCtx ctx);
MPP_RET mpp_destroy(MppCtx ctx);
```
