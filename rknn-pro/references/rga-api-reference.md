# RGA API Reference

Rockchip RGA (Raster Graphics Acceleration) is a 2D hardware accelerator for fixed-function
image processing. Use the **im2d API** (modern, recommended).

## RGA Capabilities and Limitations

| Supported | Not supported |
|---|---|
| **Resize** (bilinear, bicubic, nearest) | **Affine transform** (warp affine, perspective) |
| **Crop** (rectangular region) | **Convolution / filter** (blur, sharpen, edge detect) |
| **Color space conversion** (YUV↔RGB, etc.) | **Morphological ops** (dilate, erode, open, close) |
| **Rotate** (90°, 180°, 270°) | **Histogram / statistics** |
| **Flip** (horizontal, vertical) | **Drawing** (lines, circles, text) |
| **Translate / shift** | **Custom pixel operations** (lookup table, threshold) |
| **Format conversion** (NV12↔RGB↔RGBA) | **Multi-pass / chained operations** (must interleave with CPU sync) |
| **Alpha blending** (limited, via channel) | **Non-2D transforms** (perspective, homography) |

> ⚠️ RGA is a **fixed-function 2D hardware block**, not a GPU shader. It excels at common
> pre-processing operations used in camera and display pipelines. If the operation is not in the
> supported list, it must be handled on CPU (NEON-optimized) or NPU.
>
> For affine or perspective transforms (e.g., document scanning, AR), use:
> - **CPU**: OpenCV `warpAffine` / `warpPerspective` with NEON optimization
> - **NPU**: Custom RKNN model for spatial transform

### When to use RGA vs CPU vs NPU

| Criterion | RGA | CPU (NEON) | NPU (RKNN) |
|---|---|---|---|
| Resize + CSC | ✅ Fastest, offloaded | ✅ Flexible | ❌ Overkill |
| Crop | ✅ Zero-copy (DMA-BUF) | ✅ | ❌ |
| Rotate / Flip | ✅ Hardware | ✅ | ✅ (model-dependent) |
| Affine / Perspective | ❌ **Not supported** | ✅ OpenCV | ✅ Custom model |
| Multi-step pipeline | ❌ One op at a time | ✅ Full control | ✅ Batch |
| Small images (<64×64) | ⚠️ Overhead may dominate | ✅ Prefer CPU | ❌ |

## Buffer Import

### `importbuffer_fd`

```c
rga_buffer_handle_t importbuffer_fd(int fd, int size);
```

Import a DMA-BUF file descriptor for RGA processing. This is the **preferred zero-copy path**.

- `fd`: DMA-BUF file descriptor (from V4L2, MPP, DRM, dma_heap, etc.)
- `size`: buffer size in bytes
- Returns: handle (opaque), or NULL on failure

**Performance:** `importbuffer_fd()` is intentionally expensive — do NOT call every frame.
Import once for a pool of buffers and reuse handles.

### `importbuffer_virtualaddr`

```c
rga_buffer_handle_t importbuffer_virtualaddr(void *virt_addr, int size);
```

Import CPU virtual address. Slower (page-table walk overhead). Use only when DMA-BUF is unavailable.

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
|---|---|
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

When the destination fd is an RKNN input allocation, pass the queried model input
`w_stride` / `h_stride` explicitly. The short/default-stride wrapper can describe a tightly packed
buffer even when RKNN allocated or expects padded rows.

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
|---|---|
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
blend is used, and `IM_SYNC` in `usage` for synchronous execution. Run `imcheck` with the same
rects first.

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
|---|---|
| `IM_HAL_TRANSFORM_FLIP_H` | Horizontal flip |
| `IM_HAL_TRANSFORM_FLIP_V` | Vertical flip |
| `IM_HAL_TRANSFORM_FLIP_H_V` | Both |

### `imrotate`

```c
IM_STATUS imrotate(const rga_buffer_t src, rga_buffer_t dst, int rotation, int sync);
```

| `rotation` | Description |
|---|---|
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
|---|---|---|
| `RK_FORMAT_RGB_565` | RGB 565 | 2 |
| `RK_FORMAT_RGB_888` | RGB 888 | 3 |
| `RK_FORMAT_RGBA_8888` | RGBA 8888 | 4 |
| `RK_FORMAT_BGRA_8888` | BGRA 8888 | 4 |
| `RK_FORMAT_YCbCr_420_SP` | NV12 (Y+UV) | 1.5 |
| `RK_FORMAT_YCbCr_422_SP` | NV16 | 2 |

---

## Alignment Rules (Common Pitfalls)

| Format | Width stride alignment | Height stride alignment |
|---|---|---|
| RGB565 | 2 | 1 |
| RGB888 | 4 | 1 |
| RGBA/BGRA 8888 | 4 | 1 |
| NV12 / NV21 | 4 | 2 |
| YUV420 | 4 | 2 |

> ⚠️ **NV12 width must be even and ≥ 2.** `imcheck` will reject NV12 with odd width like 1281.

For stride calculation:
```c
// NV12 stride alignment
int w_stride = ALIGN_UP(width, 4);   // 4-byte alignment
int h_stride = ALIGN_UP(height, 2);  // 2-byte alignment

// NV12 buffer size
int size = w_stride * h_stride * 3 / 2;
```

**Critical: `importbuffer_fd()` is expensive — call once per buffer, reuse handles.**

### RKNN destination contract

For RGA preprocessing directly into NPU input memory, derive the destination layout from the RKNN
input attribute and carry it through the RGA helper API:

```cpp
const rknn_tensor_attr& input_attr = model->GetInputAttr(0);
const int dst_w_stride = input_attr.w_stride != 0
    ? static_cast<int>(input_attr.w_stride)
    : model_width;
const int dst_h_stride = input_attr.h_stride != 0
    ? static_cast<int>(input_attr.h_stride)
    : model_height;

rga_buffer_t dst = wrapbuffer_fd(dst_fd,
                                 model_width,
                                 model_height,
                                 RK_FORMAT_RGB_888,
                                 dst_w_stride,
                                 dst_h_stride);
```

Use `wrapbuffer_handle(..., dst_w_stride, dst_h_stride)` when the installed librga does not expose
the stride-aware fd overload. Size the backing DMA-BUF from these same strides and the pixel format,
not merely from `model_width * model_height`. Run `imcheck` before the operation.

---

## Typical Usage Pattern

```c
// === Setup (once) ===

// Source: DMA-BUF fd from V4L2/MPP
rga_buffer_handle_t src_handle = importbuffer_fd(src_fd, src_size);
rga_buffer_t src = wrapbuffer_handle(src_handle, src_w, src_h,
                                     RK_FORMAT_YCbCr_420_SP, src_w_stride, src_h_stride);

// Destination: DMA-BUF fd from dma_heap or pre-allocated
rga_buffer_handle_t dst_handle = importbuffer_fd(dst_fd, dst_size);
rga_buffer_t dst = wrapbuffer_handle(dst_handle, dst_w, dst_h,
                                     RK_FORMAT_RGB_888, dst_w_stride, dst_h_stride);

// === Per frame ===

// Validate (im_rect by value; success is IM_STATUS_NOERROR)
im_rect src_rect = {0, 0, src_w, src_h};
im_rect dst_rect = {0, 0, dst_w, dst_h};
IM_STATUS ret = imcheck(src, dst, src_rect, dst_rect);
if (ret != IM_STATUS_NOERROR) {
    printf("RGA imcheck failed: %s\n", imStrError(ret));
}

// Convert NV12 -> RGB888 + resize to 640x640
imresize(src, dst, 0, 0, INTER_LINEAR, 1);  // sync=1

// === Cleanup (at shutdown) ===
releasebuffer_handle(src_handle);
releasebuffer_handle(dst_handle);
```
