---
toolkit2_version: v2.3.2
---

# Model Conversion Guide (Framework → ONNX → RKNN)

Full model conversion pipeline for Rockchip NPU: from PyTorch or TensorFlow to ONNX, then ONNX to RKNN
via rknn-toolkit2. Also covers direct framework-to-RKNN paths.

> Keep three concepts separate: source-model dtype, host-side Runtime tensor dtype, and NPU graph
> execution precision. Quantized builds commonly use INT8 and non-quantized builds commonly use
> FP16 on these targets. `RKNN_TENSOR_FLOAT32` remains a valid host input type when the Runtime is
> asked to convert it; it does not imply FP32 execution inside the NPU.

---

## 1. PyTorch → ONNX

### Basic export

```python
import torch

model = torch.load("model.pt")
model.eval()

dummy_input = torch.randn(1, 3, 224, 224)

torch.onnx.export(
    model,
    dummy_input,
    "model.onnx",
    opset_version=13,       # conservative default; verify against the installed Toolkit2
    input_names=["input"],
    output_names=["output"],
    # Export static shapes unless the deployment explicitly requires a
    # Toolkit2-supported dynamic_input shape set.
)
```

### Key parameters

| Parameter | Recommendation |
|---|---|
| `opset_version` | Use 13 as a conservative default. Modern Toolkit2 versions support up to opset 19, but verify against your exact installed release. |
| Dynamic shape | Prefer static export. For a required shape set, follow the bundled Toolkit2 `functions/dynamic_shape` example and configure `dynamic_input`; arbitrary ONNX dynamic axes do not guarantee RKNN support. |
| `input_names` / `output_names` | Match names used during RKNN conversion |

### Common issues

- **Dynamic control flow**: Use `torch.jit.script()` first if model has data-dependent branches.
- **Unsupported ONNX ops**: Check rknn-toolkit2 supported operator list.
- **Verification**:
  ```python
  import onnx
  onnx.checker.check_model("model.onnx")
  ```

---

## 2. TensorFlow → ONNX

### Using tf2onnx

```bash
pip install tf2onnx onnx

# From SavedModel
python -m tf2onnx.convert \
    --saved-model ./saved_model \
    --output model.onnx \
    --opset 13

# From frozen .pb
python -m tf2onnx.convert \
    --input model.pb --inputs input:0 --outputs output:0 \
    --output model.onnx --opset 13
```

### NHWC → NCHW

TensorFlow defaults to NHWC. Rockchip RKNN commonly expects NHWC (TensorFlow-compatible).
If the model was trained in NCHW, use `--inputs-as-nchw` in tf2onnx or transpose in preprocessing.

---

## 3. ONNX → RKNN (rknn-toolkit2)

### Required conversion evidence gate

Do not design or approve preprocessing, Runtime input handling, zero-copy tensor layout,
quantization-sensitive postprocessing, or deployment configuration until the conversion provenance
has been checked. Create `.agents/rknn-model-context.md` from
[model-conversion-manifest.md](model-conversion-manifest.md) and link these artifacts by hash:

1. Source ONNX plus its export/training preprocessing contract.
2. Exact conversion script/config, Toolkit2 version, target, and verbose log/build report.
3. Calibration dataset manifest and preprocessing when quantization was requested.
4. Exported RKNN artifact and Runtime-queried input/output attributes.

When ONNX is available, run:

```bash
python3 <skill-root>/scripts/inspect-onnx-model.py model.onnx -o onnx-inspection.md
```

The inspector reports ONNX facts and possible preprocessing nodes. It cannot recover Toolkit2
`mean_values`/`std_values` from an RKNN artifact, prove the training-time input contract, or confirm
the final RKNN graph precision.

If the evidence gate is blocked, the development report must name the missing ONNX contract fields
(hash, IR/opset, producer/metadata, inputs/outputs, shapes, dtypes, dynamic dimensions, and candidate
input preprocessing), the missing conversion/quantization evidence, the decisions that remain
blocked, and unrelated source work that can continue without assuming those facts.

### Basic Python conversion script

```python
from rknn.api import RKNN

rknn = RKNN(verbose=True)

# target_platform MUST be configured early in modern workflows!
rknn.config(
    mean_values=[[123.675, 116.28, 103.53]],   # per-channel mean
    std_values=[[58.395, 58.395, 58.395]],      # per-channel std
    target_platform="rk3568",                    # or rk3576 / rk3588
    quantized_dtype="asymmetric_quantized-8",    # quantization type
    quantized_algorithm="normal",                # or "mmse" for better accuracy
)

# Load ONNX model
ret = rknn.load_onnx(model="model.onnx")
assert ret == 0, "load_onnx failed"

# Build (quantize and convert)
ret = rknn.build(do_quantization=True, dataset="./dataset.txt")
assert ret == 0, "build failed"

# Export RKNN
ret = rknn.export_rknn("./model.rknn")
assert ret == 0, "export failed"

rknn.release()
```

### Pre-Processing Configuration

*(See the `rknn.config()` block in the script above. Multi-batch is a `build()` option, not a `config()` option: `rknn.build(..., rknn_batch_size=4)`)*

### Normalization and Runtime Input Type

Normalization may occur in three different places:

| Location | How to confirm it | What it does not prove |
|---|---|---|
| ONNX graph | Inspect input-reachable nodes/constants and confirm against export/training code | Toolkit2 conversion settings or final Runtime input contract |
| Toolkit2 conversion | Preserve the exact `rknn.config(mean_values=..., std_values=...)` call and verbose log | That the application is feeding the intended raw range/order |
| Application/RGA side | Trace the real resize, color, layout, cast, scale, subtract, and divide operations | Internal RKNN graph precision |

Classify each location as `confirmed-present`, `confirmed-absent`, or `unknown`. The end-to-end
pipeline must contain exactly the intended normalization transform. It can be represented by one
location or deliberately split into documented stages, but each arithmetic operation must occur
once and reproduce the training contract. An unknown is not an absence.

`mean_values` and `std_values` can configure Toolkit2 input preprocessing. Raw UINT8 is a common
efficient host contract in that case, but it is not safe to derive the entire Runtime call from this
fact alone. Query converted-model tensor attributes, verify the installed Runtime's `pass_through`
semantics, and run a known-input parity test. ONNX input dtype alone cannot reveal whether Toolkit2
added preprocessing after loading the ONNX.

**Common mistake — double normalization:**

```c
// ❌ WRONG: CPU normalizes + model also normalizes = garbage output
float normalized[640 * 480 * 3];
for (int i = 0; i < size; i++)
    normalized[i] = (image[i] / 255.0f - mean) / std;  // normalization on CPU

rknn_input input;
input.buf = normalized;           // already normalized
input.type = RKNN_TENSOR_FLOAT32; // but model will normalize again!

// ✅ CORRECT: feed raw uint8, let model handle normalization
rknn_input input;
input.buf = image;                // raw [0,255] uint8 pixels
input.type = RKNN_TENSOR_UINT8;   // conversion contract accepts raw uint8
input.fmt = RKNN_TENSOR_NHWC;
input.pass_through = 0;           // Runtime applies its validated input conversion
```

The corrected example is valid only when the preserved conversion config, queried input attributes,
and parity test establish that exact contract. `pass_through=0` does not prove that the graph is
INT8; it controls Runtime-side input processing.

**Why this matters for zero-copy:**
- If the model expects [0,255] uint8, you can feed the raw image memory to it. **However**, raw V4L2/MPP decoder output is usually NV12/NV21, so you MUST run it through RGA for CSC (Color Space Conversion) and format matching (to RGB/BGR NHWC) before zero-copy RKNN ingestion. You cannot feed raw NV12 directly as `RKNN_TENSOR_UINT8` if the model expects RGB/BGR!
- If the model expects application-normalized float32, account for the full-frame transform and its copy/bandwidth cost. Revisit the conversion contract if input preprocessing can be represented correctly by Toolkit2.

**Check what your model expects:**
```python
# During conversion, inspect the model's expected input type
import onnx
m = onnx.load("model.onnx")
input_tensor = m.graph.input[0]
type_info = input_tensor.type.tensor_type
elem_type = type_info.elem_type  # 1=float32, 2=uint8, ...
```
An ONNX float32 input plus Toolkit2 `mean/std` commonly produces a raw-image host input workflow,
but do not turn that convention into proof. Confirm the exact config/log, query the RKNN input, and
compare ONNX Runtime and RKNN results for the same preprocessed sample.

### ⚠️ Channel order: RGB vs BGR

**Different models expect different channel orders.** Feeding RGB data to a BGR-trained
model (or vice versa) produces silently wrong results — colors are swapped.

| Training framework | Typical training format | Common practice |
|---|---|---|
| PyTorch / torchvision | **RGB** (C×H×W: 3,224,224) | Images loaded as RGB |
| TensorFlow / Keras | **RGB** (H×W×C: 224,224,3) | Images loaded as RGB |
| OpenCV (C++) | **BGR** (H×W×C: rows, cols, 3) | cv::imread returns BGR |
| Caffe | **BGR** | BVLC models expect BGR |
| Darknet (YOLO) | **RGB** | Darknet converts loaded images to RGB internally |
| ONNX Model Zoo | **RGB** | Most ONNX models are RGB |

**How to check the channel order for an ONNX model:**

```python
import onnx

m = onnx.load("model.onnx")

# Look at the mean_values in preprocessing info (if available)
# RGB models typically use means like [123.675, 116.28, 103.53] (R mean, G mean, B mean)
# BGR models typically use means like [103.53, 116.28, 123.675] (B mean, G mean, R mean)

# Or inspect the model's documentation / training script
# Or run a test: feed an image with known colors (red square) and check output
```

**In RKNN config, values must follow the already-confirmed input channel order:**

| `mean_values` example | Valid interpretation only when the model contract confirms |
|---|---|
| `[123.675, 116.28, 103.53]` | **RGB**, with R first |
| `[103.53, 116.28, 123.675]` | **BGR**, with B first |
| `[0, 0, 0]` | Channel order remains ambiguous |

These familiar value sequences are clues, not evidence of channel order. Confirm order from the
training/export preprocessing and a known-color parity input.

**In the pipeline — matching channel order:**

```
Source format → RGA conversion → Model expected format

NV12 (MPP decode) → RGA CSC → RGB888 → model expects RGB  ✅
NV12 (MPP decode) → RGA CSC → BGR888 → model expects BGR  ✅
NV12 (MPP decode) → RGA CSC → RGB888 → model expects BGR  ❌ colors swapped!
NV12 (MPP decode) → RGA CSC → BGR888 → model expects RGB  ❌ colors swapped!
```

**How to specify the channel order in RKNN config:**

If your model expects a different order than what the training framework outputs,
you can sometimes handle it during conversion:

```python
rknn.config(
    mean_values=[[123.675, 116.28, 103.53]],   # R, G, B means
    std_values=[[58.395, 58.395, 58.395]],
    target_platform="rk3568",
    quantized_dtype="asymmetric_quantized-8",
    # Note: RKNN does NOT have a direct "channel_order" parameter
    # Values follow the input order established by the training/export contract.
)
```

**If you cannot change the model, change the preprocessing:**

```c
// RGA CSC: NV12 → RGB888  (feed to RGB model)
// RGA CSC: NV12 → BGR888  (feed to BGR model)

// Or swap channels on CPU before RKNN input
if (model_expects_bgr && source_is_rgb) {
    for (int i = 0; i < width * height; i++) {
        uint8_t r = rgb[i * 3 + 0];
        uint8_t g = rgb[i * 3 + 1];
        uint8_t b = rgb[i * 3 + 2];
        // Swap R↔B
        bgr[i * 3 + 0] = b;
        bgr[i * 3 + 1] = g;
        bgr[i * 3 + 2] = r;
    }
}
// ⚠️ This is a full-frame CPU pass — breaks zero-copy.
// Better: chain RGA to output the correct order directly.
```

**Zero-copy implication:** RGA can output both RGB888 and BGR888 via CSC.
Use the correct RGA format to match the model — no CPU channel swap needed:

```c
// RGA output format choice depends on model:
rga_buffer_t dst = wrapbuffer_handle(dst_handle, w, h,
    (model_expects_rgb ? RK_FORMAT_RGB_888 : RK_FORMAT_BGR_888),  // ⚠️ choose here!
    w_stride, h_stride);
```

### Quantization Guide

| `do_quantization` request | Expected result | Required confirmation | Use case |
|---|---|---|---|
| `True` | Quantized graph, commonly INT8 with possible mixed precision | Successful build plus graph/layer precision report and exported RKNN hash | PTQ candidate |
| `False` | No PTQ requested; commonly a floating graph on target | Successful build plus graph/layer precision report | Accuracy baseline or precision-sensitive model |

**Modern v2.x Features:**
- **Automatic Mixed Precision (AMP):** You can provide an `amp_cfg` in `rknn.config()` to automatically fall back precision-sensitive layers (like softmax) to FP16 while keeping the rest as INT8.
- **W4A16 Quantization:** RK3576 supports advanced W4A16 quantization (`quantized_dtype="w4a16"`) which can significantly reduce memory bandwidth usage for large models like LLMs or heavy transformers, though check compatibility matrix for your specific Toolkit version.

Treat `do_quantization=True` as the requested build mode, not proof that the exported model is wholly
INT8. Confirm actual graph/layer precision from the build report, including mixed or excluded layers,
and link that report to the RKNN hash. Do not infer precision from the `.rknn` filename, ONNX input
dtype, Runtime input/output type, `pass_through`, `want_float`, or a host-side C buffer.

Dataset file (`dataset.txt`): one image path per line for calibration.

```text
./calib_images/img001.jpg
./calib_images/img002.jpg
./calib_images/img003.jpg
```

### Target Platforms

| Value | SoC |
|---|---|
| `rk3568` | RK3566 / RK3568 |
| `rk3576` | RK3576 |
| `rk3588` | RK3588 / RK3588S |

### Pre-Compiled Models

Some SDK generations support pre-compiled artifacts, but the build option and compatibility rules
are version-specific. Do not emit a `pre_compile` argument unless it exists in the installed Toolkit2
API. Treat `RKNN_ERR_INCOMPATILE_PRE_COMPILE_MODEL` as evidence that the artifact must be rebuilt for
the selected driver/runtime rather than as a generic model-format error.

---

## 4. Modern Dynamic Shape Workflow

Dynamic shapes are supported in modern versions but require explicit handling at every step. Do NOT rely on raw ONNX dynamic shapes to simply "work."

**Checklist:**
1. **Export ONNX with symbolic dims:** When calling `torch.onnx.export()`, define `dynamic_axes` for your inputs (e.g., `{ 'input': {0: 'batch', 2: 'height', 3: 'width'} }`).
2. **Configure Toolkit2:** You MUST provide a specific list of supported shape combinations in `rknn.config()` using the `dynamic_input` parameter. e.g., `dynamic_input=[[[1,3,224,224]], [[1,3,448,448]]]` (list of lists of lists — covering each input shape across all inputs).
3. **Verify in Simulator:** Call `rknn.init_runtime()` and `rknn.inference()` with differing input shapes to prove dynamic switching works on the host PC.
4. **C++ API Usage:** In the target C++ code, you CANNOT just pass different sized tensors to `rknn_inputs_set`. You MUST call `rknn_set_core_mask()` (if relevant) and `rknn_set_input_shape()` for the new shape *before* calling `rknn_inputs_set` and `rknn_run`.

---

## 5. Direct Framework → RKNN

rknn-toolkit2 also supports direct conversion without the ONNX intermediate:

```python
# PyTorch
rknn.load_pytorch(model="model.pt", input_size_list=[[1, 3, 224, 224]])

# TensorFlow
rknn.load_tensorflow(tf_pb="model.pb", inputs=["input"], outputs=["output"], input_size_list=[[1, 224, 224, 3]])

# TFLite
rknn.load_tflite(model="model.tflite")

# Caffe
rknn.load_caffe(model="model.prototxt", blobs="model.caffemodel")

# Darknet
rknn.load_darknet(model="model.cfg", weight="model.weights")
```

Direct conversion is simpler but the ONNX intermediate is recommended for:
- Debugging (check model structure at each stage).
- Compatibility (ONNX is the widest-supported intermediate format).
- Re-targeting (same ONNX for Ascend, GPU, etc.).

## NPU-Aware Model Optimization

### Problem: Unsupported or Host-Executed Operators

Not every model operator maps to the NPU. Depending on Toolkit2 version and operator, conversion may
fail, rewrite/fuse the graph, use a documented CPU/custom operator implementation, or require the
application to move that operation outside RKNN. Do not assume arbitrary unsupported operators are
transparently partitioned to the CPU.

```
Possible graph with an explicitly supported host/custom operator:

  [NPU conv] → [NPU relu] → [NPU→CPU] → [CPU: NMS] → [CPU→NPU] → [NPU ...]
                                    ^^^               ^^^
                               expensive copy!   expensive copy!
```

### Two-phase optimization strategy

| Phase | What | Goal |
|---|---|---|
| **Phase 1: Prove conversion** | Build with the exact Toolkit2/target and classify every warning or failure. | Establish what actually maps, is rewritten, or is rejected. |
| **Phase 2: Optimize** | Move unsuitable postprocessing out of the model or use a documented CPU/custom-op path when required. | Avoid accidental host work and extra transfers. |

### Step 1 — Identify which ops run on NPU vs CPU

**Method A: RKNN verbose build output**
```python
rknn = RKNN(verbose=True)
ret = rknn.load_onnx(model="model.onnx")
ret = rknn.build(do_quantization=True, dataset="./dataset.txt")
```
Search the output for:
- `running on NPU` — ops accelerated by NPU
- `running on CPU` — ops that fall back to CPU (these are candidates for removal)

**Method B: Runtime performance query**
```c
rknn_perf_detail perf;
rknn_query(ctx, RKNN_QUERY_PERF_DETAIL, &perf, sizeof(perf));
// Check perf.layer_detail for per-op timing and execution target
```

### Step 2 — Identify candidate ops for removal

Typical ops that RKNN NPU cannot accelerate (vary by SoC and RKNN version):

| Op | Typical location | CPU/NPU | C++ alternative |
|---|---|---|---|
| `NonMaxSuppression` | Detection output | ❌ CPU | Implement NMS in C++ after NPU output |
| `TopK` | Classification | ❌ CPU | Sort + select in C++ |
| `Sort` / `ArgSort` | Post-processing | ❌ CPU | Implement in C++ |
| `Gather` / `Scatter` (dynamic indices) | Various | ⚠️ Often CPU | Rewrite with fixed indices or C++ |
| `Where` / `NonZero` | Mask processing | ❌ CPU | Implement in C++ |
| `Reshape` (certain patterns) | Shape changes | ⚠️ May fall back | Check; often free if contiguous |
| `Expand` / `Tile` (large factors) | Data duplication | ⚠️ Sometimes CPU | Implement in C++ |
| Custom ONNX ops | Any | ❌ Always CPU | Implement in C++ or replace with supported ops |

> ⚠️ This list changes with RKNN version and target SoC.
> **Always verify** by inspecting the verbose build output, not by assumption.

### Step 3 — Split the model (remove layers from ONNX)

```python
import onnx

model = onnx.load("model.onnx")
graph = model.graph

# Find the node just before NMS
nms_node = None
output_name = None
for node in graph.node:
    if node.op_type == "NonMaxSuppression":
        nms_node = node
        # The input to NMS is the detection output we want to keep
        output_name = node.input[0]  # e.g., "detection_output"
        break

# Remove NMS and all nodes after it by extracting the sub-graph up to output_name.
# Signature: extract_model(input_path, output_path, input_names, output_names)
onnx.utils.extract_model(
    "model.onnx",           # input: the original model
    "model_trimmed.onnx",   # output: the trimmed model
    input_names=["input"],  # original model inputs
    output_names=[output_name]  # output before NMS
)
```

After trimming, reconvert to RKNN:
```python
rknn.load_onnx(model="model_trimmed.onnx")
rknn.build(do_quantization=True, dataset="./dataset.txt")
rknn.export_rknn("./model_trimmed.rknn")
```

### Step 4 — Implement removed layers in C++

```c
// After rknn_run, the NPU output is the raw detection tensor
// (without NMS). Implement NMS in C++ on the CPU side.

void rknn_run_and_postprocess(rknn_context ctx) {
    rknn_output outputs[1];
    outputs[0].want_float = 0;  // keep INT8
    rknn_outputs_get(ctx, 1, outputs, NULL);

    // Manual dequantize (only for the boxes we need to sort)
    float scale = output_attr.scale;
    uint8_t zp = output_attr.zp;

    // Custom C++ NMS — avoids NPU→CPU shuttle for the whole graph
    std::vector<Detection> detections = decode_outputs(outputs[0].buf, scale, zp);
    std::vector<Detection> nms_results = custom_nms(detections, 0.45f, 0.5f);

    rknn_outputs_release(ctx, 1, outputs);
}
```

### Step 5 — Measure the gain

```c
struct timespec start, end;
clock_gettime(CLOCK_MONOTONIC, &start);

// Full-pipeline benchmark
for (int i = 0; i < 100; i++) {
    preprocess();
    rknn_run(ctx, NULL);
    postprocess();
}

clock_gettime(CLOCK_MONOTONIC, &end);
double ms = (end.tv_sec - start.tv_sec) * 1000.0 +
            (end.tv_nsec - start.tv_nsec) / 1e6;
printf("Avg: %.2f ms/frame\n", ms / 100);
```

Compare the actually convertible full graph, when one exists, against a trimmed graph plus explicit
application-side postprocessing. Report measured values from the selected device; do not reuse
illustrative latency numbers as expectations.

### Design checklist for model optimization

- [ ] Phase 1 benchmark captured (full model, baseline)
- [ ] Verbose build output inspected and relevant operators classified
- [ ] Every rewritten, CPU/custom, rejected, or host-side operator is supported by evidence
- [ ] ONNX trimmed where application-side implementation is the verified design
- [ ] C++ replacement implemented for each removed op
- [ ] Accuracy validated (compare trimmed+CPU vs full model output)
- [ ] Phase 2 benchmark captured (trimmed model + C++ postproc)
- [ ] Speedup confirmed before switching to production

## Verification Checklist

- [ ] Model loads and runs in rknn-toolkit2 simulator.
- [ ] INT8 accuracy acceptable (compare against FP32 baseline).
- [ ] Target platform matches actual SoC (rk3568 / rk3576 / rk3588).
- [ ] Input shape matches runtime data.
- [ ] Quantization dataset representative of production data.
- [ ] Pre-compiled model (if used) matches NPU driver version on board.
- [ ] Batch size matches deployment requirement.
- [ ] Unsupported, rewritten, CPU/custom, and host-side operators are distinguished from build logs and official version-matched documentation.

## RKNN-Toolkit2 and Runtime Compatibility

Do not use a guessed universal compatibility matrix. Model-format compatibility changes by release,
target, feature, and pre-compilation mode, and semantic version ordering alone does not prove that a
Runtime can load an artifact.

For each deployment:

1. Record Toolkit2 version, target platform, conversion options, model hash, Runtime/API version,
   driver version, and the exact target header.
2. Check the matching Toolkit2 changelog, release notes, model-zoo branch, and board SDK documentation.
3. Run `rknn_init` and a known-input parity test on the target image before rollout.
4. Reconvert with the board vendor's validated Toolkit2 release when compatibility is uncertain.

### How to Check Versions
```python
# PC-side: Toolkit2 version
import rknn
print(rknn.__version__)

# Or check installed package
pip show rknn-toolkit2
```

```bash
# Board-side: Runtime version
strings /usr/lib/librknnrt.so | grep -i 'version\|RKNN'
# Or from the API
# rknn_query(ctx, RKNN_QUERY_SDK_VERSION, ...)
```

### Troubleshooting Load Failures

**Step 0: Always anchor against `rknn_model_zoo` examples.** If a model fails to load or execute, try to load a known-good pre-compiled model from the official `rknn_model_zoo` for your exact chip and OS (e.g., a YOLOv5 example). If the zoo model fails, your board environment (driver, runtime) is broken. If the zoo model works but yours fails, the issue is in your conversion pipeline or version mismatch.

Do not classify a generic `rknn_init` failure as a version mismatch without evidence. Capture the full
Runtime log, query SDK/driver versions, verify model integrity and target platform, check pre-compile
compatibility, and reproduce with a vendor model-zoo artifact built for the same image.

## Sources

- Toolkit2 changelog: https://github.com/airockchip/rknn-toolkit2/blob/master/CHANGELOG.md
- Official dynamic-shape example: https://github.com/airockchip/rknn-toolkit2/tree/master/rknn-toolkit2/examples/functions/dynamic_shape
- Runtime header defining tensor types and errors: https://github.com/airockchip/rknn-toolkit2/blob/master/rknpu2/runtime/Linux/librknn_api/include/rknn_api.h
