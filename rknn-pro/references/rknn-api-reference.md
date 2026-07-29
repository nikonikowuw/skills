# RKNN Runtime API Reference

Detailed parameter descriptions, calling sequences, and constraints for the Rockchip RKNN Runtime (C API).

## Contents

- [Initialization and Lifecycle](#initialization-and-lifecycle)
- [Query](#query)
- [Inference](#inference)
- [Zero-Copy Memory Management](#zero-copy-memory-management)
- [Multi-Core NPU](#multi-core-npu)
- [Typical Calling Sequence](#typical-calling-sequence)

## Initialization and Lifecycle

### `rknn_init`

```c
int rknn_init(rknn_context *ctx, void *model, uint32_t size, uint32_t flag, rknn_init_extend *extend);
```

Initialize RKNN runtime context from a `.rknn` model blob.

| Parameter | Description |
|---|---|
| `ctx` | Output: pointer to context handle |
| `model` | Pointer to loaded `.rknn` model data |
| `size` | Model data size in bytes |
| `flag` | Initialization flags (see below) |
| `extend` | Extended init info (can be NULL) |

**Common flags (names from `rknn_api.h`; use the header's constants, do not hard-code values):**

| Flag | Purpose |
|---|---|
| `0` | Normal init |
| `RKNN_FLAG_PRIOR_HIGH` / `RKNN_FLAG_PRIOR_MEDIUM` / `RKNN_FLAG_PRIOR_LOW` | Context scheduling priority |
| `RKNN_FLAG_ASYNC_MASK` | Previous-frame output mode in Runtime releases whose header documents that behavior; it is not a generic nonblocking `rknn_run` flag |
| `RKNN_FLAG_COLLECT_PERF_MASK` | Collect performance data |

**Returns:** 0 on success, negative on error.

In the current official header, `RKNN_FLAG_ASYNC_MASK` makes `rknn_outputs_get` retrieve the previous
frame so a single-threaded loop waits less. The same header says multithreaded mode does not need the
flag. Re-check the selected target header because this behavior is version-bound; do not use the flag
as proof that `rknn_run` is nonblocking or that one context is safe for concurrent calls.

The model length is `uint32_t` in the current API. Validate file length, allocation, and complete
read before initialization; reject a `size_t` value above `UINT32_MAX` rather than narrowing it.

### `rknn_dup_context`

```c
int rknn_dup_context(rknn_context* context_in, rknn_context* context_out);
```

Both parameters are pointers. Check the return before using `context_out`. The current header does
not state a weight-sharing or memory-saving guarantee, so measure memory and validate lifecycle
behavior on the deployed Runtime instead of making duplication mandatory.

### `rknn_destroy`

```c
int rknn_destroy(rknn_context ctx);
```

Destroy the runtime context and free all associated resources.

---

## Query

### `rknn_query`

```c
int rknn_query(rknn_context ctx, rknn_query_cmd cmd, void *info, uint32_t info_size);
```

Query model and runtime information.

| `cmd` | `info` struct | Description |
|---|---|---|
| `RKNN_QUERY_IN_OUT_NUM` | `rknn_input_output_num` | Number of input / output tensors |
| `RKNN_QUERY_INPUT_ATTR` | `rknn_tensor_attr` | Attributes of a specific input tensor |
| `RKNN_QUERY_OUTPUT_ATTR` | `rknn_tensor_attr` | Attributes of a specific output tensor |
| `RKNN_QUERY_PERF_DETAIL` | `rknn_perf_detail` | Runtime-generated performance report string; requires the collect-performance init flag and a completed output retrieval in the current header |
| `RKNN_QUERY_MEM_SIZE` | `rknn_mem_size` | Memory usage of model |

**Illustrative tensor attributes (`rknn_tensor_attr`; exact fields are header-version dependent):**

```c
typedef struct {
    uint32_t index;           // tensor index
    uint32_t n_dims;          // number of dimensions
    uint32_t dims[16];        // dimensions
    char name[256];           // tensor name
    uint32_t n_elems;         // number of elements
    uint32_t size;            // logical/legacy total size in bytes
    uint32_t size_with_stride;// stride-aware total size on newer API 2.x headers; feature-detect it
    rknn_tensor_fmt fmt;      // data format (NHWC/NCHW/...)
    rknn_tensor_type type;    // data type (INT8/INT16/FP16/FP32/UINT8)
    uint32_t w_stride;        // read-only in the current header; 0 means logical width
    uint32_t h_stride;        // write-only in the current header; 0 means logical height
    rknn_tensor_qnt_type qnt_type; // quantization type
    int8_t fl;                // fractional length (for DFP quantization)
    int32_t zp;               // zero point (signed — asymmetric INT8 zero points can be negative)
    float scale;              // scale (for affine/asymmetric quantization)
} rknn_tensor_attr;
```

The exact structure differs across RKNN header releases. Do not copy this illustrative layout into
compatibility code. Use CMake `check_struct_has_member` against the header selected by the target,
prefer `size_with_stride` when present, and guard direct access to optional `size` and
`size_with_stride` members independently. See
[memory-alignment.md](memory-alignment.md) for the complete build and allocation pattern.

`rknn_perf_detail` exposes `perf_data` and `data_len` in the pinned header. Treat `perf_data` as a
version-specific report string; there is no structured per-layer member to dereference.

---

## Inference

### `rknn_inputs_set`

```c
int rknn_inputs_set(rknn_context ctx, uint32_t n_inputs, rknn_input inputs[]);
```

Set input tensors for inference.

```c
typedef struct {
    uint32_t index;            // input tensor index
    void *buf;                 // input buffer pointer (host memory)
    uint32_t size;             // input buffer size
    uint8_t pass_through;      // 0: do pre-process (quantize), 1: pass raw data
    rknn_tensor_type type;     // data type of the buffer
    rknn_tensor_fmt fmt;       // data format of the buffer
} rknn_input;
```

- `pass_through=0`: Runtime converts the host tensor to the model's native input requirements. That
  can include layout/type conversion or quantization and can add measurable CPU/runtime overhead.
- `pass_through=1`: Data must already be in the expected format (for zero-copy or pre-quantized paths).
- Multiple inputs: set `index` for each input tensor.

### `rknn_run`

```c
int rknn_run(rknn_context ctx, rknn_run_extend *extend);
```

Submit inference in the classic Runtime flow. Completion and output timing depend on the selected
Runtime API and initialization flags; follow the exact header and pair newer submit/wait APIs when
the installed release exposes them.

### `rknn_outputs_get`

```c
int rknn_outputs_get(rknn_context ctx, uint32_t n_outputs, rknn_output outputs[], rknn_output_extend *extend);
```

Get inference outputs.

```c
typedef struct {
    uint8_t want_float;        // 1: dequantize to float, 0: keep quantized
    uint8_t is_prealloc;       // 1: caller provides buf, 0: runtime allocates
    uint32_t index;            // output tensor index
    void *buf;                 // output data (runtime- or caller-allocated per is_prealloc)
    uint32_t size;             // output data size in bytes
} rknn_output;
```

- `want_float=1`: Runtime converts the output to float for the caller. For quantized outputs this
  includes dequantization and may add host-side conversion overhead. It does not describe the NPU
  graph's execution precision. Measure before preferring `want_float=0`.
- `want_float=0`: Get the native/raw output and apply the queried quantization contract when needed.
  It often avoids conversion work, but choose it from correctness and end-to-end measurements rather
  than treating it as an unconditional production rule.

### `rknn_outputs_release`

```c
int rknn_outputs_release(rknn_context ctx, uint32_t n_outputs, rknn_output outputs[]);
```

Release output buffers obtained from `rknn_outputs_get`. Must call to avoid memory leak.

---

## Zero-Copy Memory Management

### `rknn_create_mem`

```c
rknn_tensor_mem *rknn_create_mem(rknn_context ctx, uint32_t size);
```

Create internal NPU-accessible memory. Returns handle for use with `rknn_set_io_mem`.

- Runtime allocates NPU-accessible tensor memory. The backing allocator and physical-contiguity
  guarantees are BSP/runtime details; use the returned handle and target API contract rather than
  assuming a particular heap implementation.
- Use for input/output buffers in zero-copy paths.
- For every tensor allocation, compare the compatibility-selected size field, `size`, and
  `size_with_stride` when available. For an RGA-written input, also include the bytes implied by
  the actual destination strides; then apply the target allocator's page/alignment requirement.
- Perform those calculations in checked `size_t`/`uint64_t`, then reject values above `UINT32_MAX`
  before calling this API. Newer headers may expose `rknn_create_mem2` with a 64-bit size; feature
  detect it and follow its allocation-flag contract rather than silently switching APIs.

### `rknn_create_mem_from_fd`

```c
rknn_tensor_mem *rknn_create_mem_from_fd(rknn_context ctx, int32_t fd, void *virt_addr, uint32_t size, int32_t offset);
```

Import a DMA-BUF file descriptor as NPU-accessible memory. This is the **key zero-copy API** — RGA output
or MPP decode buffer can be imported directly without copying.

| Parameter | Description |
|---|---|
| `fd` | DMA-BUF file descriptor |
| `virt_addr` | CPU mapping of the buffer. Pass the mapped address when CPU code will touch the data; whether NULL is accepted is release-dependent — follow the installed header's comment |
| `size` | Buffer size in bytes |
| `offset` | Byte offset of the tensor data inside the DMA-BUF (usually 0). This is **not** an mmap protection flag — passing `PROT_READ` here silently shifts the import by 1 byte |

Returns NULL on failure.

### `rknn_set_io_mem`

```c
int rknn_set_io_mem(rknn_context ctx, rknn_tensor_mem *mem, rknn_tensor_attr *attr);
```

Bind pre-allocated NPU memory to an input or output tensor. Used instead of `rknn_inputs_set` for zero-copy paths.

- `mem`: handle from `rknn_create_mem` or `rknn_create_mem_from_fd`.
- `attr`: tensor attributes queried first. In the current header, preserve read-only `w_stride` and
  make the backing buffer satisfy it; set write-only `h_stride` from the real physical layout.

### `rknn_destroy_mem`

```c
int rknn_destroy_mem(rknn_context ctx, rknn_tensor_mem *mem);
```

Destroy NPU memory. Must call for every `rknn_create_mem`/`rknn_create_mem_from_fd`.

---

## Multi-Core NPU

### `rknn_set_core_mask`

```c
int rknn_set_core_mask(rknn_context ctx, rknn_core_mask core_mask);
```

Set a core mask on a multi-core platform. The enum in a shared header does not prove that every mask
is available on every SoC/runtime; validate the selected target and check the return code.

| `core_mask` | Description |
|---|---|
| `RKNN_NPU_CORE_AUTO` | Auto-balance across cores (default) |
| `RKNN_NPU_CORE_0` | Use only NPU core 0 |
| `RKNN_NPU_CORE_1` | Use only NPU core 1 |
| `RKNN_NPU_CORE_2` | Use only NPU core 2 when supported |
| `RKNN_NPU_CORE_0_1` | Use both cores |
| `RKNN_NPU_CORE_0_1_2` | Use cores 0, 1, and 2 when supported |
| `RKNN_NPU_CORE_ALL` | Let Runtime select available cores according to the platform |

---

## Typical Calling Sequence

### Standard path (copy-based)

```c
// 1. Load model
FILE *fp = fopen("model.rknn", "rb");
if (fp == NULL) return -1;
if (fseek(fp, 0, SEEK_END) != 0) {
    fclose(fp);
    return -1;
}
long file_size = ftell(fp);
if (file_size <= 0 || (unsigned long)file_size > UINT32_MAX ||
    fseek(fp, 0, SEEK_SET) != 0) {
    fclose(fp);
    return -1;
}
uint32_t model_size = (uint32_t)file_size;
void *model = malloc(model_size);
if (model == NULL || fread(model, 1, model_size, fp) != model_size) {
    free(model);
    fclose(fp);
    return -1;
}
fclose(fp);

// 2. Init
rknn_context ctx = 0;
int ret = rknn_init(&ctx, model, model_size, 0, NULL);
free(model);
if (ret != RKNN_SUCC) return ret;

// 3. Query input/output
rknn_input_output_num io_num = {0};
ret = rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &io_num, sizeof(io_num));
if (ret != RKNN_SUCC) goto destroy_ctx;
if (io_num.n_input != 1 || io_num.n_output != 1) {
    ret = RKNN_ERR_PARAM_INVALID;
    goto destroy_ctx;
}

// 4. Set input
rknn_input inputs[1] = {0};
inputs[0].index = 0;
inputs[0].buf = image_data;
inputs[0].size = image_size;
inputs[0].pass_through = 0;
inputs[0].type = RKNN_TENSOR_UINT8;
inputs[0].fmt = RKNN_TENSOR_NHWC;
ret = rknn_inputs_set(ctx, 1, inputs);
if (ret != RKNN_SUCC) goto destroy_ctx;

// 5. Run
ret = rknn_run(ctx, NULL);
if (ret != RKNN_SUCC) goto destroy_ctx;

// 6. Get output
rknn_output outputs[1] = {0};
outputs[0].index = 0;
outputs[0].want_float = 1;
ret = rknn_outputs_get(ctx, 1, outputs, NULL);
if (ret != RKNN_SUCC) goto destroy_ctx;

// 7. Process
process_result(outputs[0].buf, outputs[0].size);

// 8. Release
ret = rknn_outputs_release(ctx, 1, outputs);

destroy_ctx:
{
    int destroy_ret = rknn_destroy(ctx);
    return ret != RKNN_SUCC ? ret : destroy_ret;
}
```

`image_size` must also be validated as representable by `rknn_input.size` before this sequence.
Real code should use structured cleanup/RAII rather than copying the `goto` outline into C++.

### Zero-copy path (DMA-BUF import)

```c
// ... init ...

// 1. Query I/O attributes BEFORE touching memory
rknn_tensor_attr input_attr;
memset(&input_attr, 0, sizeof(input_attr));
input_attr.index = 0;
if (rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &input_attr, sizeof(input_attr)) != RKNN_SUCC) {
    return -1;
}

rknn_tensor_attr output_attr;
memset(&output_attr, 0, sizeof(output_attr));
output_attr.index = 0;
if (rknn_query(ctx, RKNN_QUERY_OUTPUT_ATTR, &output_attr, sizeof(output_attr)) != RKNN_SUCC) {
    return -1;
}

// 2. Make RGA produce the queried input layout, writing into a DMA-BUF
uint32_t dst_w_stride = input_attr.w_stride ? input_attr.w_stride : model_width;
uint32_t dst_h_stride = rga_destination_h_stride;  // from the real allocation/layout
// Pass dst_w_stride/dst_h_stride to RGA wrapbuffer_fd/wrapbuffer_handle.
int rga_fd = get_rga_output_fd();
input_attr.h_stride = dst_h_stride;  // write-only bind input in the current header

// 3. Import the fd as NPU input memory (virt_addr = CPU mapping, offset usually 0)
rknn_tensor_mem *input_mem = rknn_create_mem_from_fd(
    ctx, rga_fd, rga_virt_addr, CheckedSizeToUint32(input_size), 0);
if (input_mem == NULL) return -1;

// 4. Allocate output memory (size rules: see memory-alignment.md)
rknn_tensor_mem *output_mem = rknn_create_mem(ctx, CheckedSizeToUint32(output_alloc_size));
if (output_mem == NULL) {
    rknn_destroy_mem(ctx, input_mem);
    return -1;
}

// 5. Bind BOTH input and output before running
if (rknn_set_io_mem(ctx, input_mem, &input_attr) != RKNN_SUCC ||
    rknn_set_io_mem(ctx, output_mem, &output_attr) != RKNN_SUCC) {
    rknn_destroy_mem(ctx, input_mem);
    rknn_destroy_mem(ctx, output_mem);
    return -1;
}

// 6. Single run — NPU reads input_mem and writes output_mem directly
if (rknn_run(ctx, NULL) != RKNN_SUCC) {
    rknn_destroy_mem(ctx, input_mem);
    rknn_destroy_mem(ctx, output_mem);
    return -1;
}

// 7. Read only what you need from output_mem->virt_addr
//    (mind cache flags — see rknn_mem_sync in known-crash-patterns.md)

rknn_destroy_mem(ctx, input_mem);
rknn_destroy_mem(ctx, output_mem);
rknn_destroy(ctx);
```

`CheckedSizeToUint32` denotes a project helper that rejects values above `UINT32_MAX`. This outline
omits application-specific cache synchronization and RGA completion, both of which must be proven
before the NPU reads the imported memory.

## Source Snapshot

Validated 2026-07-28 against the official Runtime header at Toolkit2 commit
[`59a913d172e7f5ff03c9076e2ec7b1b1288ffd08`](https://github.com/airockchip/rknn-toolkit2/blob/59a913d172e7f5ff03c9076e2ec7b1b1288ffd08/rknpu2/runtime/Linux/librknn_api/include/rknn_api.h).
Use the deployed target header and Runtime as the final contract.
