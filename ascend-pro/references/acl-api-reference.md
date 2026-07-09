# AscendCL API Reference

Detailed parameter descriptions, calling sequences, and constraints for AscendCL (C/C++).

## Device & Context Management

### `aclrtSetDevice`

```c
aclError aclrtSetDevice(int32_t deviceId);
```

Activates a physical device for the calling thread. Creates a default context. Must be called before any other ACL operation.

- **deviceId**: 0-based index (check via `npu-smi info`)
- Returns `ACL_SUCCESS` on success
- Each thread should call this independently
- Device is "owned" by the thread until `aclrtResetDevice`

### `aclrtCreateContext`

```c
aclError aclrtCreateContext(aclrtContext *context, int32_t deviceId);
```

Creates a context on a device without setting it as default. Useful for multi-context designs.

### `aclrtGetRunMode`

```c
aclError aclrtGetRunMode(aclrtRunMode *runMode);
```

Returns `ACL_DEVICE` (Ascend device runs inference) or `ACL_HOST` (host CPU only). Determines whether `aclrtMalloc` allocates device memory or host memory.

## Memory Management

### `aclrtMalloc`

```c
aclError aclrtMalloc(void **devPtr, size_t size, aclrtMemMallocPolicy policy);
```

Allocates device memory. Memory must be freed with `aclrtFree`.

| Policy | Meaning |
|---|---|
| `ACL_MEM_MALLOC_HUGE_FIRST` | Default. Try huge pages first, fall back to normal. |
| `ACL_MEM_MALLOC_HUGE_ONLY` | Only huge pages. Fails if unavailable. |
| `ACL_MEM_MALLOC_NORMAL_ONLY` | Only normal pages. Larger allocation limit but lower bandwidth. |

- **Alignment**: 32 bytes (for input/output of model inference)
- **Size limit**: device memory total varies by product (e.g., Atlas 200: ~8 GB shared)
- **Performance**: huge pages give better bandwidth; use `ACL_MEM_MALLOC_HUGE_FIRST` for model I/O

### `aclrtMallocHost`

```c
aclError aclrtMallocHost(void **hostPtr, size_t size);
```

Allocates physically contiguous host memory. Preferred for high-bandwidth DMA transfers. Must free with `aclrtFreeHost`.

- **Advantage**: Higher H2D/D2H bandwidth vs regular `malloc` due to contiguous physical pages
- **Use when**: Large or frequent host-device transfers in the hot path
- **Avoid when**: Trying to eliminate copies (prefer device-resident)

### `aclrtMemcpy`

```c
aclError aclrtMemcpy(void *dst, size_t dstSize, const void *src, size_t srcSize, aclrtMemcpyKind kind);
```

Synchronous memory copy. Blocks until complete.

| kind | Direction | Typical Use |
|---|---|---|
| `ACL_MEMCPY_HOST_TO_HOST` | Host → Host | Rarely needed |
| `ACL_MEMCPY_HOST_TO_DEVICE` | Host → Device | Upload input data to NPU |
| `ACL_MEMCPY_DEVICE_TO_HOST` | Device → Host | Read back inference output |
| `ACL_MEMCPY_DEVICE_TO_DEVICE` | Device → Device | Move data between devices or within device |

- `srcSize` and `dstSize` must match for the transfer size
- For overlapping transfers, use `aclrtMemcpyAsync`

### `aclrtMemcpyAsync`

```c
aclError aclrtMemcpyAsync(void *dst, size_t dstSize, const void *src, size_t srcSize,
                          aclrtMemcpyKind kind, aclrtStream stream);
```

Asynchronous memcpy. Returns immediately; completion is ordered on the stream.

- **Must synchronize** with `aclrtSynchronizeStream` before accessing `dst` from host
- Multiple async memcpys on the same stream are executed in order
- Use separate streams for overlapping compute and transfer

### `aclrtMemset` / `aclrtMemsetAsync`

```c
aclError aclrtMemset(void *devPtr, size_t maxCount, int32_t value, size_t count);
aclError aclrtMemsetAsync(void *devPtr, size_t maxCount, int32_t value, size_t count, aclrtStream stream);
```

Device memory fill. Async version requires stream synchronization.

## Stream & Synchronization

### `aclrtCreateStream`

```c
aclError aclrtCreateStream(aclrtStream *stream);
```

Creates an Ascend stream — a sequence of operations that execute in order.

- Streams are **per-context** (create after setting device/context)
- Operations on different streams may execute concurrently (if hardware supports)
- Operations on the same stream are strictly ordered

### `aclrtSynchronizeStream`

```c
aclError aclrtSynchronizeStream(aclrtStream stream);
```

Blocks the calling thread until all operations on the stream complete.

- **Performance trap**: Calling after every async operation serializes the pipeline
- **Best practice**: Call once after queuing a batch of work on the stream

### `aclrtSynchronizeDevice`

```c
aclError aclrtSynchronizeDevice();
```

Blocks until all streams and operations on the current device complete. Heavy-weight — use sparingly.

## Model Inference

### `aclmdlLoadFromFile`

```c
aclError aclmdlLoadFromFile(const char *modelPath, uint32_t *modelId);
```

Loads an OM model from file system into device memory.

- `modelPath` must point to a `.om` file
- Returns a `modelId` used for all subsequent inference operations
- Must be called after `aclrtSetDevice`
- Memory is allocated on the device; model stays resident until `aclmdlUnload`

### `aclmdlLoadFromMem`

```c
aclError aclmdlLoadFromMem(void *model, size_t modelSize, uint32_t *modelId);
```

Loads from a memory buffer (e.g., embedded binary, encrypted model). Same semantics as `aclmdlLoadFromFile`.

### `aclmdlGetInputSizeByName` / `aclmdlGetOutputSizeByName`

```c
aclError aclmdlGetInputSizeByName(uint32_t modelId, const char *name, size_t *inputSize);
aclError aclmdlGetOutputSizeByName(uint32_t modelId, const char *name, size_t *outputSize);
```

Get buffer sizes for a named I/O tensor. Useful for allocating memory before inference.

### `aclmdlGetInputDimByName` / `aclmdlGetOutputDimByName`

```c
typedef struct {
    uint32_t dimCount;
    int64_t dims[ACL_MAX_DIM_CNT];
} aclmdlIODims;

aclError aclmdlGetInputDimByName(uint32_t modelId, const char *name, aclmdlIODims *dims);
aclError aclmdlGetOutputDimByName(uint32_t modelId, const char *name, aclmdlIODims *dims);
```

Get tensor dimensions. For dynamic-shape models, returns the max dimensions.

### `aclmdlCreateDataset` / `aclmdlDestroyDataset`

```c
aclmdlDataset *aclmdlCreateDataset();
aclError aclmdlDestroyDataset(aclmdlDataset *dataset);
```

A dataset is a container for multiple `aclDataBuffer` entries (one per model input or output).

- Create one dataset for inputs, one for outputs
- Add buffers with `aclmdlAddDatasetBuffer`
- Destroy after use to free container resources (does NOT free the underlying data buffers)

### `aclCreateDataBuffer` / `aclDestroyDataBuffer`

```c
aclDataBuffer *aclCreateDataBuffer(void *data, size_t size);
aclError aclDestroyDataBuffer(aclDataBuffer *dataBuffer);
```

Wraps a raw pointer + size into a data buffer for use with datasets.

- `data` points to the tensor data (device or host memory, depending on run mode)
- `size` is the tensor buffer size in bytes
- Destroying the buffer does NOT free `data`

### `aclmdlAddDatasetBuffer`

```c
aclError aclmdlAddDatasetBuffer(aclmdlDataset *dataset, aclDataBuffer *dataBuffer);
```

Adds a data buffer to a dataset. The index order must match the model's I/O tensor order.

### `aclmdlExecute`

```c
aclError aclmdlExecute(uint32_t modelId, const aclmdlDataset *input, aclmdlDataset *output);
```

Synchronous model inference. Blocks until complete.

- `modelId` from `aclmdlLoadFromFile`
- `input` and `output` are Dataset objects with properly prepared buffers
- Returns `ACL_SUCCESS` when inference completes

### `aclmdlExecuteAsync`

```c
aclError aclmdlExecuteAsync(uint32_t modelId, const aclmdlDataset *input,
                            aclmdlDataset *output, aclrtStream stream);
```

Asynchronous model inference. Returns immediately; completion is ordered on the stream.

- Must synchronize the stream (`aclrtSynchronizeStream`) before accessing output
- The input buffers must remain valid until the stream synchronizes
- Combine with double-buffering for pipeline parallelism

### `aclmdlUnload`

```c
aclError aclmdlUnload(uint32_t modelId);
```

Unloads the model from device memory. Frees associated resources.

### `aclmdlSetInputAIPP` (Dynamic AIPP)

```c
aclError aclmdlSetInputAIPP(uint32_t modelId, aclmdlDataset *input,
                            size_t index, const aclmdlAIPP *aippParams);
```

Sets AIPP parameters at runtime for models built with dynamic AIPP mode.

- `index`: input tensor index
- `aippParams`: `tagAippDynamicBatchPara` struct with crop, resize, padding, CSC parameters
- Only valid when the OM was converted with `aipp_mode: dynamic`

## Additional ACL APIs

### `aclmdlSetDynamicBatchSize`

```c
aclError aclmdlSetDynamicBatchSize(uint32_t modelId, aclmdlDataset *dataset,
                                   size_t index, uint64_t batchSize);
```

Set batch size for models converted with `--dynamic_batch_size`.

### `aclmdlSetDynamicHWSize`

```c
aclError aclError aclmdlSetDynamicHWSize(uint32_t modelId, aclmdlDataset *dataset,
                                         size_t index, uint64_t height, uint64_t width);
```

Set input resolution for models converted with `--dynamic_image_size`.

## Error Handling

All AscendCL APIs return `aclError`:

```c
typedef enum {
    ACL_SUCCESS = 0,
    ACL_ERROR_INVALID_PARAM = 100000,
    ACL_ERROR_UNSUPPORTED = 100001,
    ACL_ERROR_BAD_ALLOC = 100002,
    ACL_ERROR_REPEAT_INITIALIZE = 100003,
    ACL_ERROR_READ_MODEL_FAILURE = 100005,
    // ... see CANN documentation for full list
} aclError;
```

Always check return values. Use `aclGetRecentErrMsg()` for detailed error description:

```c
const char *aclGetRecentErrMsg();
```

## Typical Calling Sequence

```
aclInit(NULL)
aclrtSetDevice(0)

// Model setup
aclmdlLoadFromFile("model.om", &modelId)
input_dataset = aclmdlCreateDataset()
output_dataset = aclmdlCreateDataset()

// Allocate buffers
aclrtMalloc(&input_buf, input_size, ACL_MEM_MALLOC_HUGE_FIRST)
aclrtMalloc(&output_buf, output_size, ACL_MEM_MALLOC_HUGE_FIRST)

// Bind buffers
input_buffer = aclCreateDataBuffer(input_buf, input_size)
aclmdlAddDatasetBuffer(input_dataset, input_buffer)
// ... repeat for output

// Inference loop
while (has_data) {
    aclrtMemcpy(input_buf, ..., ACL_MEMCPY_HOST_TO_DEVICE)
    aclmdlExecute(modelId, input_dataset, output_dataset)
    aclrtMemcpy(host_output, output_buf, ..., ACL_MEMCPY_DEVICE_TO_HOST)
}

// Cleanup
aclDestroyDataBuffer(input_buffer)
// ... other buffers
aclmdlDestroyDataset(input_dataset)
aclmdlDestroyDataset(output_dataset)
aclrtFree(input_buf)
aclrtFree(output_buf)
aclmdlUnload(modelId)
aclrtResetDevice(0)
aclFinalize()
```
