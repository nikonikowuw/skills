# Model Conversion Guide (Framework → ONNX → OM)

Full model conversion pipeline for Ascend devices: from PyTorch or TensorFlow to ONNX, then ONNX to deployable `.om` offline model via ATC.

---

## 1. PyTorch → ONNX

### Basic export

```python
import torch

model = torch.load("model.pt")  # or torch.jit.load for TorchScript
model.eval()

# Create dummy input matching the model's input shape
dummy_input = torch.randn(1, 3, 224, 224)

# Export to ONNX
torch.onnx.export(
    model,
    dummy_input,
    "model.onnx",
    opset_version=11,          # Ascend supports opset 11+; prefer 13 or 15
    input_names=["input"],
    output_names=["output"],
    dynamic_axes={
        "input": {0: "batch_size", 2: "height", 3: "width"},
        "output": {0: "batch_size"}
    }  # omit for static shapes
)
```

### Key `torch.onnx.export` parameters

| Parameter | Description | Ascend Recommendation |
|---|---|---|
| `opset_version` | ONNX opset version | 11–15; 13 is a safe default |
| `dynamic_axes` | Dict of dynamic dimensions | Use for variable batch/resolution models |
| `input_names` / `output_names` | Named I/O tensors | Match names used in ATC `--input_shape` / `--out_nodes` |
| `do_constant_folding` | Fold constant ops | `True` (default) reduces graph size |
| `export_params` | Include model weights | `True` (default) |

### Common PyTorch→ONNX issues

**Dynamic control flow (if/for dependent on input):**
- PyTorch's `torch.onnx.export` traces the graph with `dummy_input`.
- If the model has data-dependent control flow, use `torch.jit.script()` first, then export.

**Operators not supported in ONNX:**
- Common unsupported ops: `torch.einsum` (partial), advanced indexing with dynamic indices.
- Workaround: rewrite using supported ops (e.g., `torch.matmul` + `torch.reshape`).

**Export with dynamic batch but ATC expects static:**
- Either keep `dynamic_axes` and use ATC's `--dynamic_batch_size`,
- Or export with a fixed batch size and omit `dynamic_axes`.

**Verification:**
```python
import onnx
onnx_model = onnx.load("model.onnx")
onnx.checker.check_model(onnx_model)
print(onnx.helper.printable_graph(onnx_model.graph))
```

### Exporting from HuggingFace / transformers

```python
from transformers import AutoModel
model = AutoModel.from_pretrained("bert-base-uncased")
model.eval()

dummy_input = {
    "input_ids": torch.randint(0, 30000, (1, 128)),
    "attention_mask": torch.ones(1, 128, dtype=torch.long),
}

torch.onnx.export(
    model,
    tuple(dummy_input.values()),
    "bert.onnx",
    opset_version=13,
    input_names=["input_ids", "attention_mask"],
    output_names=["last_hidden_state"],
    dynamic_axes={
        "input_ids": {0: "batch", 1: "seq_len"},
        "attention_mask": {0: "batch", 1: "seq_len"},
    },
)
```

---

## 2. TensorFlow → ONNX

### Using tf2onnx

```bash
pip install tf2onnx onnx
```

**From SavedModel:**
```bash
python -m tf2onnx.convert \
    --saved-model ./saved_model \
    --output model.onnx \
    --opset 13
```

**From frozen .pb (GraphDef):**
```bash
python -m tf2onnx.convert \
    --input model.pb \
    --inputs input:0 \
    --outputs output:0 \
    --output model.onnx \
    --opset 13
```

**From Keras H5 / SavedModel:**
```python
import tf2onnx
import tensorflow as tf

model = tf.keras.models.load_model("model.h5")
spec = (tf.TensorSpec((None, 224, 224, 3), tf.float32, name="input"),)
model.output_names = ["output"]

onnx_model, _ = tf2onnx.convert.from_keras(model, input_signature=spec, opset=13)
onnx.save(onnx_model, "model.onnx")
```

### Key tf2onnx parameters

| Parameter | Description |
|---|---|
| `--opset` | ONNX opset version (11–15; 13 recommended for Ascend) |
| `--inputs` / `--outputs` | Input/output tensor names (with `:0` port suffix) |
| `--inputs-as-nchw` | Treat listed inputs as NCHW format |
| `--fold_const` | Fold constant ops before export |
| `--target` | Target device hints (e.g., `--target=ascend`) |

### TensorFlow → ONNX pitfalls

**NHWC vs NCHW:**
- TensorFlow defaults to NHWC (batch, height, width, channels).
- Ascend models commonly expect NCHW.
- Use `--inputs-as-nchw` in tf2onnx OR transpose in preprocessing.
- Alternatively, use AIPP `ax_swap_switch` to handle channel reorder.

**TF control flow (tf.cond / tf.while_loop):**
- tf2onnx has limited support; prefer to export without dynamic control flow.
- Convert to TF2 static graph if possible (use `@tf.function(jit_compile=True)`).

**Ops missing from ONNX:**
- Some TF ops (e.g., `ExtractImagePatches` with certain params) may not map.
- Run with `--verbose` to see which ops are unsupported.

**Verification:**
```bash
python -m tf2onnx.convert --saved-model ./saved_model --output model.onnx --opset 13
python -c "import onnx; onnx.checker.check_model('model.onnx'); print('OK')"
```

---

## 3. ONNX → OM (ATC)

### Basic command

```bash
atc --model=model.onnx --framework=5 --output=model.om --soc_version=Ascend310P3
```

## Critical Parameters

| Parameter | Values | Description |
|---|---|---|
| `--soc_version` | Ascend310P1/3, Ascend910B1, Ascend310B1, etc. | **Must** match target device. Check via `npu-smi info` or `/usr/local/Ascend/driver/version.conf`. |
| `--precision_mode` | `force_fp16`, `allow_fp32_to_fp16`, `must_keep_origin_dtype`, `allow_mix_precision` | Controls operator precision. `allow_mix_precision` gives best perf/accuracy trade-off. |
| `--op_select_implmode` | `high_precision`, `high_performance` | `high_precision` resolves accuracy degradation; `high_performance` maximizes throughput. |
| `--input_shape` | e.g., `data:1,3,224,224` | Override input shapes (required for dynamic-shaped ONNX models). |
| `--dynamic_batch_size` | e.g., `1,2,4,8` | Enables dynamic batch at runtime. Cannot use with `--input_shape` for the same input. |
| `--dynamic_image_size` | e.g., `224,224;512,512` | Enables dynamic resolution at runtime. |
| `--insert_op_conf` | path to AIPP config | Attach AIPP preprocessing configuration. |
| `--output_type` | FP32, FP16, UINT8, etc. | Force output data type. |
| `--log` | `debug`, `info`, `warning`, `error` | Debug level — use `debug` to see which operators fail. |
| `--out_nodes` | e.g., `output:0` | Specify output node names (when model has multiple outputs). |

## Dynamic Shape Strategies

### Dynamic batch (`--dynamic_batch_size`)
```
--dynamic_batch_size=1,2,4,8 --input_shape="data:-1,3,224,224"
```
- ATC generates optimization profiles for each batch size
- At runtime, use `aclmdlSetDynamicBatchSize` before each inference
- Batch-1 and batch-8 may have different throughput characteristics

### Dynamic image size (`--dynamic_image_size`)
```
--dynamic_image_size="224,224;512,512"
--input_shape="data:1,3,-1,-1"
```
- Each HW pair generates an optimization profile
- At runtime, use `aclmdlSetDynamicHWSize` before inference
- Cannot use `Crop`/`Padding` AIPP features in this mode

### Dynamic shape (ND format)
```
--input_shape="data:1,3,-1,-1"  --dynamic_dims="224,224;512,512"
```
- Use `aclmdlSetInputShape` at runtime
- Most flexible but may have lower performance than profile-based approaches

## Precision Optimization Guide

### When accuracy drops after conversion

1. Try `--precision_mode=allow_mix_precision` first
2. If still degraded: `--precision_mode=must_keep_origin_dtype`
3. If specific ops are problematic: `--op_select_implmode=high_precision`
4. Use `--precision_mode=allow_fp32_to_fp16` for a balance

### When throughput is critical

1. `--precision_mode=force_fp16` (fastest, may lose accuracy)
2. `--op_select_implmode=high_performance`
3. Combine with `--enable_scope_fusion_passes` for aggressive fusion

## Conversion Debugging

### ATC fails with operator error

```bash
atc --model=model.onnx --framework=5 --output=model.om --soc_version=Ascend310P3 --log=debug 2>&1 | grep -i "fail\|unsupported\|error"
```

Common operator issues:
- Custom ONNX ops not registered → write a custom operator plugin
- Operator not supported on target SOC → check operator list in CANN documentation
- Dynamic shape constraints → flatten or fix input shape specification

### ATC succeeds but OM fails at runtime

```bash
# Check CANN version compatibility
cat /usr/local/Ascend/version.cfg
# Compare with ATC version used for conversion

# Load the OM with debug logging
export ASCEND_SLOG_PRINT_TO_STDOUT=1
export ASCEND_GLOBAL_LOG_LEVEL=1
```

Root causes:
1. CANN version mismatch between conversion environment and deployment device
2. `--soc_version` does not match actual deployment hardware
3. OM was built for different memory constraints

## AIPP + Conversion Interaction

- **Static AIPP**: parameters frozen at conversion; simpler, no runtime overhead
- **Dynamic AIPP**: parameters set via `aclmdlSetInputAIPP` at runtime; ATC adds `AippData` input
- Dynamic batch `--dynamic_batch_size` + AIPP: `batchSize` param must equal max batch
- Dynamic image size `--dynamic_image_size` + AIPP: `Crop`/`Padding` disabled at runtime
- `--input_shape` + AIPP: AIPP output W/H must be within the shape range

## Verification Checklist

- [ ] `--soc_version` matches deployment device (check `npu-smi info`)
- [ ] CANN version on conversion host and deployment device are compatible (within 4 minor versions)
- [ ] Input shape(s) match runtime data
- [ ] AIPP config (if used) matches runtime input format and layout
- [ ] Dynamic shape policy (if used) is consistent between conversion and runtime code
- [ ] Accuracy validated after conversion (compare NPU output vs CPU/GPU reference)
- [ ] Throughput measured after conversion (not just single-inference latency)
- [ ] `atc --debug` shows no unsupported operator fallbacks
