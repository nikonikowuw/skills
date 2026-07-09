# Zero-Copy Inference Pipeline Guide

How to design and verify inferencing pipelines that minimize or eliminate host-device copies on Ascend hardware.

## The Golden Path

```
source ──[device memory]──> DVPP preproc ──[device]──> AIPP/ACL input ──[NPU]──> OM inference ──[device partial readback]──> postprocess
```

Each hop stays in device memory. No `aclrtMemcpy(H2D)` or `aclrtMemcpy(D2H)` in the hot path.

## Memory Domain Map

| Buffer Location | Allocation API | Visibility | Typical Use |
|---|---|---|---|
| Device memory (NPU DDR) | `aclrtMalloc` | NPU only | Model input/output tensors, DVPP output |
| Host memory (physically contiguous) | `aclrtMallocHost` | CPU + DMA | Zero-copy input sources, large buffers |
| Host memory (virtual) | `malloc`/`new` | CPU only | OpenCV, ffmpeg output, control data |
| DVPP device memory | `acldvppMalloc` | DVPP + NPU | Raw decoded frames, VPC output |
| AIPP | config file + `--insert_op_conf` | inside model pipe | Preprocessing absorbed into model pipeline |

## Common Copy Patterns (Anti-Patterns)

### Anti-pattern 1: CPU preprocess → H2D copy
```
OpenCV decode → CPU RGB → BGR → resize → aclrtMemcpy(H2D) → model input
```
**Fix:** DVPP decode + VPC resize, keep device-resident. Or AIPP for resize/CSC.

### Anti-pattern 2: Readback for inspection → re-upload
```
DVPP output → aclrtMemcpy(D2H) for "checking" → aclrtMemcpy(H2D) → model input
```
**Fix:** Keep DVPP output on device. Debug with selective D2H on first frame only.

### Anti-pattern 3: Per-frame allocation churn
```
for each frame:
    aclrtMalloc(input_buf, size)
    aclrtMalloc(output_buf, size)
    aclmdlExecute(...)
    aclrtFree(input_buf)
    aclrtFree(output_buf)
```
**Fix:** Pre-allocate buffer pool once; reuse. Use double/triple buffering for async pipelines.

### Anti-pattern 4: Full tensor readback
```
aclmdlExecute → aclrtMemcpy(D2H, full_output) → CPU postprocess → select top-5
```
**Fix:** If postprocess only needs metadata (e.g., detection boxes), restructure to read only the relevant portion, or move postprocess to device.

### Anti-pattern 5: Synchronize after every operation
```
acldvppVpcResizeAsync(...) → aclrtSynchronizeStream(...)
aclrtMemcpyAsync(...) → aclrtSynchronizeStream(...)
aclmdlExecuteAsync(...) → aclrtSynchronizeStream(...)
```
**Fix:** Queue all operations, synchronize once at the end. Use separate streams for producer/consumer pipelining.

## Zero-Copy Verification Procedure

For each claimed zero-copy path, trace every byte:

1. **Source allocation**: Where is the input buffer allocated? (device? host?)
2. **First touch**: Who writes to it first? (VPU? CPU? DMA?)
3. **Transformations**: Any format conversion, resize, crop along the way? Where does it happen? (CPU? DVPP? AIPP?)
4. **Boundary crossings**: Every `aclrtMemcpy` call in the path. Classify H2D, D2H, D2D.
5. **Synchronization**: Where does the code call `aclrtSynchronizeStream` or `aclrtSynchronizeDevice`?
6. **Lifetime management**: Are buffers allocated per-frame or pooled?
7. **Output routing**: Is the full output tensor copied to host, or only metadata?

## Async Pipeline Design

### Double-buffered async inference

```c
// Setup: two sets of buffers
aclrtMalloc(input_buf[0], ...); aclrtMalloc(input_buf[1], ...);
aclrtMalloc(output_buf[0], ...); aclrtMalloc(output_buf[1], ...);
aclrtCreateStream(stream);

int frame = 0;
while (has_data) {
    int buf_idx = frame % 2;
    // Preprocess next frame into input_buf[buf_idx]
    preprocess_frame(frame, input_buf[buf_idx]);

    // Async inference
    aclmdlExecuteAsync(modelId, input_buf[buf_idx], output_buf[buf_idx], stream);

    if (frame > 0) {
        // Process previous output while current inference runs
        int prev_idx = (frame - 1) % 2;
        aclrtSynchronizeStream(stream);  // or use callback
        process_output(output_buf[prev_idx]);
    }
    frame++;
}
// Final sync
aclrtSynchronizeStream(stream);
process_output(output_buf[(frame-1) % 2]);
```

### Triple-buffering for decode → preproc → infer → postproc

Use 3 streams:
- Stream A: DVPP decode + VPC
- Stream B: AIPP (if dynamic) + model input binding + inference
- Stream C: output readback + postprocess

With 3 buffer sets to decouple producer/consumer timing.

## Device-Memory Buffer Pools

### Input buffer pool pattern

```c
#define POOL_SIZE 4
typedef struct {
    void *devPtr;
    size_t size;
    int in_use;
} BufferSlot;

BufferSlot input_pool[POOL_SIZE];
void *acquire_input_buffer(size_t required_size) {
    for (int i = 0; i < POOL_SIZE; i++) {
        if (!input_pool[i].in_use) {
            if (input_pool[i].size < required_size) {
                aclrtFree(input_pool[i].devPtr);
                aclrtMalloc(&input_pool[i].devPtr, required_size, ACL_MEM_MALLOC_HUGE_FIRST);
                input_pool[i].size = required_size;
            }
            input_pool[i].in_use = 1;
            return input_pool[i].devPtr;
        }
    }
    // Block until one is free (or grow pool)
    return NULL;
}
```

## Profiling Copies

Use Ascend profiling tools to find hidden copies:

```bash
# Enable profiling
export ASCEND_PROFILING_OUTPUT=/path/to/profiling
export ASCEND_PROFILING_MODE=taskwise

# Run inference
./your_pipeline

# Check for H2D/D2H transfers in profiling output
# Look for: Memcpy(H2D), Memcpy(D2H), Memcpy(D2D)
```

### Stage timing to isolate copy costs

```python
# scripts/summarize-stage-latency.py
# Use it on timing logs to find which stage dominates
```

## Design Principles

1. **Device-resident handoff**: If the next stage can consume the current buffer directly, do not route through host.
2. **Prefetch and pipeline**: Let the NPU work while CPU prepares the next frame.
3. **Pool, don't allocate**: Per-frame malloc/free is a throughput killer.
4. **Measure, don't assume**: What looks zero-copy may have hidden D2H via AIPP fallback or DVPP alignment copy.
5. **Partial readback**: Postprocess on device when possible; only read back what the application needs.
