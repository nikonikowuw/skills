# Ascend Memory Alignment Reference

Ascend hardware (DVPP, AI Core, JPEG/Video codec) enforces strict alignment requirements on buffer
addresses, widths, heights, strides, and total sizes. Misaligned buffers cause silent data corruption,
runtime errors (`aclError` returns), or hardware hangs.

## Quick Reference Table

| Operation | Buffer Addr Align | Width Stride Align | Height Stride Align | Size Formula |
|---|---|---|---|---|
| **DVPP VPC** (YUV420SP input) | 16 bytes | 16 | 2 | `ws * hs * 3 / 2` |
| **DVPP VPC** (YUV420SP output) | 16 bytes | 16 | 2 | `ws * hs * 3 / 2` |
| **DVPP VPC** (RGB888) | 16 bytes | 32 | 2 | `ws * hs * 3` |
| **DVPP VPC** (ARGB8888) | 16 bytes | 32 | 2 | `ws * hs * 4` |
| **DVPP JPEG decode** | 16 bytes | 16 | 2 | `ws * hs * 3 / 2` (YUV420SP out) |
| **DVPP JPEG encode** | 16 bytes | 16 | 2 | Depends on input format |
| **DVPP VDEC** (H.264/H.265) | 32 bytes | 16 (128 for HiB) | 16 | `ws * hs * 3 / 2` |
| **DVPP VENC** (H.264/H.265) | 32 bytes | 16 (128 for HiB) | 16 | `ws * hs * 3 / 2` |
| **ACL model I/O** | 32 bytes | N/A (linear) | N/A | as reported by `aclmdlGetInputSizeByName` |
| **ACL aclrtMalloc** | 32 bytes (guaranteed) | N/A | N/A | as requested |

> **ws** = width_stride, **hs** = height_stride (aligned values).
> Alignment values may vary by device model (e.g., Atlas 200 vs 910B) and CANN version.
> Always check the device-specific documentation for your target.

## Alignment Calculation Functions

### C / C++

```c
#define ALIGN_UP(x, align)  (((x) + (align) - 1) & ~((align) - 1))
#define ALIGN_DOWN(x, align) ((x) & ~((align) - 1))

// YUV420SP NV12 buffer size
size_t calc_yuv420sp_size(int32_t width, int32_t height) {
    int32_t ws = ALIGN_UP(width, 16);     // width stride
    int32_t hs = ALIGN_UP(height, 2);     // height stride
    return (size_t)ws * hs * 3 / 2;
}

// RGB888 buffer size
size_t calc_rgb888_size(int32_t width, int32_t height) {
    int32_t ws = ALIGN_UP(width, 32);     // RGB needs 32-byte stride alignment
    int32_t hs = ALIGN_UP(height, 2);
    return (size_t)ws * hs * 3;
}
```

### Python

```python
def align_up(x, align):
    return (x + align - 1) // align * align

def calc_yuv420sp_size(width, height):
    ws = align_up(width, 16)
    hs = align_up(height, 2)
    return ws * hs * 3 // 2

def calc_rgb888_size(width, height):
    ws = align_up(width, 32)
    hs = align_up(height, 2)
    return ws * hs * 3
```

## Why Alignment Matters

Ascend's DVPP and AI Core hardware processes pixels in fixed-size blocks (e.g., 16×16 for
video codecs, 2×2 for YUV420 chroma). Misaligned widths cause:

1. **Hardware reads garbage pixels** at the right/bottom edges of the image.
2. **Buffer overflow** — if you allocate `width * height * 3 / 2` without alignment, the hardware
   may write beyond the buffer when processing at aligned strides.
3. **Silent corruption** — the output image looks correct in the top-left but has shifted colors
   or artifacts at boundaries.
4. **Interface errors** — `acldvppVpcResizeAsync` returns an error code when stride alignment is wrong.

Always use `acldvppMalloc` (not `aclrtMalloc` or regular `malloc`) for DVPP memory. `acldvppMalloc`
handles address alignment automatically — but you still need to pass the correctly aligned size.

## ACL Model I/O Buffer Alignment

For `aclrtMalloc` used with model inference:

```c
// Size from model metadata (already includes internal alignment)
size_t inputSize = 0;
aclmdlGetInputSizeByName(modelId, "input", &inputSize);
void *devBuf = NULL;
aclrtMalloc(&devBuf, inputSize, ACL_MEM_MALLOC_HUGE_FIRST);
// devBuf is guaranteed 32-byte aligned by aclrtMalloc
```

- Do **not** add extra alignment to sizes returned by `aclmdlGetInputSizeByName` — they already include it.
- `aclrtMalloc` returns 32-byte aligned addresses automatically.
- When using `aclCreateDataBuffer`, the `data` pointer can be the raw `aclrtMalloc` pointer.

## DVPP Image Dimension Constraints (by Operation)

### VPC Resize / Crop

| Constraint | YUV420SP | RGB888 | ARGB8888 |
|---|---|---|---|
| Min input width | 32 | 32 | 32 |
| Min input height | 32 | 32 | 32 |
| Min output width | 16 | 16 | 16 |
| Min output height | 16 | 16 | 16 |
| Max input width | varies by device (≤ 8192 typical) | same | same |
| Max input height | varies by device (≤ 8192 typical) | same | same |
| Width stride alignment | 16 | 32 | 32 |
| Height stride alignment | 2 | 2 | 2 |
| Scaling ratio (out/in) | [1/2048, 16] | [1/2048, 16] | [1/2048, 16] |

### JPEG Decode

| Constraint | Value |
|---|---|
| Min width | 32 for YUV420SP output |
| Min height | 2 for YUV420SP output |
| Max width | 8192 (varies by device) |
| Max height | 8192 (varies by device) |
| Width alignment | 16 (output YUV420SP stride) |
| Height alignment | 2 (output YUV420SP stride) |

### Video Decode (VDEC)

| Constraint | Value |
|---|---|
| Width stride alignment | 16 (128 for HiB/High Profile) |
| Height stride alignment | 16 |
| Min width | 128 (H.264), 128 (H.265) |
| Min height | 32 (H.264), 32 (H.265) |
| Max resolution | Device-dependent (e.g., 4096×4096 for Atlas 300) |

## Common Mistakes

1. **Using `aclrtMalloc` instead of `acldvppMalloc` for DVPP buffers**
   → DVPP hardware cannot access memory allocated by `aclrtMalloc` on some device configurations.
   → Always use `acldvppMalloc`/`acldvppFree` for DVPP input/output buffers.

2. **Using `malloc` or `new` for host-side DVPP input data**
   → If the JPEG data or raw frame data is supplied from host, it must be in a buffer accessible
     by the DMA engine. Use `aclrtMallocHost` for best performance, or `acldvppMalloc` if
     the data originates/terminates on device.

3. **Buffer size = width × height × channels (ignoring stride)**
   → This under-allocates. Always use aligned stride for size calculation.

4. **Using 16-byte stride for RGB format**
   → RGB requires 32-byte stride alignment. YUV420SP works with 16.

5. **Assuming alignment requirements are same across all Ascend devices**
   → Atlas 200/300/500, 200I A2, 910B, 310P all may have subtle differences.
   → When in doubt, check CANN documentation matching the target device.

6. **Video decode output aligned height at 16, but post-process (VPC) expects 2**
   → After VDEC output (stride-aligned to 16), when feeding into VPC as input,
     the stride in the picture descriptor should reflect the actual stride (16-aligned).
     The VPC will handle the remaining stride internally.

## Verification Snippet

```c
// Quick alignment check for a DVPP buffer
void check_buffer_alignment(const char* label, void* addr, size_t size,
                            int32_t width, int32_t height,
                            acldvppPixelFormat format) {
    int ws_align = (format == PIXEL_FORMAT_RGB_888) ? 32 : 16;
    int hs_align = 2;

    int32_t expected_ws = ALIGN_UP(width, ws_align);
    int32_t expected_hs = ALIGN_UP(height, hs_align);
    size_t expected_size;

    if (format == PIXEL_FORMAT_YUV420SP_U8 || format == PIXEL_FORMAT_YVU420SP_U8) {
        expected_size = expected_ws * expected_hs * 3 / 2;
    } else if (format == PIXEL_FORMAT_RGB_888) {
        expected_size = expected_ws * expected_hs * 3;
    } else {
        expected_size = expected_ws * expected_hs * 4;  // ARGB
    }

    printf("[%s] addr=%p (%%16=%ld) ws=%d hs=%d size=%zu (expected=%zu)\n",
           label, addr, (uintptr_t)addr % 16,
           expected_ws, expected_hs, size, expected_size);

    assert((uintptr_t)addr % 16 == 0);  // addr 16-byte aligned
    assert(size >= expected_size);       // size sufficient
}
```
