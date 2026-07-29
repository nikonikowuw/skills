# RGA API Reference

Rockchip RGA (Raster Graphics Acceleration) is a 2D hardware accelerator for fixed-function
image processing. Use the **im2d API** (modern, recommended).

## RGA Capabilities and Limitations

| Common fixed-function building blocks | Hardware/library/version-specific; verify | Not a general RGA contract |
| --- | --- | --- |
| Crop, scale, format conversion, and color-space conversion | Exact input/output formats, CSC modes, interpolation, scale ratios, and resolutions | Arbitrary GPU-style shaders or user kernels |
| 90/180/270 rotation, mirror, and translation | Alpha blend, color key, color fill/palette, and ROP | Arbitrary affine matrices, perspective, or homography |
| DMA-BUF-backed source/destination processing | Quantize, rectangle/border, mosaic, OSD, Gaussian blur on listed hardware | General convolution/filter, morphology, histogram/statistics, or text/shape rasterization |
| Synchronous and asynchronous submissions | Compound, array, task/job APIs and compressed/tiled read modes | An undocumented format/operation combination merely because another RGA core supports it |

RGA is a fixed-function 2D block, not a programmable shader. The API surface can be broader than a
given core's capability: match SoC/core/format/read mode against the pinned guide, query available
capabilities where supported, and require `imcheck` success. If the exact request is unsupported,
choose a measured CPU, GPU, NPU, or multi-stage fallback appropriate to the application.

### When to use RGA vs CPU vs NPU

| Criterion | RGA | CPU (NEON) | NPU (RKNN) |
| --- | --- | --- | --- |
| Resize + CSC | Fixed-function candidate when the exact combination validates | Flexible fallback | Model-specific and usually unnecessary |
| Crop | Can retain DMA-BUF backing; ownership/sync still required | Flexible fallback | Usually unnecessary |
| Rotate / Flip | Common fixed-function operation | Flexible fallback | Model-dependent |
| Arbitrary affine / perspective | No general matrix-warp contract | OpenCV or another validated engine | Custom-model option |
| Multi-step pipeline | Use supported compound/task/job APIs or explicit fenced stages | Full control | Model-dependent batching |
| Small images | Submission overhead may dominate; measure | Often competitive; measure | Measure only when already model-based |

## Buffer Import

### `importbuffer_fd`

```c
rga_buffer_handle_t importbuffer_fd(int fd, int size);
```

Import a DMA-BUF file descriptor for RGA processing. This is the **preferred zero-copy path**.

- `fd`: DMA-BUF file descriptor (from V4L2, MPP, DRM, dma_heap, etc.)
- `size`: buffer size in bytes
- Returns: opaque handle; reject the installed API's invalid/zero-handle result

**Performance:** importing has measurable setup cost. Import once and reuse handles when the buffer
pool is reusable; when buffers are genuinely ephemeral, measure the import path and preserve exact
fd/handle lifetime rather than caching stale handles.

### `importbuffer_virtualaddr`

```c
rga_buffer_handle_t importbuffer_virtualaddr(void *virt_addr, int size);
```

Import a CPU virtual address. This can add page-table and cache-maintenance cost. Use it for a
CPU-owned source or when no compatible DMA-BUF path exists, then compare the measured result.

### `releasebuffer_handle`

```c
int releasebuffer_handle(rga_buffer_handle_t handle);
```

Release an imported buffer handle.

---

## Wrapping Buffers

### `wrapbuffer_handle`

```c
rga_buffer_t wrapbuffer_handle(rga_buffer_handle_t handle, int width, int height, int format, int w_stride, int h_stride);
```

Create an `rga_buffer_t` from a previously imported buffer handle.

| Parameter | Description |
| --- | --- |
| `handle` | Handle from `importbuffer_fd` |
| `width` | Image width in pixels |
| `height` | Image height in pixels |
| `format` | Pixel format enum (`RK_FORMAT_*`) |
| `w_stride` | Width stride (aligned width). Must meet format alignment requirements |
| `h_stride` | Height stride (aligned height) |

Librga headers commonly expose this stride-aware macro invocation:

```c
rga_buffer_t dst = wrapbuffer_fd(fd, width, height, format, w_stride, h_stride);
```

When the destination fd is an RKNN input allocation, pass the queried read-only model `w_stride`
and the actual backing allocation's `h_stride` explicitly. The current RKNN header defines
`h_stride` as write-only, so a queried value is not evidence. The short/default-stride wrapper can
describe a tightly packed buffer even when RKNN/backing memory uses padded rows.

The underlying C symbol may be declared as
`wrapbuffer_fd_t(fd, width, height, w_stride, h_stride, format)`, with a different parameter order.
Follow the installed header and do not substitute the `_t` symbol's order into the public macro call.

### `wrapbuffer_virtualaddr`

```c
rga_buffer_t wrapbuffer_virtualaddr(void *virt_addr, int width, int height, int format, int w_stride, int h_stride);
```

Wrap a CPU-accessible virtual address.

---

## Processing Operations

### `imresize`

```c
IM_STATUS imresize(const rga_buffer_t src, rga_buffer_t dst, double fx, double fy, int interpolation, int sync);
```

Resize image from `src` to `dst`.

| Parameter | Description |
| --- | --- |
| `fx`, `fy` | Scale factors (0.0 = use dst size, >0 = scale factor) |
| `interpolation` | `INTER_LINEAR` (default), `INTER_CUBIC`, `INTER_NEAREST` |
| `sync` | 1 = synchronous (wait for completion), 0 = async |

### `imcrop`

```c
IM_STATUS imcrop(const rga_buffer_t src, rga_buffer_t dst, im_rect rect, int sync);
```

Crop a rectangle from source. `im_rect = {x, y, w, h}`. There is no interpolation parameter, and
`imcrop` does **not** resize — the dst geometry must match the rect. For one-pass crop + scale
(e.g., detection box → classifier input), use `improcess` with explicit src/dst rects.

### `improcess`

```c
IM_STATUS improcess(rga_buffer_t src, rga_buffer_t dst, rga_buffer_t pat,
                    im_rect srect, im_rect drect, im_rect prect, int usage);
```

Combined operation driven by rects and usage flags: `srect` selects the source region, which is
scaled/converted into `drect` of the destination. Pass empty (`{}`) `pat`/`prect` when no pattern
blend is used, and `IM_SYNC` in `usage` for synchronous execution.

Core selection is not a `usage` flag. Current librga exposes scheduler values such as
`IM_SCHEDULER_RGA3_CORE0` through either `imconfig(IM_CONFIG_SCHEDULER_CORE, value)` for the current
thread or `im_opt_t.core` with an extended `improcess` overload. Availability depends on the SoC,
driver, librga, and header. The official guide warns that core/priority configuration can cause a
system crash or deadlock and advises using it only for development/debugging, not production.
Leave automatic scheduling enabled in production unless the platform vendor supplies a validated
product-specific contract. Never OR scheduler enums into `usage`.

### `imcvtcolor`

```c
IM_STATUS imcvtcolor(rga_buffer_t src, rga_buffer_t dst, int sfmt, int dfmt, int mode);
```

Color space conversion. `sfmt`/`dfmt` are `RK_FORMAT_*` enums.

Common conversions:

- `RK_FORMAT_YCbCr_420_SP` (NV12) → `RK_FORMAT_RGB_888`
- `RK_FORMAT_RGB_888` → `RK_FORMAT_YCbCr_420_SP`
- `RK_FORMAT_RGBA_8888` → `RK_FORMAT_RGB_888`

### `imflip`

```c
IM_STATUS imflip(const rga_buffer_t src, rga_buffer_t dst, int mode, int sync);
```

| `mode` | Description |
| --- | --- |
| `IM_HAL_TRANSFORM_FLIP_H` | Horizontal flip |
| `IM_HAL_TRANSFORM_FLIP_V` | Vertical flip |
| `IM_HAL_TRANSFORM_FLIP_H_V` | Both |

### `imrotate`

```c
IM_STATUS imrotate(const rga_buffer_t src, rga_buffer_t dst, int rotation, int sync);
```

| `rotation` | Description |
| --- | --- |
| `IM_HAL_TRANSFORM_ROT_90` | 90° clockwise |
| `IM_HAL_TRANSFORM_ROT_180` | 180° |
| `IM_HAL_TRANSFORM_ROT_270` | 270° clockwise |

### `imtranslate`

```c
IM_STATUS imtranslate(const rga_buffer_t src, rga_buffer_t dst, int dx, int dy, int sync);
```

Translate (shift) image by `dx`, `dy` pixels.

---

## Validation

### `imcheck`

```c
IM_STATUS imcheck(const rga_buffer_t src, const rga_buffer_t dst, const im_rect src_rect, const im_rect dst_rect, int mode_usage);
```

Validate RGA parameters **before** calling the operation. `im_rect` arguments are passed **by
value**, not by pointer; `mode_usage` defaults to 0 in the C++ declaration. Success is
`IM_STATUS_NOERROR`.

**Always call `imcheck` before production operations** — RGA returns opaque errors on invalid parameters.
This is especially important when buffer dimensions or formats come from runtime data.

---

## Pixel Formats (`RK_FORMAT_*`)

| Enum | Description | Bytes per pixel |
| --- | --- | --- |
| `RK_FORMAT_RGB_565` | RGB 565 | 2 |
| `RK_FORMAT_RGB_888` | RGB 888 | 3 |
| `RK_FORMAT_RGBA_8888` | RGBA 8888 | 4 |
| `RK_FORMAT_BGRA_8888` | BGRA 8888 | 4 |
| `RK_FORMAT_YCbCr_420_SP` | NV12 (Y+UV) | 1.5 |
| `RK_FORMAT_YCbCr_422_SP` | NV16 | 2 |

---

## Alignment Rules (Common Pitfalls)

Raster alignment depends on hardware generation and format:

| Core family | RGBA8888 width stride | RGB565 width stride | RGB888 width stride | NV12/NV21 width stride |
| --- | ---: | ---: | ---: | ---: |
| RGA2 family | no additional pixel multiple | 2 | 4 | 4 |
| RGA3 | 4 | 8 | 16 | 16 |

For raster NV12/NV21, x/y offsets, logical width/height, and height stride must also be even. An odd
logical width such as 1281 remains invalid even if the backing stride is rounded up. RGA3 ten-bit
YUV requires a width stride multiple of 64 and x/y offsets multiple of 4; FBC and tile read modes add
their own constraints. If the driver can schedule a request onto several generations, satisfy the
strictest applicable rule. Use checked arithmetic from
[memory-alignment.md](memory-alignment.md) for byte sizing and run `imcheck` on the complete request.

### Unaligned Cascade Cropping (Two-Stage Networks)

In multi-model cascades (for example detection, crop, then recognition), a detector can produce a
rectangle that violates the selected source format/core/read-mode constraints. For raster NV12,
`x`, `y`, width, and height must be even. RGB constraints differ and must not inherit an arbitrary
byte-based ROI rule.

**Workaround:**

1. Determine pixel-coordinate multiples from the source format, selected read mode, and eligible
   hardware cores. Do not confuse byte-stride alignment with pixel-coordinate alignment.
2. Expand with overflow-checked align-down/align-up operations, then clamp to source bounds while
   preserving the required multiples. Reject empty or unrepresentable rectangles.
3. Run `imcheck` with the exact source/destination rectangles and operation flags before submission.
4. If the model contract requires the exact unsnapped crop, use a verified fallback; do not assume
   extra context is harmless.

**Critical: `importbuffer_fd()` is expensive — call once per buffer, reuse handles.**

### RKNN destination contract

For RGA preprocessing directly into NPU input memory, derive the destination layout from the RKNN
input attribute and carry it through the RGA helper API:

```cpp
const rknn_tensor_attr& input_attr = model->GetInputAttr(0);
const int dst_w_stride = input_attr.w_stride != 0
    ? CheckedUint32ToInt(input_attr.w_stride)
    : model_width;
// h_stride is write-only in the current RKNN header; use the real backing layout.
const int dst_h_stride = CheckedUint32ToInt(rga_destination_h_stride);

rga_buffer_t dst = wrapbuffer_fd(dst_fd,
                                 model_width,
                                 model_height,
                                 RK_FORMAT_RGB_888,
                                 dst_w_stride,
                                 dst_h_stride);
```

In the current RKNN header, `w_stride` is read-only: query it and make RGA/backing memory satisfy it.
`h_stride` is write-only: set it from this real destination layout when calling `rknn_set_io_mem`.
Use `wrapbuffer_handle(..., dst_w_stride, dst_h_stride)` when the installed librga does not expose
the stride-aware fd overload. Size the backing DMA-BUF from these same strides and the pixel format,
not merely from `model_width * model_height`. Run `imcheck` before the operation.

---

## Typical Usage Pattern

```c
// === Setup (once) ===

// Source: DMA-BUF fd from V4L2/MPP
rga_buffer_handle_t src_handle = importbuffer_fd(src_fd, CheckedSizeToInt(src_size));
if (src_handle == 0) return -1;
rga_buffer_t src = wrapbuffer_handle(src_handle, src_w, src_h,
                                     RK_FORMAT_YCbCr_420_SP, src_w_stride, src_h_stride);

// Destination: DMA-BUF fd from dma_heap or pre-allocated
rga_buffer_handle_t dst_handle = importbuffer_fd(dst_fd, CheckedSizeToInt(dst_size));
if (dst_handle == 0) {
    releasebuffer_handle(src_handle);
    return -1;
}
rga_buffer_t dst = wrapbuffer_handle(dst_handle, dst_w, dst_h,
                                     RK_FORMAT_RGB_888, dst_w_stride, dst_h_stride);

// === Per frame ===

// Validate (im_rect by value; success is IM_STATUS_NOERROR)
im_rect src_rect = {0, 0, src_w, src_h};
im_rect dst_rect = {0, 0, dst_w, dst_h};
IM_STATUS ret = imcheck(src, dst, src_rect, dst_rect, 0);
if (ret != IM_STATUS_NOERROR) {
    printf("RGA imcheck failed: %s\n", imStrError(ret));
    releasebuffer_handle(src_handle);
    releasebuffer_handle(dst_handle);
    return -1;
}

// Convert NV12 -> RGB888 + resize to 640x640
ret = imresize(src, dst, 0, 0, INTER_LINEAR, 1);  // sync=1
if (ret != IM_STATUS_SUCCESS) {
    printf("RGA resize failed: %s\n", imStrError(ret));
}

// === Cleanup (at shutdown) ===
releasebuffer_handle(src_handle);
releasebuffer_handle(dst_handle);
return ret == IM_STATUS_SUCCESS ? 0 : -1;
```

---

## Troubleshooting RGA Failures

### RGA DMA-BUF lifecycle cascade failure

**The single most common cause of sustained RGA crashes in production inference pipelines.**

#### Quick diagnostic

Check `/proc/interrupts` on the device:

```bash
grep rga2 /proc/interrupts | awk '{
    total=0; for(i=3;i<=NF-2;i++) total+=$i;
    for(i=3;i<=NF-2;i++) printf "  %s core %s: %s (%.1f%%)\n", $(NF), i-3, $i, ($i/total)*100
}'
```

> If core 4 is >90% and core 8 is <10%, the **imbalance amplified the cascade failure** — fix the DMA-BUF lifecycle first, then the load balancing.

#### Symptom → Root Cause Map

| dmesg pattern | What it really means |
| --- | --- |
| `Cannot get dst channel buffer` | DMA-BUF fd was `close()`d before RGA finished with it. **Root trigger.** |
| `failed to map buffer` | Kernel IOMMU cannot resolve the fd to physical pages. |
| `abort! finished 0 failed 0 ...` | RGA pre-commit validation cancelled the job before hardware touched it. |
| `job hardware has timeout` → `INTR[0x840700]` | IOMMU page fault caused hardware hang on the target core. |
| `soft reset complete` | Kernel recovered the hung core. |
| `no core match` | Scheduler has no available core — the one that handles 99% of jobs is in reset. |
| `mpp_rkvdec2 timeout/resetting` | Decoder pipeline back-pressured because RGA is not consuming frames. |

#### Code audit checklist

- [ ] Are all `wrapbuffer_fd()` calls paired with a one-time `importbuffer_fd()` per buffer pool lifecycle?
- [ ] Or does the code call `wrapbuffer_fd()` **every frame** without retaining the handle? (🚨 Red flag)
- [ ] Is `importbuffer_fd()` called with the full stride-derived size, not just `width * height * bpp`?
- [ ] Is `imcheck()` called before every `improcess`/`imresize`?
- [ ] Does the destination DMA-BUF double as an NPU input buffer? If so, is there a sync fence?

#### Fix summary

```
P0: importbuffer_fd() once per pool → wrapbuffer_handle() per frame → releasebuffer_handle() at shutdown
P1: im_set_core_mask() to balance across all RGA2 cores
P2: Validate dst buffer size and call imcheck() before every operation
```

See `known-crash-patterns.md` section "RGA DMA-BUF Lifecycle Cascade Failure" for the full diagnosis and code examples.
