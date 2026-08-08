# Rockchip Memory Alignment Reference

Rockchip hardware (RGA, MPP, RKNN NPU) enforces strict alignment requirements on buffer addresses,
widths, heights, strides, and total sizes. Misaligned buffers cause silent data corruption or
runtime errors.

## Contents

- [Quick Reference Table](#quick-reference-table)
- [Alignment Calculation Functions](#alignment-calculation-functions)
- [RKNN Memory Alignment Detail](#rknn-memory-alignment-detail)
- [Why Alignment Matters](#why-alignment-matters)
- [RGA Format-Specific Alignment](#rga-format-specific-alignment)
- [MPP Buffer Sizing](#mpp-buffer-sizing)
- [RKNN Tensor Stride](#rknn-tensor-stride)
- [Common Mistakes](#common-mistakes)
- [Verification Snippet](#verification-snippet)

## Quick Reference Table

| Operation | Width stride rule | Height/geometry rule | Buffer address | Size source |
|---|---|---|---|---|
| **RGA2 family** RGB565 / RGB888 / RGBA8888 | 2 / 4 / no extra pixel alignment | Format-specific; RGB raster height has no extra rule in the cited table | Allocator/driver contract | Checked bytes from actual strides and format |
| **RGA2 family** NV12/NV21 | Width stride multiple of 4 | x/y/width/height/height stride all even | Allocator/driver contract | Checked bytes from actual plane layout |
| **RGA3** RGB565 / RGB888 / RGBA8888 | 8 / 16 / 4 pixels | Format- and read-mode-specific | Allocator/driver contract | Checked bytes from actual strides and format |
| **RGA3** NV12/NV21 | Width stride multiple of 16 | x/y/width/height/height stride all even | Allocator/driver contract | Checked bytes from actual plane layout |
| **RGA FBC/AFBC** | AFBC16×16: 16 px; AFBC32×8: 32 px; RFBC64×4: 64 px | AFBC16×16: 16 px; AFBC32×8: 8 px; RFBC64×4: 4 px | Allocator/driver contract | Block-aligned layout from compressed format spec |
| **MPP** decode | Returned frame layout | Returned frame layout | Selected MPP allocator | `mpp_frame_get_buf_size`; confirm with `mpp_buffer_get_size` |
| **RKNN** `rknn_inputs_set` | Host tensor contract | Host tensor contract | Host type/allocator contract | Checked value representable by the API's `uint32_t size` |
| **RKNN** `rknn_create_mem` | Queried model layout | Actual physical height stride | Runtime-managed | Maximum applicable tensor/layout minimum, checked before narrowing |
| **RKNN** `rknn_create_mem_from_fd` | Backing layout must satisfy queried read-only `w_stride` | Set write-only `h_stride` to actual backing layout | Exporter/importer contract | Exported allocation size, checked against all consumer minima |

> **ws** = width stride, **hs** = height stride. The RGA rows cover common raster formats only.
> Ten-bit, packed, FBC/AFBC, and tile modes have additional rules. When multiple RGA generations
> can receive a request, use the strictest applicable rule unless an exact-core diagnostic is active.

## Alignment Calculation Functions

### C / C++ (Industrial Standard)

In production environments, directly using the classic bitwise `ALIGN_UP` macro is a severe integer overflow vulnerability if dimensions come from external or untrusted video streams. **Always use overflow-checked alignment helpers:**

```cpp
#include <stdexcept>
#include <limits>
#include <cstddef>
#include <cstdint>

// Standard industrial-grade alignment with overflow protection
static inline size_t AlignUpChecked(size_t value, size_t alignment) {
    if (alignment == 0 || value > std::numeric_limits<size_t>::max() - (alignment - 1)) {
        throw std::overflow_error("Rockchip allocation alignment overflow");
    }
    // Works for any alignment, not just powers of 2
    return ((value + alignment - 1) / alignment) * alignment;
}

static inline size_t CheckedMul(size_t lhs, size_t rhs) {
    if (lhs != 0 && rhs > std::numeric_limits<size_t>::max() / lhs) {
        throw std::overflow_error("Rockchip buffer size overflow");
    }
    return lhs * rhs;
}

// Pass 4 only for an RGA2-family NV12 request and 16 for RGA3.
// Padding the stride does not make odd NV12 logical geometry valid.
size_t CalcRasterNv12Size(uint32_t width,
                          uint32_t height,
                          size_t width_stride_alignment) {
    if ((width & 1U) != 0 || (height & 1U) != 0) {
        throw std::invalid_argument("NV12 logical width and height must be even");
    }
    const size_t ws = AlignUpChecked(width, width_stride_alignment);
    const size_t pixels = CheckedMul(ws, height);
    return CheckedMul(pixels, 3) / 2;
}
```

> **Legacy Anti-Pattern:** The classic macro `#define ALIGN_UP(x, align) (((x) + (align) - 1) & ~((align) - 1))` only works for power-of-2 alignments and silently wraps around on integer overflow. Do not use it in new code.

### Python

```python
def align_up(x, align):
    return (x + align - 1) // align * align

def rga_nv12_size(width, height, width_stride_alignment):
    if width % 2 or height % 2:
        raise ValueError("NV12 logical width and height must be even")
    ws = align_up(width, width_stride_alignment)
    return ws * height * 3 // 2
```

Do not synthesize a generic MPP decode allocation from logical dimensions. Use the
information-change frame's reported buffer size and validate the actual `MppBuffer` capacity.

## RKNN Memory Alignment Detail

RKNN memory alignment depends on the **data path**:

### Build-time compatibility: prefer `size_with_stride`

RKNN headers are not uniform across BSP/runtime releases. API 2.x headers commonly expose
`rknn_tensor_attr.size_with_stride`, while older headers may expose only `size`. Detect the member
in every independently built algorithm target instead of inferring it from a version string.

```cmake
include(CheckStructHasMember)

# Point this at the same RKNN include directory used by the algorithm target.
set(_RKNN_SAVED_REQUIRED_INCLUDES "${CMAKE_REQUIRED_INCLUDES}")
set(CMAKE_REQUIRED_INCLUDES "${RKNN_INCLUDE_DIRS}")

check_struct_has_member(
    "struct _rknn_tensor_attr"
    size_with_stride
    "rknn_api.h"
    RKNN_HAVE_SIZE_WITH_STRIDE)
if(NOT RKNN_HAVE_SIZE_WITH_STRIDE)
    check_struct_has_member(
        "struct _rknn_tensor_attr" nbytes "rknn_api.h" RKNN_HAVE_NBYTES)
endif()
if(NOT RKNN_HAVE_SIZE_WITH_STRIDE AND NOT RKNN_HAVE_NBYTES)
    check_struct_has_member(
        "struct _rknn_tensor_attr" n_size "rknn_api.h" RKNN_HAVE_N_SIZE)
endif()
# Detect size independently: newer headers commonly expose it beside size_with_stride,
# while some legacy variants may use only nbytes or n_size.
check_struct_has_member(
    "struct _rknn_tensor_attr" size "rknn_api.h" RKNN_HAVE_SIZE)

set(CMAKE_REQUIRED_INCLUDES "${_RKNN_SAVED_REQUIRED_INCLUDES}")
unset(_RKNN_SAVED_REQUIRED_INCLUDES)

if(RKNN_HAVE_SIZE_WITH_STRIDE)
    set(RKNN_TENSOR_SIZE_FIELD_NAME size_with_stride)
    message(STATUS "RKNN tensor size field: size_with_stride (API 2.x)")
elseif(RKNN_HAVE_NBYTES)
    set(RKNN_TENSOR_SIZE_FIELD_NAME nbytes)
    message(STATUS "RKNN tensor size field: nbytes")
elseif(RKNN_HAVE_N_SIZE)
    set(RKNN_TENSOR_SIZE_FIELD_NAME n_size)
    message(STATUS "RKNN tensor size field: n_size")
elseif(RKNN_HAVE_SIZE)
    set(RKNN_TENSOR_SIZE_FIELD_NAME size)
    message(STATUS "RKNN tensor size field: size (legacy API)")
else()
    message(FATAL_ERROR
        "rknn_tensor_attr has none of size_with_stride, nbytes, n_size, or size")
endif()

target_compile_definitions(${ALGORITHM_TARGET} PRIVATE
    RKNN_TENSOR_SIZE_FIELD=${RKNN_TENSOR_SIZE_FIELD_NAME})
if(RKNN_HAVE_SIZE_WITH_STRIDE)
    target_compile_definitions(${ALGORITHM_TARGET} PRIVATE
        RKNN_HAVE_SIZE_WITH_STRIDE=1)
endif()
if(RKNN_HAVE_SIZE)
    target_compile_definitions(${ALGORITHM_TARGET} PRIVATE
        RKNN_HAVE_SIZE=1)
endif()
```

Adapt `RKNN_INCLUDE_DIRS` and `${ALGORITHM_TARGET}` to local target names. Apply the same feature
test to separately packaged algorithms such as `face`, `yolov5`, and `yolov8`; do not assume one
package's CMake result propagates to another target or directory.

`check_struct_has_member` results are cached. When switching sysroots, BSPs, or RKNN header roots in
one build directory, clear the affected CMake cache or use a fresh build directory before trusting
the result.

Use the exported `RKNN_TENSOR_SIZE_FIELD` macro where one selected field is sufficient:

```cpp
const uint32_t runtime_tensor_size = attr.RKNN_TENSOR_SIZE_FIELD;
```

For defensive allocation, keep the feature macro as well so C++ can compare both fields when the
new member exists.

### Path 1: `rknn_inputs_set` (host memory → NPU, with internal copy)

```c
rknn_input input = {0};
input.index = 0;
input.buf = host_buffer;           // host-side buffer
input.size = CheckedSizeToUint32(image_size); // reject values above UINT32_MAX
input.pass_through = 0;            // runtime handles quantize
input.type = RKNN_TENSOR_UINT8;
input.fmt = RKNN_TENSOR_NHWC;
if (rknn_inputs_set(ctx, 1, &input) != RKNN_SUCC) {
    return -1;
}
```

- Meet the host type's alignment and the selected Runtime API contract. This path may perform an
  internal copy or conversion; do not infer a direct DMA read or a universal address-alignment rule.
- For `UINT8`, byte alignment satisfies the C object type, but the surrounding image rows and source
  allocator can impose stronger requirements.
- For `FP32`, use at least the platform/type alignment and measure any Runtime conversion cost.
- For NEON-optimized CPU preprocessing feeding this path: **16-byte alignment** improves performance.

`CheckedSizeToUint32` denotes a project helper that rejects values above `UINT32_MAX`; do not rely on
implicit `size_t` narrowing at Runtime API boundaries.

### Path 2: `rknn_create_mem` (NPU-managed memory, zero-copy)

```c
rknn_tensor_mem *mem = rknn_create_mem(ctx, size);
```

- Runtime returns NPU-accessible tensor memory. The backing dma-heap/ION choice, physical layout,
  CPU mapping, and page alignment are BSP/runtime properties; query the returned handle and follow
  the deployed API contract instead of assuming physical contiguity or a fixed allocator.
- Use with `rknn_set_io_mem` to bind to a tensor.

#### Defensive input allocation

For every tensor allocation, compare the selected compatibility field with `size` and, on
stride-aware headers, `size_with_stride`. For an input that RGA writes directly, also cover the
bytes RGA will write using the exact destination format and NPU strides. Round the result up only
after all applicable minimum sizes have been compared.

```cpp
#include <algorithm>
#include <climits>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <stdexcept>
#include <unistd.h>

static size_t CheckedMul(size_t lhs, size_t rhs) {
    if (lhs != 0 && rhs > std::numeric_limits<size_t>::max() / lhs) {
        throw std::overflow_error("RKNN/RGA buffer size overflow");
    }
    return lhs * rhs;
}

static size_t AlignUpChecked(size_t value, size_t alignment) {
    if (alignment == 0 || value > std::numeric_limits<size_t>::max() - (alignment - 1)) {
        throw std::overflow_error("RKNN allocation alignment overflow");
    }
    return ((value + alignment - 1) / alignment) * alignment;
}

static size_t RgaTensorBytes(uint32_t w_stride,
                             uint32_t h_stride,
                             int format) {
    const size_t pixels = CheckedMul(w_stride, h_stride);
    switch (format) {
    case RK_FORMAT_RGB_888:
        return CheckedMul(pixels, 3);
    case RK_FORMAT_RGBA_8888:
    case RK_FORMAT_BGRA_8888:
        return CheckedMul(pixels, 4);
    case RK_FORMAT_RGB_565:
        return CheckedMul(pixels, 2);
    case RK_FORMAT_YCbCr_420_SP:
    case RK_FORMAT_YCrCb_420_SP:
        if ((w_stride & 1U) != 0 || (h_stride & 1U) != 0) {
            throw std::invalid_argument("YUV420 stride must be even");
        }
        return CheckedMul(pixels, 3) / 2;
    default:
        throw std::invalid_argument("unsupported RGA destination format");
    }
}

const rknn_tensor_attr& attr = input_attrs_[i];
const uint32_t dst_w_stride = attr.w_stride != 0 ? attr.w_stride : model_width;
// Current official headers define w_stride as query output and h_stride as bind input.
const uint32_t dst_h_stride = rga_destination_h_stride;

size_t alloc_size = attr.RKNN_TENSOR_SIZE_FIELD;
#if defined(RKNN_HAVE_SIZE)
alloc_size = std::max(alloc_size, static_cast<size_t>(attr.size));
#endif
#if defined(RKNN_HAVE_SIZE_WITH_STRIDE)
alloc_size = std::max(alloc_size, static_cast<size_t>(attr.size_with_stride));
#endif
alloc_size = std::max(
    alloc_size,
    RgaTensorBytes(dst_w_stride, dst_h_stride, rga_dst_format));

const long page_size_value = sysconf(_SC_PAGESIZE);
if (page_size_value <= 0) {
    throw std::runtime_error("failed to query system page size");
}
alloc_size = AlignUpChecked(alloc_size, static_cast<size_t>(page_size_value));

if (alloc_size > std::numeric_limits<uint32_t>::max()) {
    throw std::overflow_error("rknn_create_mem size exceeds uint32_t API limit");
}
input_mems_[i] = rknn_create_mem(ctx_, static_cast<uint32_t>(alloc_size));
if (input_mems_[i] == nullptr) {
    throw std::runtime_error("rknn_create_mem failed");
}
```

If the project already has checked arithmetic, format-size, or page-alignment helpers, use those
instead of adding duplicates. For multi-plane formats or BSP-specific layouts, use the allocator's
authoritative size formula; the switch above is a minimum template, not a universal format table.

### Path 3: `rknn_create_mem_from_fd` (DMA-BUF import, zero-copy)

```c
// virt_addr: CPU mapping of the DMA-BUF (NULL acceptance is release-dependent — check the header).
// Last parameter is the byte OFFSET inside the fd (usually 0), not an mmap protection flag.
rknn_tensor_mem *mem = rknn_create_mem_from_fd(
    ctx, dma_fd, dma_virt_addr, CheckedSizeToUint32(size), 0);
if (mem == NULL) {
    return -1;
}
```

- Imports an existing DMA-BUF from RGA, MPP, or dma_heap.
- Address alignment is inherited from the source (typically 4KB page-aligned).
- In the current official header, `w_stride` is read-only: query it and make the producer/backing
  buffer satisfy it. Do not overwrite it to relabel an incompatible DMA-BUF.
- In that same header, `h_stride` is write-only: set it to the actual physical height stride before
  `rknn_set_io_mem`; do not treat a value observed after `rknn_query` as authoritative.
- Older/vendor headers may differ. Compile and reason against the exact deployed header/runtime pair.

### Path 4: `rknn_set_io_mem` with w_stride / h_stride

```c
rknn_tensor_attr attr = {0};
attr.index = 0;
if (rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &attr, sizeof(attr)) != RKNN_SUCC) {
    return -1;
}

// w_stride is read-only: make RGA write the queried width layout.
const uint32_t dst_w_stride = attr.w_stride != 0 ? attr.w_stride : model_width;
// h_stride is write-only: this value comes from the destination allocation/layout.
const uint32_t dst_h_stride = rga_destination_h_stride;
if (rga_helper.ResizeToFd(src_fd, dst_fd, model_width, model_height,
                          dst_w_stride, dst_h_stride,
                          RK_FORMAT_RGB_888) != IM_STATUS_SUCCESS) {
    return -1;
}
attr.h_stride = dst_h_stride;
if (rknn_set_io_mem(ctx, mem, &attr) != RKNN_SUCC) {
    return -1;
}
```

- For the current header, `w_stride` is read-only and `h_stride` is write-only. Those directions are
  part of the API contract, not stylistic advice.
- `w_stride` is expressed in tensor elements rather than bytes in this image-tensor contract; verify
  the selected format/header before applying that statement to another tensor layout.
- If w_stride ≠ width, the NPU reads `w_stride` elements per row, skipping the padding.
- Incorrect w_stride/h_stride cause **garbage output** (NPU reads wrong memory locations).
- For a buffer created specifically as model input, query the model stride and make RGA use it.
- For an externally owned/imported buffer, verify its real layout is accepted by the runtime before
  changing tensor attributes. Never relabel a buffer with strides it does not physically have.

### RGA helper must carry the NPU destination stride

Do not let a helper drop `w_stride` / `h_stride` and call the default-stride `wrapbuffer_fd` form.
Make the destination layout explicit at the interface boundary:

```cpp
struct RgaFdImage {
    int fd;
    int width;
    int height;
    int w_stride;
    int h_stride;
    int format;
};

// Its implementation wraps both descriptors, checks bounds and imcheck(), then submits.
IM_STATUS ResizeToFd(const RgaFdImage& src, const RgaFdImage& dst);

const auto& input_attr = model->GetInputAttr(0);
if (input_attr.w_stride > static_cast<uint32_t>(INT_MAX) ||
    rga_destination_h_stride > static_cast<uint32_t>(INT_MAX)) {
    throw std::overflow_error("RGA stride exceeds int API limit");
}
const int dst_w_stride = input_attr.w_stride != 0
    ? static_cast<int>(input_attr.w_stride)
    : model_width;
const int dst_h_stride = static_cast<int>(rga_destination_h_stride);

const RgaFdImage src = GetValidatedSourceRgaImage();
const RgaFdImage dst = {input_mems_[0]->fd, model_width, model_height,
                        dst_w_stride, dst_h_stride, RK_FORMAT_RGB_888};
if (ResizeToFd(src, dst) != IM_STATUS_SUCCESS) {
    throw std::runtime_error("RGA preprocessing failed");
}
```

If the installed librga lacks the stride-aware `wrapbuffer_fd` macro form, import the fd once and call
`wrapbuffer_handle(handle, width, height, format, w_stride, h_stride)`. The invariant is the same:
RGA destination wrapping, allocation size, and RKNN tensor binding describe one physical layout.

## Why Alignment Matters

Rockchip hardware processes pixels in fixed-size blocks, but the constraints are not universal. The
cited raster table uses a 4-byte base for RGA2-family cores and a 16-byte base for RGA3; pixel
storage converts that byte rule into different width-stride multiples. Codec/BSP-specific MPP
layouts may add padding or metadata, and YUV420 chroma requires even logical geometry.

Misaligned dimensions cause:
1. **RGA `imcheck` failure** or silent data corruption.
2. **MPP decode artifacts** at right/bottom edges.
3. **RKNN tensor stride mismatch** leading to garbage NPU output.

## RGA Format-Specific Alignment

### Common raster formats by RGA generation

| Core family | RGBA8888 width stride | RGB565 width stride | RGB888 width stride | NV12/NV21 width stride |
|---|---:|---:|---:|---:|
| RGA2 family | no additional pixel multiple | 2 | 4 | 4 |
| RGA3 | 4 | 8 | 16 | 16 |

For NV12/NV21 in raster mode, logical x/y/width/height and height stride must also be even. An odd
logical width such as 1281 is invalid; rounding only the width stride does not repair the logical
image. Ten-bit formats and non-linear modes have stricter, different requirements. Run `imcheck`
against the complete source/destination rectangles and selected read modes.

## MPP Buffer Sizing

After MPP reports an information change, read width, height, horizontal stride, vertical stride,
format, and `mpp_frame_get_buf_size(frame)`. When a buffer is attached, require
`mpp_buffer_get_size(mpp_frame_get_buffer(frame))` to cover the reported requirement. The upstream
README's older stride-based formula and buffer-count examples are rules of thumb for its documented
decode path, not universal contracts across codecs, bit depths, compression modes, and BSPs.

Use an external group when the application must supply the allocation pool. An internally allocated
`MppBuffer` can also expose a DMA-BUF fd, so internal allocation alone does not prove a pixel copy.

## RKNN Tensor Stride

When using zero-copy (`rknn_create_mem_from_fd` or `rknn_set_io_mem`), the tensor attributes
`w_stride` and `h_stride` must match the actual buffer layout:

```c
rknn_tensor_attr attr = {0};
attr.index = 0;
if (rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &attr, sizeof(attr)) != RKNN_SUCC) {
    return -1;
}

// w_stride is read-only: the backing layout must satisfy this queried value.
const uint32_t required_w_stride = attr.w_stride ? attr.w_stride : model_width;
if (actual_w_stride != required_w_stride) {
    return -1;
}

// h_stride is write-only: describe the backing allocation at bind time.
attr.h_stride = actual_h_stride;
if (rknn_set_io_mem(ctx, input_mem, &attr) != RKNN_SUCC) {
    return -1;
}
```

If strides don't match, NPU will read/write at wrong offsets and output will be garbage.

## Dynamic Shape / Dynamic Batch Memory Allocation

When using RKNN Dynamic Shape or Dynamic Batching, memory allocation must follow these strict rules to prevent Segmentation Faults (`SIGSEGV`) or buffer overruns:

1. **Allocate for Max Capacity**: determine the maximum supported tensor layout and compute every
   product with checked `size_t` arithmetic. Also compare the Runtime's stride-aware size fields;
   do not encode a raw multi-factor multiplication that can overflow before allocation.
2. **Query the supported shape set**: read the model's dynamic input ranges via
   `rknn_query(ctx, RKNN_QUERY_INPUT_DYNAMIC_RANGE, ...)` before allocating buffers.
3. **Select the active shape per run**: call
   `rknn_set_input_shapes(ctx, n_inputs, attrs)` when exposed by the installed header, then re-query
   `RKNN_QUERY_CURRENT_INPUT_ATTR` / `RKNN_QUERY_CURRENT_OUTPUT_ATTR` and rebind with
   `rknn_set_io_mem`, while keeping the max-capacity DMA-BUF backing store. Follow the
   `examples/functions/dynamic_shape` sample shipped with the installed Toolkit2 release —
   query-command and function names have changed across releases. The singular
   `rknn_set_input_shape` is explicitly deprecated in the current official header.

## Common Mistakes

1. **Passing geometry, strides, or ROI offsets that violate the selected RGA core/format/read-mode contract** → validation failure or incorrect access.
2. **Using a logical packed-size formula for a physically padded or multi-plane layout** → buffer too small.
3. **Assuming MPP internal allocation cannot export a DMA-BUF fd** → unnecessary copy or pool rewrite.
4. **Overwriting RKNN read-only `w_stride`, or failing to set write-only `h_stride` from the real layout** → rejected binding or misread data.
5. **Reusing `importbuffer_fd` every frame** → performance regression (import is expensive; do once).
6. **Assuming RK3568, RK3576, and RK3588 have identical alignment requirements** → verify on target BSP.
7. **Checking `size_with_stride` in only one algorithm package** → sibling packages keep the old,
   undersized allocation path.
8. **Allocating `attr.size` but wrapping the RGA destination with padded strides** → RGA can write
   beyond the DMA-BUF even though the logical tensor dimensions look correct.
9. **Increasing allocation without passing NPU strides to RGA** → avoids one overrun but keeps the
   row layout inconsistent.
10. **Allocating Dynamic Shape DMA-BUF for current shape instead of max shape** → crash (`SIGSEGV`) when a larger frame is passed.

## Verification Snippet

```c
IM_STATUS validate_rga_request(rga_buffer_t src,
                               rga_buffer_t dst,
                               im_rect src_rect,
                               im_rect dst_rect,
                               int usage) {
    if (src_rect.x < 0 || src_rect.y < 0 || src_rect.width <= 0 || src_rect.height <= 0 ||
        dst_rect.x < 0 || dst_rect.y < 0 || dst_rect.width <= 0 || dst_rect.height <= 0 ||
        src_rect.x > src.wstride - src_rect.width ||
        src_rect.y > src.hstride - src_rect.height ||
        dst_rect.x > dst.wstride - dst_rect.width ||
        dst_rect.y > dst.hstride - dst_rect.height) {
        return IM_STATUS_ILLEGAL_PARAM;
    }
    return imcheck(src, dst, src_rect, dst_rect, usage);
}
```

`imcheck` is the final capability/alignment gate; arithmetic checks remain necessary to prevent
overflow before constructing the RGA descriptors.

## Source Snapshot

Validated 2026-07-28 against librga commit
[`2b32edcb97b601b25683e2941d888c8515da6d55`](https://github.com/airockchip/librga/tree/2b32edcb97b601b25683e2941d888c8515da6d55)
and RKNN Toolkit2 commit
[`59a913d172e7f5ff03c9076e2ec7b1b1288ffd08`](https://github.com/airockchip/rknn-toolkit2/tree/59a913d172e7f5ff03c9076e2ec7b1b1288ffd08).
Treat the deployed headers, shared objects, drivers, allocator, and model attributes as authoritative.
