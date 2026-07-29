# Ascend Buffer And Alignment Verification

DVPP, codecs, AIPP, model I/O, and allocation APIs can impose different address, dimension, stride, and
size constraints. Numeric requirements vary by device, pixel format, operation, and CANN release. Do not
use a universal `16`, `32`, or `64` byte table.

## Required Evidence

| Operation | Buffer Addr Align | Width Stride Align | Height Stride Align | Size Formula |
| --- | --- | --- | --- | --- |
| **DVPP VPC** (YUV420SP input) | 16 bytes | 16 | 2 | `ws * hs * 3 / 2` |
| **DVPP VPC** (YUV420SP_U10 10-bit) | 16 bytes | 32 | 2 | `ws * hs * 3 / 2` |
| **DVPP VPC** (YUV420SP output) | 16 bytes | 16 | 2 | `ws * hs * 3 / 2` |
| **DVPP VPC** (RGB888) | 16 bytes | 32 | 2 | `ws * hs * 3` |
| **DVPP VPC** (ARGB8888) | 16 bytes | 32 | 2 | `ws * hs * 4` |
| **DVPP JPEG decode** | 16 bytes | 16 | 2 | `ws * hs * 3 / 2` (YUV420SP out) |
| **DVPP JPEG encode** | 16 bytes | 16 | 2 | Depends on input format |
| **DVPP VDEC** (H.264/H.265) | 32 bytes | 16 (128 for HiB) | 16 | `ws * hs * 3 / 2` |
| **DVPP VENC** (H.264/H.265) | 32 bytes | 16 (128 for HiB) | 16 | `ws * hs * 3 / 2` |
| **ACL model I/O** | 32 bytes | N/A (linear) | N/A | as reported by `aclmdlGetInputSizeByName` |
| **ACL aclrtMalloc** | 32 bytes (guaranteed) | N/A | N/A | as requested |

- device model and CANN version;
- operation/API and selected pixel/tensor format;
- logical width/height or tensor dimensions;
- width/height stride requirements from exact-version docs or installed headers;
- address/allocation-domain requirement;
- plane layout and per-plane stride/offset rules;
- size-query API when the operation provides one;
- descriptor fields actually passed at runtime.

Store verified numeric rules in the reviewed context with source URL/header, device/CANN scope, and date.

## Safe Arithmetic

Alignment math must validate its inputs and overflow. The bit-mask formula works only for power-of-two
alignment and silently overflows without checks. Prefer an explicit helper:

```cpp
#include <cstddef>
#include <limits>
#include <optional>

std::optional<size_t> align_up(size_t value, size_t alignment) {
    if (alignment == 0) return std::nullopt;
    const size_t remainder = value % alignment;
    if (remainder == 0) return value;
    const size_t increment = alignment - remainder;
    if (value > std::numeric_limits<size_t>::max() - increment) return std::nullopt;
    return value + increment;
}

std::optional<size_t> checked_mul(size_t left, size_t right) {
    if (left != 0 && right > std::numeric_limits<size_t>::max() / left) {
        return std::nullopt;
    }
    return left * right;
}
```

For multi-plane images, calculate each plane from the verified layout and use checked addition. Do not use
`aligned_width * aligned_height * 3 / 2` unless the selected format and operation explicitly define that
layout and both strides have been verified. Prefer vendor size-query APIs when available.

## Allocation Domain

Choose an allocator from the selected operation's documented producer/consumer contract. Do not state that
all DVPP buffers always require one allocator across every device/CANN mode. Prove that both producer and
consumer can access the allocation, and pair every allocation with its matching free API.

For model I/O, query the deployed model descriptor for required byte capacity. Do not add guessed padding
or claim a fixed address-alignment guarantee unless the installed API documentation states it.

## Descriptor Validation

Before submission, assert or log at controlled verbosity:

```text
operation, format, logical W/H, width/height stride, plane offsets, total bytes, allocator/domain
```

Then verify:

- stride is at least the logical extent and meets the selected operation's multiple/range constraints;
- total allocation covers all planes using actual strides;
- descriptor size does not exceed allocation capacity;
- crop/paste ROI coordinate parity and inclusive/exclusive rules match the exact API;
- producer output descriptor matches consumer input expectations without an implicit repack;
- async buffer lifetime extends through completion.

## Common Failures

- Calculating size from logical dimensions instead of actual stride.
- Applying one operation's alignment to VPC, JPEG, VDEC, VENC, and model I/O indiscriminately.
- Treating RGB channel count as a width-stride rule without checking whether stride is pixels or bytes.
- Copying numeric limits from a different Atlas product or CANN release.
- Assuming allocation success proves DVPP accessibility.
- Reusing VDEC output while passing a descriptor with newly calculated rather than actual decoder stride.
- Ignoring overflow or truncating `size_t` into a 32-bit descriptor field.

## Verification Loop

1. Extract the exact constraint from selected-version sources.
2. Implement checked calculations or call the documented size-query API.
3. Compare allocation capacity with every descriptor size and plane offset.
4. Run boundary probes: minimum size, non-aligned logical size, maximum supported size, and invalid input.
5. Check return code, recent error detail, guard instrumentation, and output correctness.
6. Record the verified rule and test result in the active context.
