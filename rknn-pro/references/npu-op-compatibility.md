---
toolkit2_version: v2.3.2
last_validated: 2026-07-26
---
# NPU Operator and Quantization Compatibility

Use this reference to investigate model conversion, host/custom operators, and quantization loss.
Every conclusion must be tied to the exact Toolkit2 version, target platform, conversion log, and
deployed Runtime/driver.

## Precision Boundary

- Quantized builds commonly execute INT8. Non-quantized builds commonly execute FP16 on the target.
- `RKNN_TENSOR_FLOAT32` is a valid host tensor type in `rknn_api.h`. With `pass_through=0`, Runtime
  conversion may occur before the model consumes the input.
- `want_float=1` converts an output for the caller; it does not describe NPU graph precision.
- Confirm mixed or per-layer precision from Toolkit2 output and the generated quantization config.

## Unsupported Operators Are Not One Behavior

Do not describe every unsupported ONNX operator as transparent CPU fallback. Depending on Toolkit2
release and target, an operator may:

1. map directly to the NPU;
2. be fused, lowered, or rewritten during conversion;
3. use a documented Toolkit2 CPU/custom-operator implementation;
4. cause conversion to fail; or
5. need to be removed from the model and implemented in application code.

Toolkit2 release notes mention support for selected CPU operators and custom CPU/GPU operators in
specific releases. That does not establish a general-purpose fallback engine. Use the exact compiler
log and the version-matched `RKNN_Compiler_Support_Operator_List.pdf`.

## Verification Workflow

1. Record Toolkit2 version, target platform, ONNX opset, model hash, and conversion options.
2. Run conversion with `RKNN(verbose=True)` and preserve the complete log.
3. Classify each relevant operator as mapped, rewritten/fused, documented CPU/custom, or rejected.
4. Compare the operator, attributes, shapes, and dtypes against the support-list PDF shipped with
   that Toolkit2 release. Do not transfer a result between SoCs or releases without rechecking.
5. Run `accuracy_analysis` and known-input parity tests to locate the first material divergence.
6. On the board, measure end-to-end stage time and CPU utilization. Do not infer host execution from
   latency alone.

Example diagnostic skeleton:

```python
from rknn.api import RKNN

rknn = RKNN(verbose=True)
ret = rknn.load_onnx(model="model.onnx")
if ret != 0:
    raise RuntimeError(f"load_onnx failed: {ret}")

ret = rknn.build(do_quantization=True, dataset="dataset.txt")
if ret != 0:
    raise RuntimeError(f"build failed: {ret}")
```

Do not turn warning strings into a stable parser contract; wording changes between releases.

## Conservative Operator Triage

Use categories as investigation priorities, not a universal support matrix:

| Category | Typical examples | Required check |
|---|---|---|
| Usually straightforward | Conv, common activations, pooling, static reshape/transpose | Exact attributes, shapes, fusion result, target support list |
| Frequently version-sensitive | LayerNorm, GELU, attention, Gather, Resize, Pad, dynamic shapes | Toolkit2 release, SoC, opset, dtype and shape restrictions |
| Often application-side | NMS, decoding, tracking, complex detection postprocess | Whether conversion rejects it or a documented CPU/custom implementation exists |
| Custom/non-standard | Vendor ops, deformable kernels, graph-surgery plugins | Official custom-op flow and target backend availability |

Avoid labels such as "full support" unless the exact operator configuration has been converted and
tested. A model family name such as YOLO or ViT is not sufficient evidence because exported graphs
vary by repository, opset, export flags, and postprocessing choices.

## Quantization Accuracy Workflow

1. Establish an ONNX Runtime baseline with production preprocessing and postprocessing.
2. Build a non-quantized RKNN accuracy baseline and confirm the target/runtime used for comparison.
3. Build INT8 with a representative calibration set. Record dataset provenance and preprocessing.
4. Use `accuracy_analysis` to find the first meaningful divergence rather than applying a global
   cosine-similarity threshold to every model.
5. Check double normalization, RGB/BGR order, NHWC/NCHW layout, output dequantization, and changed
   postprocessing before blaming a layer.
6. Use hybrid quantization only through the interface provided by the installed Toolkit2.

## Official Hybrid Quantization Flow

Current official examples use a two-step workflow, not `rknn.config(custom_string=...)`:

```python
# After config() and load_*()
ret = rknn.hybrid_quantization_step1(
    dataset="dataset.txt",
    proposal=False,
)
if ret != 0:
    raise RuntimeError(f"hybrid_quantization_step1 failed: {ret}")
```

Edit the generated `*.quantization.cfg` and set supported types such as `float16` only for layers
justified by accuracy evidence. Then build the artifact:

```python
ret = rknn.hybrid_quantization_step2(
    model_input="model.model",
    data_input="model.data",
    model_quantization_cfg="model.quantization.cfg",
)
if ret != 0:
    raise RuntimeError(f"hybrid_quantization_step2 failed: {ret}")
```

File names and supported types are generated by the installed release; follow its bundled
`examples/functions/hybrid_quant` directory rather than copying names from this example.

## Dynamic Shapes and Opsets

- Prefer static shapes for production unless multiple shapes are required and tested.
- Configure the supported shape set with Toolkit2 `dynamic_input`; arbitrary ONNX `dynamic_axes`
  do not establish deployable RKNN dynamic-shape support.
- Modern Toolkit2 versions (v2.x) advertise ONNX opset 12 through 19. Treat opset 13 as a conservative
  starting point, then verify the exact release and model operators.

## Reporting

Report:

- exact Toolkit2, Runtime/API, driver, SoC, opset, model hash, and conversion options;
- the first failing or divergent operator with log evidence;
- whether it mapped, was rewritten, used a documented CPU/custom path, or was rejected;
- accuracy and latency before and after the proposed change; and
- any claim still dependent on unavailable board logs or vendor documentation.

## Sources

- Toolkit2 changelog: https://github.com/airockchip/rknn-toolkit2/blob/master/CHANGELOG.md
- Official hybrid-quant example: https://github.com/airockchip/rknn-toolkit2/tree/master/rknn-toolkit2/examples/functions/hybrid_quant
- Official dynamic-shape example: https://github.com/airockchip/rknn-toolkit2/tree/master/rknn-toolkit2/examples/functions/dynamic_shape
- Runtime API header: https://github.com/airockchip/rknn-toolkit2/blob/master/rknpu2/runtime/Linux/librknn_api/include/rknn_api.h
