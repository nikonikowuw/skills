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

| Operation | Width Stride Align | Height Stride Align | Buffer Addr Align | Size Formula |
|---|---|---|---|---|
| **RGA** RGB565 | 2 | 1 | 4 | `ws * hs * 2` |
| **RGA** RGB888 | 4 | 1 | 4 | `ws * hs * 3` |
| **RGA** RGBA/BGRA8888 | 4 | 1 | 4 | `ws * hs * 4` |
| **RGA** NV12/NV21 | 4 | 2 | 4 | `ws * hs * 3 / 2` |
| **MPP** decode (YUV420SP) | 16 | 16 | varies | `ws * hs * 2` (safe) |
| **MPP** encode (YUV420SP) | 16 | 16 | varies | `ws * hs * 3 / 2` |
| **RKNN** `rknn_inputs_set` (host→NPU copy) | model-defined stride | model-defined stride | 4 (FP32) / 2 (FP16) / 1 (UINT8) | from `rknn_tensor_attr.size` |
| **RKNN** `rknn_create_mem` (NPU-side) | model-defined stride | model-defined stride | page (commonly 4KB, verify target) | `max(size, size_with_stride, stride-derived bytes)`, page-aligned |
| **RKNN** `rknn_create_mem_from_fd` (DMA-BUF import) | set w_stride to match source | set h_stride to match source | page (4KB, from source allocator) | from source buffer |
| **RKNN** w_stride / h_stride in `rknn_set_io_mem` | must match actual buffer stride (query via `rknn_query`) | must match actual buffer stride | N/A | from `rknn_tensor_attr` |
| **DMA-BUF** dma_heap | 4 (varies) | 4 (varies) | page (4KB) | as requested |

> **ws** = width_stride, **hs** = height_stride.
> Alignment may vary by BSP version and SoC (RK3568 vs RK3576 vs RK3588).

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

// RGA NV12 buffer size
size_t calc_rga_nv12_size(uint32_t width, uint32_t height) {
    size_t ws = AlignUpChecked(width, 4);     // RGA NV12 width stride = 4-byte aligned
    size_t hs = AlignUpChecked(height, 2);    // RGA NV12 height stride = 2-byte aligned
    // Note: Use checked multiplication in real code to prevent overflow here as well
    return ws * hs * 3 / 2;
}
```

> **Legacy Anti-Pattern:** The classic macro `#define ALIGN_UP(x, align) (((x) + (align) - 1) & ~((align) - 1))` only works for power-of-2 alignments and silently wraps around on integer overflow. Do not use it in new code.

### Python

```python
def align_up(x, align):
    return (x + align - 1) // align * align

def rga_nv12_size(width, height):
    ws = align_up(width, 4)
    hs = align_up(height, 2)
    return ws * hs * 3 // 2

def mpp_decode_size(width, height):
    ws = align_up(width, 16)
    hs = align_up(height, 16)
    return ws * hs * 2
```

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
rknn_input input;
input.buf = host_buffer;           // host-side buffer
input.size = image_size;           // total bytes
input.pass_through = 0;            // runtime handles quantize
input.type = RKNN_TENSOR_UINT8;
input.fmt = RKNN_TENSOR_NHWC;
rknn_inputs_set(ctx, 1, &input);
```

- Meet the host type's alignment and the selected Runtime API contract. This path may perform an
  internal copy or conversion; do not infer a direct DMA read or a universal address-alignment rule.
- For `UINT8`, byte alignment satisfies the C object type, but the surrounding image rows and source
  allocator can impose stronger requirements.
- For `FP32`, use at least the platform/type alignment and measure any Runtime conversion cost.
- For NEON-optimized CPU preprocessing feeding this path: **16-byte alignment** improves performance.

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
const uint32_t dst_h_stride = attr.h_stride != 0 ? attr.h_stride : model_height;

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

input_mems_[i] = rknn_create_mem(ctx_, alloc_size);
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
rknn_tensor_mem *mem = rknn_create_mem_from_fd(ctx, dma_fd, dma_virt_addr, size, 0);
```

- Imports an existing DMA-BUF from RGA, MPP, or dma_heap.
- Address alignment is inherited from the source (typically 4KB page-aligned).
- **Critical**: `w_stride` / `h_stride` in `rknn_tensor_attr` must match the actual buffer layout.
  Query the model's expected stride via `rknn_query`, then override with the real stride.

### Path 4: `rknn_set_io_mem` with w_stride / h_stride

```c
rknn_tensor_attr attr;
attr.index = 0;
rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &attr, sizeof(attr));

// For an RGA-produced model input, make RGA write this queried layout.
const uint32_t dst_w_stride = attr.w_stride != 0 ? attr.w_stride : model_width;
const uint32_t dst_h_stride = attr.h_stride != 0 ? attr.h_stride : model_height;
rga_helper.ResizeToFd(src_fd, dst_fd, model_width, model_height,
                      dst_w_stride, dst_h_stride, RK_FORMAT_RGB_888);
rknn_set_io_mem(ctx, mem, &attr);
```

- `w_stride` is in **elements** (not bytes) for NHWC/NCHW formats.
- If w_stride ≠ width, the NPU reads `w_stride` elements per row, skipping the padding.
- Incorrect w_stride/h_stride cause **garbage output** (NPU reads wrong memory locations).
- For a buffer created specifically as model input, query the model stride and make RGA use it.
- For an externally owned/imported buffer, verify its real layout is accepted by the runtime before
  changing tensor attributes. Never relabel a buffer with strides it does not physically have.

### RGA helper must carry the NPU destination stride

Do not let a helper drop `w_stride` / `h_stride` and call the default-stride `wrapbuffer_fd` form.
Make the destination layout explicit at the interface boundary:

```cpp
IM_STATUS RgaHelper::ResizeToFd(int src_fd,
                               int dst_fd,
                               int dst_width,
                               int dst_height,
                               int dst_w_stride,
                               int dst_h_stride,
                               int dst_format) {
    rga_buffer_t dst = wrapbuffer_fd(dst_fd,
                                     dst_width,
                                     dst_height,
                                     dst_format,
                                     dst_w_stride,
                                     dst_h_stride);
    // Wrap src with its own real dimensions and strides, run imcheck, then resize/convert.
    // ...
}

const auto& input_attr = model->GetInputAttr(0);
const int dst_w_stride = input_attr.w_stride != 0
    ? static_cast<int>(input_attr.w_stride)
    : model_width;
const int dst_h_stride = input_attr.h_stride != 0
    ? static_cast<int>(input_attr.h_stride)
    : model_height;

rga_helper.ResizeToFd(src_fd, input_mems_[0]->fd,
                      model_width, model_height,
                      dst_w_stride, dst_h_stride,
                      RK_FORMAT_RGB_888);
```

If the installed librga lacks the stride-aware `wrapbuffer_fd` macro form, import the fd once and call
`wrapbuffer_handle(handle, width, height, format, w_stride, h_stride)`. The invariant is the same:
RGA destination wrapping, allocation size, and RKNN tensor binding describe one physical layout.

## Why Alignment Matters

Rockchip hardware processes pixels in fixed-size blocks:
- RGA fetches lines in 4-byte or 32-bit aligned units.
- MPP video codecs operate on 16×16 macroblocks.
- YUV420 chroma operates on 2×2 blocks.

Misaligned dimensions cause:
1. **RGA `imcheck` failure** or silent data corruption.
2. **MPP decode artifacts** at right/bottom edges.
3. **RKNN tensor stride mismatch** leading to garbage NPU output.

## RGA Format-Specific Alignment

### NV12 (YUV420SP)

```cpp
// CORRECT (Industrial Standard)
size_t w_stride = AlignUpChecked(width, 4);    // width 1281 -> stride 1284 (not 1281!)
size_t h_stride = AlignUpChecked(height, 2);
size_t size = w_stride * h_stride * 3 / 2;

// WRONG — will fail imcheck or corrupt
size_t size = width * height * 3 / 2;
```

**Common failure:** `NV12` width `1281` fails because 1281 is not aligned to 2 (let alone 4).
Always align before passing to RGA.

### RGB888

```cpp
size_t w_stride = AlignUpChecked(width, 4);     // 4-byte alignment
```

### RGB565

```cpp
size_t w_stride = AlignUpChecked(width, 2);     // 2-byte alignment
```

## MPP Buffer Sizing

MPP's decode buffer sizing:

```text
Pixel data: hor_stride * ver_stride * 3 / 2
Extra info: hor_stride * ver_stride / 2
Safe total: hor_stride * ver_stride * 2
```

The "safe total" includes padding for hardware alignment and metadata.
When in doubt, use `hor_stride * ver_stride * 2`.

H.264/H.265 decode typically needs a pool of **20+** buffers.
MPP pure external mode: user provides buffers via `mpp_buffer_import`.

## RKNN Tensor Stride

When using zero-copy (`rknn_create_mem_from_fd` or `rknn_set_io_mem`), the tensor attributes
`w_stride` and `h_stride` must match the actual buffer layout:

```c
rknn_tensor_attr attr;
rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &attr, sizeof(attr));

// Update strides to match the actual buffer (e.g., from RGA output)
attr.w_stride = AlignUpChecked(model_width, 4);    // must match buffer stride
attr.h_stride = AlignUpChecked(model_height, 2);   // must match buffer stride

rknn_set_io_mem(ctx, input_mem, &attr);
```

If strides don't match, NPU will read/write at wrong offsets and output will be garbage.

## Dynamic Shape / Dynamic Batch Memory Allocation

When using RKNN Dynamic Shape or Dynamic Batching, memory allocation must follow these strict rules to prevent Segmentation Faults (`SIGSEGV`) or buffer overruns:

1. **Allocate for Max Capacity**: DMA-BUF buffers (`rknn_create_mem` or DRM allocations) MUST be sized for the **maximum supported batch size and spatial resolution**:
   `alloc_size = max_batch * max_w_stride * max_h_stride * channels * bytes_per_pixel`
2. **Query the supported shape set**: read the model's dynamic input ranges via
   `rknn_query(ctx, RKNN_QUERY_INPUT_DYNAMIC_RANGE, ...)` before allocating buffers.
3. **Select the active shape per run**: call `rknn_set_input_shapes` (name per the installed
   header) with the current frame's shape, then re-query
   `RKNN_QUERY_CURRENT_INPUT_ATTR` / `RKNN_QUERY_CURRENT_OUTPUT_ATTR` and rebind with
   `rknn_set_io_mem`, while keeping the max-capacity DMA-BUF backing store. Follow the
   `examples/functions/dynamic_shape` sample shipped with the installed Toolkit2 release —
   query-command and function names have changed across releases.

## Common Mistakes

1. **Passing unaligned width/height to RGA** → `imcheck` fails or silent corruption.
2. **Using `width * height * 3 / 2` instead of aligned stride formula** → buffer too small.
3. **MPP decode using internal mode when zero-copy needed** → can't get DMA-BUF fd.
4. **RKNN passthrough input without setting correct `w_stride`/`h_stride`** → NPU misreads data.
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
#include <assert.h>

void check_rga_alignment(const char* label, int width, int height, int format) {
    int ws_align = 4;  // default for RGB888/RGBA/NV12
    int hs_align = 1;  // default for RGB

    if (format == RK_FORMAT_RGB_565) {
        ws_align = 2;
    } else if (format == RK_FORMAT_YCbCr_420_SP || format == RK_FORMAT_YCbCr_422_SP) {
        hs_align = 2;
    }

    assert(width % ws_align == 0 && "RGA width alignment failed");
    assert(height % hs_align == 0 && "RGA height alignment failed");
    printf("[%s] width=%d (align=%d) height=%d (align=%d) OK\n",
           label, width, ws_align, height, hs_align);
}
```
