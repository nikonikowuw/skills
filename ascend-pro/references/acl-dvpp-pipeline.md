# ACL And DVPP Pipeline Guide

## Goal

Keep image or tensor data in the most efficient memory domain from producer to consumer, and avoid unnecessary CPU conversion, host-to-device copies, device-to-host copies, and stream synchronization.

## Ascend Pipeline Shape

The common high-performance inference path is:

`capture, decode, or image load -> DVPP or CPU preprocess -> device buffer -> AIPP or ACL model input -> OM inference -> postprocess -> result sink`

The critical design question at each hop is:

- Does the next stage consume the current memory directly?
- Or does the code copy to host memory, repack, convert, or allocate a new device buffer every frame?

> ⚠️ **Memory alignment is critical for DVPP.** See [memory-alignment.md](memory-alignment.md) for stride alignment rules and buffer size formulas.

## DVPP Guidance

Use DVPP when the target device and CANN package support the requested media operation and format combination. DVPP can help with JPEG decode, video decode, resize, crop, paste, and colorspace work, but capabilities and constraints vary by device and CANN release.

Design consequences:

- Audit format, width, height, stride, alignment, and memory type before using DVPP.
- Do not assume OpenCV BGR buffers can move into DVPP without conversion cost.
- Avoid per-frame creation and destruction of channels, descriptors, and buffers in hot paths.
- Prefer stable pools and explicit lifetime management.
- Measure whether DVPP reduces end-to-end latency; offloading preprocess can still lose if synchronization or format conversion dominates.

## AIPP Guidance

AIPP can move common preprocessing into the model pipeline when conversion-time configuration matches runtime input assumptions.

Use AIPP consideration when the project does CPU-side:

- Color conversion.
- Resize or crop policies that match the model configuration.
- Mean and variance normalization.
- Channel reorder.
- Padding or letterboxing policies that can be expressed in the conversion config.

Do not blindly move preprocessing to AIPP. Confirm:

- The model was converted with the intended AIPP config.
- Runtime input format and shape match the config.
- Accuracy validation passes after the change.
- The end-to-end path removes real CPU or copy work.

## ACL Runtime Guidance

Common performance-sensitive runtime areas:

- `aclrtMalloc` and `aclrtFree` inside per-frame loops.
- Repeated `aclrtMemcpy` between host and device.
- Synchronous `aclmdlExecute` when async execution and pipelining would be safe.
- `aclrtSynchronizeStream` after every operation.
- Full output tensor readback when postprocess could be reduced, batched, or moved.
- Missing warmup when measuring model execution.

Use stable input and output buffers where possible. If dynamic shapes or multiple models force reallocation, make the cost explicit in stage timing.

## Async Is Not Automatically Parallel

Async APIs only help if the pipeline avoids immediate synchronization. Audit:

- Whether every async operation is followed by a stream synchronize.
- Whether producer and consumer queues have enough buffering.
- Whether output readback serializes all streams.
- Whether CPU postprocess is single-threaded and backpressures the NPU.

## Common Copy Traps

- OpenCV or FFmpeg decode to host memory, then full-frame CPU conversion, then `aclrtMemcpy` into model input.
- DVPP output copied back to host for inspection before model input.
- Model output copied fully to host when only a small top-k or detection metadata path is needed.
- New device buffers allocated and freed every frame.
- AIPP configured but CPU preprocessing still runs because the runtime input path was not simplified.
- Benchmark code measures only `aclmdlExecute` while product code pays preprocess and postprocess costs.

## What To Prove Before Claiming Zero-Copy

- Original data owner and memory type.
- Every host/device transfer.
- Whether DVPP output remains device-resident.
- Whether AIPP is actually active for the deployed OM.
- Which stream each operation uses.
- Where synchronization occurs.
- Whether postprocess requires full tensor readback.

## Debug Procedure

1. Draw the exact data lineage from source to sink.
2. Log allocation, memcpy, descriptor creation, model input binding, stream sync, and output retrieval.
3. Time each stage separately.
4. Compare CPU preprocess against DVPP or AIPP only after format and accuracy are verified.
5. If async is claimed, verify the queue and synchronization design rather than trusting API names.
6. If a media operation fails or falls back, check CANN version, device support, format, stride, and alignment before rewriting architecture.
