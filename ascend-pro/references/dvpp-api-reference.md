# DVPP API Reference

Detailed parameter descriptions, constraints, and calling sequences for Ascend DVPP (Digital Vision PreProcessing) APIs.

> **⚠️ Memory alignment is critical for all DVPP operations.** Buffer sizes are NOT simply `width × height × bpp`. See [memory-alignment.md](memory-alignment.md) for stride alignment rules and size calculation formulas before writing any DVPP code.

## Overview

DVPP provides hardware-accelerated media processing on Ascend devices:

| Module | Functions |
|---|---|
| **VPC** (Vision Preprocessing Core) | Resize, crop, paste, format conversion (YUV↔RGB), rotate |
| **JPEGD** | JPEG hardware decode |
| **JPEGE** | JPEG hardware encode |
| **PNGD** | PNG hardware decode |
| **VDEC** | Video hardware decode (H.264/H.265) |
| **VENC** | Video hardware encode (H.264/H.265) |

## General Constraints

- **Not all devices support all DVPP modules** — check device spec (e.g., Atlas 200 has no VDEC/VENC)
- DVPP memory must be allocated via `acldvppMalloc` (not `aclrtMalloc`)
- Input/output image alignment requirements vary by device and operation
- All VPC operations require a channel created with `acldvppCreateChannel`
- DVPP APIs are **asynchronous** — requires `aclrtSynchronizeStream` to complete

## Channel Management

### `acldvppCreateChannelDesc` / `acldvppDestroyChannelDesc`

```c
acldvppChannelDesc *acldvppCreateChannelDesc();
void acldvppDestroyChannelDesc(acldvppChannelDesc *channelDesc);
```

Create/destroy a channel descriptor. The descriptor holds channel configuration.

### `acldvppCreateChannel` / `acldvppDestroyChannel`

```c
aclError acldvppCreateChannel(acldvppChannelDesc *channelDesc);
aclError acldvppDestroyChannel(acldvppChannelDesc *channelDesc);
```

Create/destroy a DVPP processing channel. A channel must be created before any VPC/JPEG operations.

- Channel creation is heavyweight — do NOT create/destroy per frame
- Create once, reuse across frames

## Memory Management

### `acldvppMalloc` / `acldvppFree`

```c
aclError acldvppMalloc(void **devPtr, size_t size);
aclError acldvppFree(void *devPtr);
```

Allocate/free DVPP device memory. Memory allocated this way is accessible to DVPP hardware.

- **Alignment**: Output buffer width must be aligned to 16 (or 32, depending on device and format)
- **Size calculation for YUV420SP output**:
  ```
  aligned_width = ALIGN_UP(width, 16)
  aligned_height = ALIGN_UP(height, 2)   // or 16 for some operations
  size = aligned_width * aligned_height * 3 / 2
  ```

## Picture Description

### `acldvppCreatePicDesc` / `acldvppDestroyPicDesc`

```c
acldvppPicDesc *acldvppCreatePicDesc();
void acldvppDestroyPicDesc(acldvppPicDesc *picDesc);
```

Create/destroy a picture descriptor that defines image dimensions, format, and buffer.

### Picture descriptor setters

```c
aclError acldvppSetPicDescData(acldvppPicDesc *picDesc, void *data);
aclError acldvppSetPicDescSize(acldvppPicDesc *picDesc, uint32_t size);
aclError acldvppSetPicDescWidth(acldvppPicDesc *picDesc, uint32_t width);
aclError acldvppSetPicDescHeight(acldvppPicDesc *picDesc, uint32_t height);
aclError acldvppSetPicDescWidthStride(acldvppPicDesc *picDesc, uint32_t widthStride);
aclError acldvppSetPicDescHeightStride(acldvppPicDesc *picDesc, uint32_t heightStride);
aclError acldvppSetPicDescFormat(acldvppPicDesc *picDesc, acldvppPixelFormat format);
```

| Parameter | Description |
|---|---|
| `data` | Pointer to DVPP-allocated buffer |
| `size` | Total buffer size in bytes |
| `width` / `height` | Actual image dimensions |
| `widthStride` | Aligned width (≥ width, alignment depends on format and device) |
| `heightStride` | Aligned height (≥ height, typically 16-byte aligned for H.26x) |
| `format` | Pixel format enum (see below) |

### Pixel formats (`acldvppPixelFormat`)

| Enum Value | Description |
|---|---|
| `PIXEL_FORMAT_YUV420SP_U8` | NV12: Y plane + interleaved UV |
| `PIXEL_FORMAT_YVU420SP_U8` | NV21: Y plane + interleaved VU |
| `PIXEL_FORMAT_YUV444SP_U8` | YUV 4:4:4 semi-planar |
| `PIXEL_FORMAT_RGB_888` | RGB 8:8:8 |
| `PIXEL_FORMAT_BGR_888` | BGR 8:8:8 |
| `PIXEL_FORMAT_ARGB_8888` | ARGB 8:8:8:8 |
| `PIXEL_FORMAT_YUYV_U8` | YUYV packed |

## VPC Operations

### `acldvppVpcResizeAsync`

```c
aclError acldvppVpcResizeAsync(acldvppChannelDesc *channelDesc,
    acldvppPicDesc *inputDesc, acldvppPicDesc *outputDesc,
    acldvppResizeConfig *resizeConfig, aclrtStream stream);
```

Async image resize. Interpolation method controlled by `resizeConfig`.

- `inputDesc` / `outputDesc`: picture descriptors for source and destination
- `resizeConfig`: scaling configuration (created via `acldvppCreateResizeConfig`)
- `stream`: Ascend stream for ordering

**Constraints:**
- Input width/height must be ≥ 32 (varies by device)
- Output width/height must be ≥ 16
- Scaling ratio: output/input between 1/2048 and 16/1
- Width stride alignment: 16 (for YUV420SP) or 32 (for RGB)

### `acldvppVpcCropAsync`

```c
aclError acldvppVpcCropAsync(acldvppChannelDesc *channelDesc,
    acldvppPicDesc *inputDesc, acldvppPicDesc *outputDesc,
    acldvppRoiConfig *cropArea, aclrtStream stream);
```

Async image crop. Extracts a rectangular region from input.

- `cropArea`: cropping rectangle (see `acldvppCreateRoiConfig`)
- If output dimensions differ from crop area, an implicit resize occurs

### `acldvppVpcCropAndPasteAsync`

```c
aclError acldvppVpcCropAndPasteAsync(acldvppChannelDesc *channelDesc,
    acldvppPicDesc *inputDesc, acldvppPicDesc *outputDesc,
    acldvppRoiConfig *cropArea, acldvppRoiConfig *pasteArea,
    acldvppResizeConfig *resizeConfig, aclrtStream stream);
```

Async crop + resize + paste. Crop from source, optionally resize, paste into output at `pasteArea`.

- If `cropArea` dimensions ≠ `pasteArea` dimensions, auto-resize
- Use for detection model pre-processing (crop ROI, resize to model input size)

### `acldvppCreateRoiConfig` / `acldvppDestroyRoiConfig`

```c
acldvppRoiConfig *acldvppCreateRoiConfig(uint32_t left, uint32_t right, uint32_t top, uint32_t bottom);
void acldvppDestroyRoiConfig(acldvppRoiConfig *roiConfig);
```

Create ROI rectangle. The rectangle spans `[left, right]` × `[top, bottom]` inclusive.
- `right` must be > `left`, `bottom` must be > `top`
- Coordinates are in pixel units

### `acldvppCreateResizeConfig` / `acldvppDestroyResizeConfig`

```c
acldvppResizeConfig *acldvppCreateResizeConfig();
void acldvppDestroyResizeConfig(acldvppResizeConfig *resizeConfig);
```

Creates resize configuration. Use `acldvppSetResizeConfigInterpolation` to set algorithm.

```c
aclError acldvppSetResizeConfigInterpolation(acldvppResizeConfig *resizeConfig,
                                             acldvppResizeInterpolation interpolation);
```

| Interpolation | Enum | Notes |
|---|---|---|
| Bilinear | 0 | Default |
| Bicubic | 1 | Sharper, higher quality, more compute |
| Nearest neighbor | 2 | Fastest, may alias |

## JPEG Operations

### `acldvppJpegDecodeAsync`

```c
aclError acldvppJpegDecodeAsync(acldvppChannelDesc *channelDesc,
    const void *jpegData, size_t jpegSize, acldvppPicDesc *outputDesc, aclrtStream stream);
```

Decode JPEG to YUV420SP.

- `jpegData`: pointer to JPEG bitstream (must be in host memory or device memory depending on config)
- `jpegSize`: size of JPEG data
- `outputDesc`: output picture descriptor (must have DVPP-allocated buffer)
- Output is typically YUV420SP NV12

**Constraints:**
- JPEG dimensions (W×H) must be even
- Maximum resolution depends on device (e.g., 8192×8192 for Atlas 300)

### `acldvppJpegEncodeAsync`

```c
aclError acldvppJpegEncodeAsync(acldvppChannelDesc *channelDesc,
    acldvppPicDesc *inputDesc, void *jpegData, size_t *jpegSize, aclrtStream stream);
```

Encode image to JPEG. `jpegData` should point to pre-allocated buffer; `jpegSize` returns actual encoded size.

## Video Decode (VDEC)

### `acldvppVdecCreateChannel` / `acldvppVdecDestroyChannel`

```c
aclError acldvppVdecCreateChannel(acldvppChannelDesc *channelDesc);
aclError acldvppVdecDestroyChannel(acldvppChannelDesc *channelDesc);
```

Create/destroy a video decoding channel.

### `acldvppVdecSendFrame`

```c
aclError acldvppVdecSendFrame(acldvppChannelDesc *channelDesc,
    acldvppStreamDesc *input, acldvppPicDesc *output, int32_t isEos, void *userData);
```

Send a compressed frame to the VDEC for decoding.

- Uses callback mechanism: output frames arrive via registered callback function
- `isEos` signals end of stream
- Input: `acldvppStreamDesc` wrapping the bitstream buffer

### `acldvppVdecSetCallback`

```c
aclError acldvppVdecSetCallback(acldvppChannelDesc *channelDesc,
    acldvppVdecCallback callback, void *userData);
```

Register a callback function invoked when decoded frames are ready.

## Video Encode (VENC)

```c
aclError acldvppVencCreateChannel(acldvppChannelDesc *channelDesc);
aclError acldvppVencDestroyChannel(acldvppChannelDesc *channelDesc);
aclError acldvppVencSendFrame(acldvppChannelDesc *channelDesc,
    acldvppPicDesc *input, void *frameInfo, acldvppStreamDesc *output, void *userData);
```

Creates a video encoding channel and sends frames for encoding. Similar callback-based pattern to VDEC.

## Typical Calling Sequence

```c
// 1. Initialize ACL
aclInit(NULL);
aclrtSetDevice(0);

// 2. Create DVPP channel (once)
acldvppChannelDesc *channelDesc = acldvppCreateChannelDesc();
acldvppCreateChannel(channelDesc);

// 3. Create picture descriptors
acldvppPicDesc *inputDesc = acldvppCreatePicDesc();
acldvppPicDesc *outputDesc = acldvppCreatePicDesc();

// 4. Allocate DVPP memory
void *inBuf, *outBuf;
acldvppMalloc(&inBuf, inputSize);
acldvppMalloc(&outBuf, outputSize);

// 5. Set up descriptors
acldvppSetPicDescData(inputDesc, inBuf);
acldvppSetPicDescWidth(inputDesc, srcW);
acldvppSetPicDescHeight(inputDesc, srcH);
acldvppSetPicDescFormat(inputDesc, PIXEL_FORMAT_YUV420SP_U8);
// ... similar for output

// 6. Create resize config
acldvppResizeConfig *resizeConfig = acldvppCreateResizeConfig();
acldvppSetResizeConfigInterpolation(resizeConfig, 0); // bilinear

// 7. Execute resize (async)
aclrtCreateStream(&stream);
acldvppVpcResizeAsync(channelDesc, inputDesc, outputDesc, resizeConfig, stream);
aclrtSynchronizeStream(stream);

// 8. Cleanup
acldvppDestroyResizeConfig(resizeConfig);
acldvppDestroyPicDesc(inputDesc);
acldvppDestroyPicDesc(outputDesc);
acldvppFree(inBuf);
acldvppFree(outBuf);
acldvppDestroyChannel(channelDesc);
acldvppDestroyChannelDesc(channelDesc);
aclrtResetDevice(0);
aclFinalize();
```
