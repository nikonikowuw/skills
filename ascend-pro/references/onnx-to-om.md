# Framework To ONNX To OM Workflow

Conversion is two separately validated boundaries:

```text
framework artifact -> ONNX -> OM for one target SoC/toolchain
```

Do not tune ATC before proving the ONNX model matches the framework, and do not treat ATC success as proof
that the OM is accurate, compatible, or performant.

## Conversion Record

Create a record containing:

- source framework/version, model checksum, code revision, and model mode;
- deterministic representative inputs and preprocessing contract;
- input/output names, dtypes, layouts, shapes, dynamic axes, and acceptable tolerances;
- exporter/runtime/ONNX versions and chosen opset with compatibility evidence;
- target device/SoC, ATC version, exact command/log, and CANN compatibility source;
- precision/operator/AIPP/dynamic-shape flags from that installed ATC version;
- ONNX and OM checksums plus accuracy and performance results.

No opset, precision mode, dynamic flag, or ATC option is a universal default. Select it from the installed
exporter, target ATC operator support, and exact model requirements.

## Framework To ONNX

1. Load the model through its normal repository code, set evaluation/inference mode, and freeze randomness.
2. Build representative inputs from the real runtime contract, including optional inputs and boundary shapes.
3. Query the exporter and target toolchain for supported opsets; choose the newest mutually supported opset
   only after checking operator coverage.
4. Export with explicit input/output names and intentional dynamic dimensions.
5. Run the ONNX structural checker and shape inference where applicable.
6. Execute the ONNX model in an independent reference runtime on the same inputs.
7. Compare every relevant output against the framework model with dtype/model-appropriate tolerances.

Example verification skeleton:

```python
import numpy as np
import onnx
import onnxruntime as ort

onnx_model = onnx.load("model.onnx")
onnx.checker.check_model(onnx_model)

session = ort.InferenceSession("model.onnx", providers=["CPUExecutionProvider"])
onnx_outputs = session.run(None, representative_inputs)

for expected, actual in zip(framework_outputs, onnx_outputs):
    np.testing.assert_allclose(actual, expected, rtol=rtol, atol=atol)
```

Adapt conversion code to the installed framework/exporter version. Exporter APIs and control-flow support
change; do not paste a legacy PyTorch or tf2onnx snippet without checking its current signature.

## ONNX Failure Triage

- Minimize the first mismatching output/subgraph rather than rewriting the entire model.
- Distinguish exporter failure, invalid ONNX, unsupported reference-runtime operator, and numeric mismatch.
- Preserve tensor names and intermediate comparison hooks while debugging.
- Use graph simplification or constant folding only if before/after ONNX outputs remain equivalent.
- Treat layout transposes, integer types, dynamic indexing, control flow, resize semantics, and NMS variants
  as explicit compatibility risks.

## ONNX To OM

1. Establish the target SoC and installed `atc --version`.
2. Inspect `atc --help` and exact-version official documentation for supported flags and operator coverage.
3. Start from the minimum command required by that version. Do not append `.om` to `--output` unless the
   selected ATC documentation says the argument is a filename rather than an output prefix.
4. Add input-shape, dynamic-shape, precision, output-node, or AIPP options one decision at a time.
5. Capture the complete log with `pipefail` as described in [debug-logging.md](debug-logging.md).
6. Fail the workflow if ATC exits nonzero even if a pipeline command such as `tee` succeeded.
7. Hash the generated artifact and store it with the conversion record.

Command shape, with placeholders intentionally left version-specific:

```bash
set -o pipefail
atc \
  --model=model.onnx \
  --framework=5 \
  --output=model \
  --soc_version=<verified-target> \
  <verified-version-specific-options> \
  2>&1 | tee atc-conversion.log
```

## Dynamic Shapes

Choose static, dynamic batch, dynamic image size, or general dynamic dimensions from workload evidence.
Then verify, for the selected ATC/CANN version:

- valid flag combinations and syntax;
- generated model control inputs and runtime setter API;
- supported profiles/ranges and buffer sizing behavior;
- AIPP interaction;
- runtime input binding and per-shape accuracy/performance.

Static shapes are the default when production uses a fixed contract. Dynamic flexibility has artifact size,
compile-time, runtime, memory, and performance costs that must be measured rather than assumed.

## Precision Tuning

1. Establish a known-good framework and ONNX output corpus.
2. Generate an OM with the least aggressive supported conversion policy.
3. Compare tensor/model outputs and task metrics.
4. Use ATC diagnostics to identify the first precision-sensitive operator or subgraph.
5. Change one exact-version precision/operator setting.
6. Regenerate, revalidate accuracy, and measure the same workload.

Never describe a precision mode as “best” or “fastest” without measurements on the selected model/device.

## AIPP

Follow [aipp-config-reference.md](aipp-config-reference.md). Compare tensor preprocessing and model outputs,
not only final application results. Archive the config with the OM because it changes the runtime input contract.

## Deployment Gate

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
atc --model=model.onnx --framework=5 --output=model.om --soc_version=Ascend310B4
```

> 💡 **Supported `soc_version` examples (CANN 7.0 / 8.0)**:
>
> - Edge/Embedded: `Ascend310B1`, `Ascend310B4`, `Ascend310P1`, `Ascend310P3`, `Ascend310P4`
> - Server/Training: `Ascend910B1`, `Ascend910B2`, `Ascend910B3`, `Ascend910B4`

## Critical Parameters

| Parameter | Values | Description |
| --- | --- | --- |
| `--soc_version` | Ascend310B1/B4, Ascend310P1/3/4, Ascend910B1-B4 | **Must** match target device. Check via `npu-smi info` or `version.conf`. |
| `--precision_mode` | `force_fp16`, `force_fp8` (CANN 8.0+ Ascend910B3/B4), `allow_fp32_to_fp16`, `must_keep_origin_dtype`, `allow_mix_precision` | Controls operator precision. `allow_mix_precision` gives best perf/accuracy trade-off. |
| `--op_select_implmode` | `high_precision`, `high_performance` | `high_precision` resolves accuracy degradation; `high_performance` maximizes throughput. |
| `--enable_compress_weight` | `true`, `false` | Enables weight compression to reduce OM model size on memory-constrained devices. |
| `--buffer_optimize` | `off_optimize`, `l1_optimize`, `l2_optimize` | Memory buffer reuse optimization for Graph Engine during offline model generation. |
| `--input_shape` | e.g., `data:1,3,224,224` | Override input shapes (required for dynamic-shaped ONNX models). |
| `--dynamic_batch_size` | e.g., `1,2,4,8` | Enables dynamic batch at runtime. Cannot use with `--input_shape` for the same input. |
| `--dynamic_image_size` | e.g., `224,224;512,512` | Enables dynamic resolution at runtime. |
| `--insert_op_conf` | path to AIPP config | Attach AIPP preprocessing configuration (supports `.cfg` or CANN 8.0 `.yaml`). |
| `--output_type` | FP32, FP16, UINT8, etc. | Force output data type. |
| `--log` | `debug`, `info`, `warning`, `error` | Debug level — use `debug` to see which operators fail. |
| `--out_nodes` | e.g., `output:0` | Specify output node names (when model has multiple outputs). |

---

## 4. AOE Auto-Tuning (Ascend Optimization Engine)

CANN provides **AOE (Ascend Optimization Engine)** to automatically tune operators and subgraphs for target Ascend NPUs after initial ONNX conversion.

### Running AOE

```bash
aoe --framework=5 --model=model.onnx --output=model_tuned.om \
    --soc_version=Ascend310B4 \
    --job_type=1 \
    --aoe_mode=subgraph,operator
```

### AOE Job Types & Modes

| Parameter | Options | Purpose |
| --- | --- | --- |
| `--job_type` | `1` (subgraph), `2` (operator) | `1` tunes subgraph fusion passes; `2` tunes GEMM/Conv operator tile policies. |
| `--aoe_mode` | `subgraph`, `operator`, `block` | Multi-stage auto-tuning mode for CANN 8.0+. Combine modes with commas. |

> 💡 **Best Practice**: Run baseline ATC conversion first to produce `model.om`. If throughput or latency needs further optimization, run AOE tuning to produce `model_tuned.om` and measure the performance gain with `summarize-stage-latency.py`.

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
