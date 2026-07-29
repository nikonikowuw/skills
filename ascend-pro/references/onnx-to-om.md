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

- [ ] Framework and ONNX outputs match on representative and boundary inputs.
- [ ] Target SoC and installed ATC/CANN versions are recorded.
- [ ] Every ATC option exists in selected-version help/docs and has a stated reason.
- [ ] Conversion exit status, full log, and artifact checksum are retained.
- [ ] OM runtime I/O metadata matches application binding and preprocessing.
- [ ] OM accuracy passes against reference outputs for every deployed profile.
- [ ] Runtime load/execution succeeds in the reviewed device context.
- [ ] End-to-end performance is measured with product-equivalent preprocessing, copies, and postprocessing.
