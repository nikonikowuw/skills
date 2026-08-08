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

### Resolution and Scaling Limits

| Core family | Input resolution | Output resolution | Scaling range | MMU address width |
| --- | --- | --- | --- | --- |
| RGA2 / RGA2e | 2×2 – 8192×8192 | 2×2 – 4096×4096 | 1/16× – 16× | 32-bit (≤ 4 GB) |
| RGA3 | 68×2 – 8176×8176 | 68×2 – 8128×8128 | 1/8× – 8× | 40-bit (native) |

These limits are hard constraints enforced by the hardware. Common violations:

- **RGA3 minimum dimension** — a 32×32 crop for a classifier will fail on RGA3 (minimum is 68);
  route to RGA2 explicitly or resize in two steps.
- **RGA3 scaling ratio** — a 1920×1080→128×72 resize exceeds 1/8×; split into two passes
  (e.g. 1920→480 then 480→128) or route to RGA2 which allows 1/16×.
- **4 GB physical-address boundary** — RGA1/RGA2 MMU resolves only 32-bit physical addresses.
  Buffers allocated above 4 GB cause `RGA_MMU unsupported Memory larger than 4G!` and fall back
  to `swiotlb` bounce copy or fail outright. Use `dma_heap` with `DMA32` flag or restrict DDR
  capacity in U-Boot when targeting RGA2-only cores.

When the driver can schedule a request onto multiple core generations, the strictest applicable
limit governs.

### Hardware Throughput

| Core family | Pixels per clock cycle | Typical clock range |
| --- | ---: | --- |
| RGA1 | 1 | SoC-dependent |
| RGA2 | 2 | SoC-dependent |
| RGA3 | 4 | SoC-dependent |

Estimated copy latency: `width × height / (pixels_per_cycle × frequency)`. This is a theoretical
lower bound; actual latency includes setup, memory, and synchronization overhead.

### Multi-Core Scheduling and Jitter

RK3588 contains two RGA3 cores and one RGA2 core. Because the scaling algorithms differ between
RGA2 and RGA3, unpinned workloads that shift between core types can produce **visible sampling
jitter** in scaled outputs. If output determinism matters:

- Bind to a single core type using `imconfig(IM_CONFIG_SCHEDULER_CORE, IM_SCHEDULER_RGA3_CORE0)`
  for the thread, or use `im_opt_t.core` with the extended `improcess` overload.
- The official guide warns that core/priority configuration can cause a system crash or deadlock;
  use it for development/debugging. In production, prefer automatic scheduling unless the platform
  vendor supplies a validated product-specific contract.
- For **load balancing** without jitter (e.g. two RGA2 cores on RK3576), use
  `IM_SCHEDULER_RGA2_CORE0 | IM_SCHEDULER_RGA2_CORE1` to spread work across same-generation cores.

### librga / Driver Version Compatibility

- `librga` ≥ 1.4.0 requires kernel driver ≥ v1.2.0. Mismatches cause compatibility-mode fallback
  or outright parameter failures.
- A version mismatch between librga and driver can produce **pink or green color shifts** during
  RGB↔YUV conversion because the default CSC color space configuration differs between versions.
- Check versions: `cat /sys/kernel/debug/rkrga/driver_version` (or `/proc/rkrga/driver_version`),
  and `querystring(RGA_VERSION)` in code or `strings librga.so | grep version`.

### Memory Type Performance

| Memory type | Relative cost | Notes |
| --- | --- | --- |
| Physical address | ~1.1–1.2× theoretical | Fastest; limited to drivers that expose physical addresses |
| DMA FD (`dma_buf`) | ~1.3–1.5× theoretical | **Recommended default**. Allocate uncached to avoid CPU cache sync |
| Virtual address | ~1.8–2.1× theoretical | CPU builds page tables every frame and forces cache flushes |

Prefer `dma_fd` for all production pipelines. Virtual-address submission adds CPU overhead and has
caused kernel crashes on some platforms (IOMMU page faults during `rga_mm_sync_dma_sg_for_device`
when the mapping is released or invalid).

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

**Using `imStrError`** — when `imcheck` fails, `imStrError(ret)` returns a human-readable string
naming the exact rule violation (e.g. `"Error yuv not align to 2"`, `"Error srcRect"`). Log it for
faster diagnosis rather than guessing at stride tables.

---

## Synchronization Modes

| Mode | Behavior | When to use |
| --- | --- | --- |
| `IM_SYNC` / `sync=1` | Block until hardware finishes | Simple sequential pipelines |
| `IM_ASYNC` / `sync=0` | Return immediately; call `imsync()` to wait | When CPU work can overlap |
| Job + fence | `imendJob` accepts `acquire_fence_fd` and returns `release_fence_fd` | Multi-stage DMA-BUF pipelines with cross-device synchronization |

### Job/Task Batch API

For multi-operation pipelines or async fence-based synchronization:

```c
im_job_handle_t job = imbeginJob(0);  // or IM_JOB_FLAGS_EXEC_SEQUENTIAL for ordering

// Queue multiple operations into the job
imresizeTask(job, src, dst, 0, 0, INTER_LINEAR);
imcvtcolorTask(job, src2, dst2, sfmt, dfmt, mode);

// Submit with optional fence synchronization
int release_fence = -1;
IM_STATUS ret = imendJob(job, IM_ASYNC, acquire_fence_fd, &release_fence);
// release_fence signals when all tasks in the job complete
```

- `IM_JOB_FLAGS_EXEC_SEQUENTIAL` ensures tasks within the job execute in order.
- `imcancelJob(job)` aborts a created but unsubmitted job.
- Each `*Task` variant (e.g. `imresizeTask`, `imcropTask`) queues into a job handle instead of
  executing immediately.

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

### Raster Format Alignment

The hardware fetches line data in 32-bit (4-byte) word units. Pixel alignment requirements follow
from byte-stride constraints per core generation:

| Core family | Byte stride align | RGBA8888 w_stride | RGB565 w_stride | RGB888 w_stride | NV12/NV21 w_stride | Max stride |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| RGA2 family | 4 bytes | no extra pixel multiple | 2 px | 4 px | 4 px | 32768 |
| RGA3 | 16 bytes | 4 px | 8 px | 16 px | 16 px | 32768 |

For raster NV12/NV21, x/y offsets, logical width/height, and height stride must also be even. An odd
logical width such as 1281 remains invalid even if the backing stride is rounded up. RGA3 ten-bit
YUV requires a width stride multiple of 64 and x/y offsets multiple of 4.

### Non-Linear / Compressed Format Alignment (FBC / AFBC / Tile)

Non-linear read/write modes require stricter block-aligned layout:

| Mode | Width stride alignment | Height stride alignment | Available on |
| --- | ---: | ---: | --- |
| AFBC 16×16 | 16 px | 16 px | RGA3 |
| AFBC 32×8 | 32 px | 8 px | RGA2-Pro |
| RKFBC 64×4 | 64 px | 4 px | RGA2-Pro |
| TILE 8×8 | 8 px | 8 px | Selected cores |
| TILE 4×4 | 4 px | 4 px | Selected cores |

Requesting a FBC/AFBC/tile mode on a buffer that does not meet the block alignment causes hardware
timeout or IRQ error, not a clean parameter rejection. The error in dmesg is typically
`rga: Rga err irq!` or `job hardware has timeout` with no clear indication that FBC alignment is
the cause. Always verify the source/destination allocation meets the selected read mode's alignment
before submission.

### Combined Constraint Rule

If the driver can schedule a request onto several core generations, satisfy the strictest applicable
rule. Use checked arithmetic from [memory-alignment.md](memory-alignment.md) for byte sizing and
run `imcheck` on the complete request.

### Per-Core Format Support

| Core variant | SoCs | Key format additions |
| --- | --- | --- |
| RGA2 / RGA2e | RK3568, RK3566 | RGB, YUV420/422 SP/Planar, palette BPP1/2/4/8 |
| RGA2-Lite1 | Selected SoCs | Adds 10-bit YUV420/422 SP input |
| RGA2-Enhance | Selected SoCs | Adds YUYV/YVYU/UYVY/VYUY 422, YCbCr_400, Y4/Y8 |
| RGA2-Pro | RK3576, RV1126B | Adds YCbCr 444 SP, A8 source blend, AFBC/FBC compressed formats, RGBA 1010102, Y210 |
| RGA3 | RK3588 | RGB, 8/10-bit YUV 420/422 SP, YUYV, AFBC 16×16. **No YUV alpha blending** |

**Blending restriction**: Image blending does not support YUV format images on any RGA core.
Convert to RGB before blending.

### Verified Fix Patterns (RK3576 production debugging, 2026-08)

Two alignment fixes confirmed end-to-end on an RK3576 (RGA2+RGA3) fall-detection pipeline that was
failing at `imcheck` with `ALGO_RGA_PROCESS_FAILED`:

1. **NV12 odd logical height → `imcheck` "Error yuv not align to 2"**. A 600×423 NV12 source with a
   correctly aligned `wstride=608`/`hstride=424` still failed because the *logical* rect height 423
   was odd. Fix: align the NV12 logical `src_w`/`src_h` up to even at the `ResizeAndConvert` entry
   (`AlignUp(src_w, 2)`, `AlignUp(src_h, 2)`) before computing rects and letterbox geometry. Reading
   the zeroed padding row is harmless; dropping the odd row is not.

2. **RGB888 src only 4-pixel aligned → fails on RGA3's 16-pixel rule**. The source repack helper
   rounded RGB888/BGR24 wstride to 4 (satisfying RGA2 but not RGA3). Fix: repack when
   `src_stride_w & 15 != 0`, `AlignUp(src_w, 16)`, and run letterbox geometry with `alignment=16`
   (so `new_w`/`new_h`/`pad_x`/`pad_y` are also 16-multiples). 16 is a superset of RGA2's 4, so the
   same shared library stays correct on RK3568 (RGA2) and RK3576 (RGA3).

Always run `imcheck` with the exact rects and operation flags after these alignments; the error
string from `imStrError(imcheck(...))` (e.g. `"Error yuv not align to 2"`) names the offending
source/dst and the exact rule, which beats guessing at stride tables.

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

### Complete Kernel Error → Root Cause Map

| dmesg / log pattern | Root cause | Fix |
| --- | --- | --- |
| `Cannot get dst channel buffer` | DMA-BUF fd closed before RGA finished; stale cached handle from `wrapbuffer_fd` | Use `importbuffer_fd` once + `wrapbuffer_handle` per frame (see cascade section below) |
| `failed to map buffer` | IOMMU cannot resolve fd to physical pages | Verify fd validity, lifetime, and that the exporter has not reclaimed the buffer |
| `dma_buf_get fail fd[N]` | Kernel cannot obtain dma-buf from the fd | Validate fd creation, ownership, lifetime before RGA submission |
| `RGA2 failed to get vma` / `failed to get pte` | Virtual-address buffer smaller than calculated image size, or DRM kmap released | Ensure mapped bytes ≥ format × strides; for DRM use `ROCKCHIP_BO_ALLOC_KMAP` flag |
| `set mmu info error` | Page-table mapping failed for virtual address or fd | Check buffer size matches format/strides; verify memory allocator compatibility |
| `RGA_MMU unsupported Memory larger than 4G!` | Buffer above 4 GB physical; RGA1/RGA2 MMU is 32-bit | Allocate with `DMA32` heap flag or restrict DDR in U-Boot |
| `rga_policy: invalid function policy` | Requested params/address incompatible with available cores | Check resolution limits, format support per core; avoid forcing a core that can't handle the operation |
| `rga: job assign failed` | No available core matches the request | Usually follows a `soft reset` or `invalid policy`; fix the upstream cause |
| `abort! finished 0 failed 0` | Pre-commit validation cancelled the job | Symptom of upstream buffer/param failure; not a standalone cause |
| `job hardware has timeout` + `INTR[0x840700]` | IOMMU page fault caused hardware hang | Fix buffer lifecycle (see cascade); or verify FBC mode matches buffer format |
| `rga: Rga err irq! INT[701],STATS[1]` | Hardware execution exception: out-of-bounds memory or illegal register | Verify buffer size, stride, and format; check FBC alignment if compressed mode |
| `Rga sync pid X wait 1 task done timeout` | Hardware task exceeded 200 ms | DDR bus congestion, mismatched FBC flags, lowered clock, or CPU preemption blocking IRQ |
| `hardware has finished, but the software has timeout!` | CPU core handling RGA interrupt was preempted by RT tasks before softirq | Check RT scheduling; adjust IRQ affinity or RGA timeout threshold |
| `soft reset complete` | Kernel recovered a hung core | Effect, not a root cause; fix the job that caused the hang |
| `no core match` | Scheduler has no available core | All eligible cores are in reset or the request parameters exclude all cores |
| `mpp_rkvdec2 timeout/resetting` | Decoder pipeline back-pressured because RGA is not consuming frames | Fix RGA pipeline; decoder stalls are an effect of the RGA failure |
| `RgaBlit fail: Not a typewriter` | Parameter invalidity: stride < width+offset, scaling beyond limits, or alignment error | Verify stride ≥ offset + dimension; check scaling ratio within core limits |
| `RgaBlit fail: Bad file descriptor` | Invalid fd passed to the ioctl | Verify fd is valid and not already closed |
| `RgaBlit fail: Bad address` | Out-of-bounds src/src1/dst memory address | Verify buffer allocation size and mapping |
| `RgaBlit fail: Invalid argument` | Operations/params exceed matching core capabilities | Check format/operation support on the selected core |
| `err ws[X,Y,Z]` / `Error srcRect` | `x_offset + width > width_stride` violation | Ensure rect fits within the declared stride |
| `Error yuv not align to 2` | YUV logical width/height/offset is odd | Align NV12/NV21 logical dimensions up to even |
| `Try to use uninit rgaCtx=(nil)` | librga singleton uninitialized; legacy `RgaInit/RgaDeInit`, or `/dev/rga` permission denied | Check device node permissions; avoid legacy init/deinit in im2d API code |
| `Only get buffer X byte...current required Y byte` | Import size doesn't match the format/strides for the operation | Re-import with correct size: `w_stride × h_stride × bpp` (accounting for multi-plane) |
| `Decrement the reference of handle...when user exits` | Leaked `buffer_handle` — import not matched with release | Pair every `importbuffer_*` with `releasebuffer_handle` |

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
