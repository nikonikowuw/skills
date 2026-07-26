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
int rknn_init(rknn_context *ctx, void *model, size_t size, uint32_t flag, rknn_init_extend *extend);
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

### `rknn_destroy`

```c
int rknn_destroy(rknn_context ctx);
```

Destroy the runtime context and free all associated resources.

---

## Query

### `rknn_query`

```c
int rknn_query(rknn_context ctx, rknn_query_cmd cmd, void *info, size_t info_size);
```

Query model and runtime information.

| `cmd` | `info` struct | Description |
|---|---|---|
| `RKNN_QUERY_IN_OUT_NUM` | `rknn_input_output_num` | Number of input / output tensors |
| `RKNN_QUERY_INPUT_ATTR` | `rknn_tensor_attr` | Attributes of a specific input tensor |
| `RKNN_QUERY_OUTPUT_ATTR` | `rknn_tensor_attr` | Attributes of a specific output tensor |
| `RKNN_QUERY_PERF_DETAIL` | `rknn_perf_detail` | Performance breakdown per layer |
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
    uint32_t w_stride;        // width stride (for zero-copy)
    uint32_t h_stride;        // height stride (for zero-copy)
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
- `attr`: tensor attributes (index, w_stride, h_stride, etc.). Query via `rknn_query` first.

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
fseek(fp, 0, SEEK_END);
size_t model_size = ftell(fp);
rewind(fp);
void *model = malloc(model_size);
fread(model, 1, model_size, fp);
fclose(fp);

// 2. Init
rknn_context ctx;
rknn_init(&ctx, model, model_size, 0, NULL);
free(model);

// 3. Query input/output
rknn_input_output_num io_num;
rknn_query(ctx, RKNN_QUERY_IN_OUT_NUM, &io_num, sizeof(io_num));
rknn_tensor_attr input_attrs[io_num.n_input];
// ... query and set attr.index

// 4. Set input
rknn_input inputs[1];
inputs[0].index = 0;
inputs[0].buf = image_data;
inputs[0].size = image_size;
inputs[0].pass_through = 0;
inputs[0].type = RKNN_TENSOR_UINT8;
inputs[0].fmt = RKNN_TENSOR_NHWC;
rknn_inputs_set(ctx, 1, inputs);

// 5. Run
rknn_run(ctx, NULL);

// 6. Get output
rknn_output outputs[1];
outputs[0].want_float = 1;
rknn_outputs_get(ctx, 1, outputs, NULL);

// 7. Process
process_result(outputs[0].buf, outputs[0].size);

// 8. Release
rknn_outputs_release(ctx, 1, outputs);
rknn_destroy(ctx);
```

### Zero-copy path (DMA-BUF import)

```c
// ... init ...

// 1. Query I/O attributes BEFORE touching memory
rknn_tensor_attr input_attr;
memset(&input_attr, 0, sizeof(input_attr));
input_attr.index = 0;
rknn_query(ctx, RKNN_QUERY_INPUT_ATTR, &input_attr, sizeof(input_attr));

rknn_tensor_attr output_attr;
memset(&output_attr, 0, sizeof(output_attr));
output_attr.index = 0;
rknn_query(ctx, RKNN_QUERY_OUTPUT_ATTR, &output_attr, sizeof(output_attr));

// 2. Make RGA produce the queried input layout, writing into a DMA-BUF
uint32_t dst_w_stride = input_attr.w_stride ? input_attr.w_stride : model_width;
uint32_t dst_h_stride = input_attr.h_stride ? input_attr.h_stride : model_height;
// Pass dst_w_stride/dst_h_stride to RGA wrapbuffer_fd/wrapbuffer_handle.
int rga_fd = get_rga_output_fd();

// 3. Import the fd as NPU input memory (virt_addr = CPU mapping, offset usually 0)
rknn_tensor_mem *input_mem = rknn_create_mem_from_fd(ctx, rga_fd, rga_virt_addr, input_size, 0);

// 4. Allocate output memory (size rules: see memory-alignment.md)
rknn_tensor_mem *output_mem = rknn_create_mem(ctx, output_alloc_size);

// 5. Bind BOTH input and output before running
rknn_set_io_mem(ctx, input_mem, &input_attr);
rknn_set_io_mem(ctx, output_mem, &output_attr);

// 6. Single run — NPU reads input_mem and writes output_mem directly
rknn_run(ctx, NULL);

// 7. Read only what you need from output_mem->virt_addr
//    (mind cache flags — see rknn_mem_sync in known-crash-patterns.md)

rknn_destroy_mem(ctx, input_mem);
rknn_destroy_mem(ctx, output_mem);
rknn_destroy(ctx);
```
