# Rockchip MPP API Reference

Use the target BSP's `rk_mpi.h`, `rk_mpi_cmd.h`, `mpp_buffer.h`, and upstream examples as the API
contract. MPP headers and board forks vary, so compile against the selected sysroot before relying on
an example.

## Capability Verification

Do not use a generic SoC codec/resolution/bit-depth table as proof for a board image. Verify:

1. the SoC TRM or board-vendor multimedia specification;
2. the selected MPP commit and BSP release notes;
3. `mpp_check_support_format()` / `mpp_show_support_format()` from the deployed library;
4. the actual stream profile, level, bit depth, chroma format, dimensions, and reference-frame needs;
5. a decode/encode test on the target image, including resolution changes and long-running load.

Library support, kernel-driver support, and a codec headline are separate facts. Record all three.

## Core Lifecycle

Current upstream `rk_mpi.h` exposes:

```c
MPP_RET mpp_create(MppCtx *ctx, MppApi **mpi);
MPP_RET mpp_init(MppCtx ctx, MppCtxType type, MppCodingType coding);
MPP_RET mpp_destroy(MppCtx ctx);
MPP_RET mpp_check_support_format(MppCtxType type, MppCodingType coding);
void mpp_show_support_format(void);
```

Data flow and control calls are function pointers in `MppApi`, not free functions named
`mpp_decode_put_frame` or `mpp_set_ext_grp`:

```c
MppCtx ctx = NULL;
MppApi *mpi = NULL;

MPP_RET ret = mpp_create(&ctx, &mpi);
if (ret != MPP_OK) {
    return ret;
}

ret = mpp_init(ctx, MPP_CTX_DEC, MPP_VIDEO_CodingHEVC);
if (ret != MPP_OK) {
    mpp_destroy(ctx);
    return ret;
}

ret = mpi->decode_put_packet(ctx, packet);
if (ret == MPP_OK) {
    ret = mpi->decode_get_frame(ctx, &frame);
}

mpi->reset(ctx);
mpp_destroy(ctx);
```

Check every return code and preserve ownership of packets, frames, groups, and buffers on all error
paths. Whether a retry is appropriate depends on the API result and queue state.

## Decoder Information Change

MPP reports format/resolution changes through a frame marked with `mpp_frame_get_info_change(frame)`.
At that point:

1. Query width, height, horizontal/vertical stride, format, and
   `mpp_frame_get_buf_size(frame)` from the frame.
2. Validate every dimension and size calculation before allocating or importing buffers.
3. Configure or replace the buffer group for the new layout.
4. Call `mpi->control(ctx, MPP_DEC_SET_EXT_BUF_GROUP, group)` when using that external group.
5. Signal `mpi->control(ctx, MPP_DEC_SET_INFO_CHANGE_READY, NULL)` only after the group is ready.
6. Retire old buffers only after every downstream RGA/RKNN/display/encoder user has completed.

Do not hard-code one H.264/H.265 stride formula or buffer count. Use the frame-reported layout and
the selected MPP/BSP requirements, then enforce an explicit memory budget.

## Buffer Groups and DMA-BUF Import

Current upstream `mpp_buffer.h` defines group creation macros and a structured import contract:

```c
MppBufferGroup group = NULL;
MPP_RET ret = mpp_buffer_group_get_external(&group, MPP_BUFFER_TYPE_DRM);
if (ret != MPP_OK) {
    return ret;
}

MppBufferInfo info = {
    .type = MPP_BUFFER_TYPE_DRM,
    .size = dma_buf_size,
    .ptr = NULL,
    .hnd = NULL,
    .fd = dma_buf_fd,
    .index = buffer_index,
};

ret = mpp_buffer_commit(group, &info);  // add an unused external buffer to the group
if (ret != MPP_OK) {
    mpp_buffer_group_put(group);
    return ret;
}
ret = mpi->control(ctx, MPP_DEC_SET_EXT_BUF_GROUP, group);
if (ret != MPP_OK) {
    mpp_buffer_group_put(group);
    return ret;
}
```

For a one-off imported buffer rather than a decoder group:

```c
MppBuffer buffer = NULL;
MPP_RET ret = mpp_buffer_import(&buffer, &info);
if (ret == MPP_OK) {
    // Use buffer, then release the MPP reference.
    mpp_buffer_put(buffer);
}
```

Relevant current signatures/macros include:

```c
MPP_RET mpp_buffer_group_put(MppBufferGroup group);
MPP_RET mpp_buffer_group_clear(MppBufferGroup group);
MPP_RET mpp_buffer_group_limit_config(MppBufferGroup group, size_t size, RK_S32 count);
int mpp_buffer_get_fd(MppBuffer buffer);
size_t mpp_buffer_get_size(MppBuffer buffer);
MPP_RET mpp_buffer_put(MppBuffer buffer);
```

Never substitute the obsolete/nonexistent form `mpp_buffer_import(group, fd, size)`. Compile-time
feature checks are preferable when supporting materially different vendor headers.

## Zero-Copy Boundary

"Zero-copy" describes the complete handoff, not merely the MPP buffer mode:

- An internally allocated `MppBuffer` may still expose a DMA-BUF fd that downstream hardware can
  import without a pixel copy.
- An external group is useful when the application must control allocation or share a pool, but it
  does not guarantee that RGA, RKNN, display, or encode accepts the same format/layout.
- `mpp_buffer_get_ptr` or `mmap` creates CPU access but is not itself a pixel copy. A CPU full-frame
  walk/conversion or copy into a second DMA-BUF is a data-movement boundary. All require
  cache/lifetime review.
- Prove fd identity, allocation size, plane offsets, stride, format, fences/cache synchronization,
  and ownership at every stage.

Prefer the least complex buffer mode that satisfies the actual ownership and interoperability
requirements. Do not mandate pure external mode without first proving it is required.

## Cache and Lifetime Rules

- Pair every `MppBuffer` reference with `mpp_buffer_put` and every group with
  `mpp_buffer_group_put` after all users finish.
- Do not close an imported DMA-BUF fd or recycle its backing storage while MPP or downstream
  asynchronous hardware may still access it.
- Use the selected allocator/exporter and MPP cache-sync APIs according to the BSP contract. Avoid
  assuming implicit coherence across CPU, decoder, RGA, NPU, encoder, and display.
- Bound group size/count with `mpp_buffer_group_limit_config` where supported, and handle allocation
  failure without unbounded retry loops.
- Treat info-change, seek/reset, EOS, reload, and shutdown as ownership transitions that need tests.

## Diagnostic Checklist

- [ ] Target `rk_mpi.h` and `mpp_buffer.h` paths and library linkage recorded
- [ ] MPP commit/version and kernel/BSP recorded
- [ ] Codec support checked through target API plus board documentation
- [ ] Stream profile, level, bit depth, chroma, dimensions, and reference-frame load recorded
- [ ] `MppApi` function-pointer calls used with checked return values
- [ ] Information-change handshake and buffer retirement tested
- [ ] Buffer group count and total DMA memory bounded
- [ ] DMA-BUF size, layout, fd ownership, cache sync, and downstream lifetime proven
- [ ] EOS, reset, malformed stream, resolution change, and shutdown tested

## Sources

- Upstream MPP README (snapshot `df4864b`): https://github.com/rockchip-linux/mpp/blob/df4864bd1e907cbfd427c397348976c5b2b05ee9/readme.txt
- `rk_mpi.h`: https://github.com/rockchip-linux/mpp/blob/df4864bd1e907cbfd427c397348976c5b2b05ee9/inc/rk_mpi.h
- `mpp_buffer.h`: https://github.com/rockchip-linux/mpp/blob/df4864bd1e907cbfd427c397348976c5b2b05ee9/inc/mpp_buffer.h
- Decoder example: https://github.com/rockchip-linux/mpp/blob/df4864bd1e907cbfd427c397348976c5b2b05ee9/test/mpi_dec_test.c
