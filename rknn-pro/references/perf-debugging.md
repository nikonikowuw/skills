# Performance Debugging

## Principle

Do not ask “why is the NPU slow” until you have broken the pipeline into stages. On Rockchip boards, end-to-end regressions are often outside the NPU core itself.

## Stage Breakdown

Time these separately:

- Capture or decode
- Preprocess
- Inference
- Postprocess
- Display or encode
- Queue wait or synchronization time

If stage timing is unavailable, add it before changing architecture.

## Symptom To Hypothesis Map

### High CPU, moderate throughput, low NPU utilization

Suspect:

- Virtual-address fallback in RGA
- Full-frame memcpy into RKNN inputs
- CPU-heavy postprocess
- Cache maintenance overhead caused by CPU-visible cached buffers
- Repeated `importbuffer_fd()` or buffer-handle churn in RGA setup

### Low frame rate, low CPU, high queue wait

Suspect:

- Blocking dequeue or fence wait
- Too few buffers in the pipeline
- Mismatched producer and consumer cadence
- Decoder or display backpressure

### Good inference time, poor end-to-end latency

Suspect:

- Preprocess copy chain
- Format conversion costs
- Postprocess on CPU
- Serialization between stages that should be overlapped

### RGA failures or intermittent slowness

Suspect:

- `librga` and kernel driver mismatch
- Alignment or stride mistakes
- Unsupported format or parameter combination
- Debug build or compatibility mode behavior

### “Zero-copy” path still uses too much CPU

Suspect:

- CPU mapping for inspection or postprocess
- Cache flush or invalidate cost
- Virtual-address submission hidden behind wrappers
- Logging or debug copying in the hot path
- Cache synchronization on cacheable DMA-BUF allocators

## Board Inspection Checklist

- Read CPU frequency policy and thermal state
- Check whether clocks are scaling under load
- Check RGA debug nodes when available
- Check dmesg for driver fallback or parameter errors
- Check if the process is pinning one core with postprocess
- Check if the DDR or memory subsystem is the actual limit

## RGA-Specific Observations From Rockchip FAQ

The RGA FAQ documents that:

- `dma_fd` is generally recommended over virtual address submission.
- Virtual-address paths add CPU work and can force cache synchronization.
- Even `dma_fd` paths can carry cache synchronization overhead depending on allocator behavior.
- Width stride and format alignment mistakes can cause obvious parameter errors.
- RGA driver debug nodes can expose version, logs, and timing-related information depending on the kernel and driver generation.
- `importbuffer_fd()` is a setup cost and should not be paid every frame when a reusable pool exists.

Use those debug nodes before guessing.

## MPP-Specific Observations

MPP documentation states that pure external buffer mode is the most efficient route for zero-copy display style paths. If your decode path cannot hand buffers cleanly to downstream stages, inspect the chosen MPP memory mode first.

## Minimal Measurement Standard

For each experiment, record:

- Board model
- Kernel and BSP origin if known
- `librga` and RGA driver versions if available
- RKNN runtime version if available
- Input resolution and format
- Per-stage average and percentile latency
- CPU usage per major thread if possible

## Fast Triage Order

1. Validate versions with [version-audit.md](version-audit.md).
2. Check whether the alleged zero-copy path still maps or repacks frames on CPU.
3. Check RGA alignment, allocator type, and import pattern.
4. Check MPP memory mode and downstream buffer ownership.
5. Check whether postprocess, not inference, owns the wall time.

## Sources

- Linux kernel dma-buf overview: https://docs.kernel.org/driver-api/dma-buf.html
- Rockchip MPP readme: https://github.com/rockchip-linux/mpp/blob/develop/readme.txt
- Rockchip librga FAQ: https://github.com/airockchip/librga/blob/master/docs/Rockchip_FAQ_RGA_EN.md
- Rockchip RKNN Toolkit2 README: https://github.com/airockchip/rknn-toolkit2
