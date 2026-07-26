# RKNN Model Conversion Evidence Manifest

Keep this file in the target project as `.agents/rknn-model-context.md`. Use one section per RKNN
artifact. Do not overwrite one model's evidence with another model's data.

Allowed evidence states are `confirmed-present`, `confirmed-absent`, and `unknown`. A missing artifact
or log is `unknown`, not `absent`.

## Identity and Artifact Chain

| Field | Value | Evidence |
|---|---|---|
| Context ID | `<model>-<onnx-sha-prefix>-<rknn-sha-prefix>-<target>` | This manifest |
| Source framework/checkpoint | `unknown` | Export script or training record |
| ONNX path | `unknown` | Artifact |
| ONNX SHA-256 | `unknown` | `inspect-onnx-model.py` or `sha256sum` |
| ONNX export script/commit | `unknown` | Repository path and commit |
| Conversion script SHA-256 | `unknown` | Conversion source |
| Toolkit2 version | `unknown` | Conversion environment |
| Target platform | `unknown` | Exact `rknn.config()` call/log |
| Conversion log/build report | `unknown` | Preserved verbose output/report |
| RKNN path | `unknown` | Artifact |
| RKNN SHA-256 | `unknown` | `sha256sum` |

The ONNX hash, conversion script/config, conversion log/report, and RKNN hash must describe one
conversion run. A collection of unrelated artifacts does not establish provenance.

## ONNX Contract

Generate a draft with:

```bash
python3 <skill-root>/scripts/inspect-onnx-model.py model.onnx -o onnx-inspection.md
```

Record:

- IR version, opset imports, producer, and model metadata.
- Every graph input/output name, dtype, shape, and dynamic dimension.
- Operator counts and any preprocessing candidates near graph inputs.
- The training/export preprocessing contract and its source location.

The inspector reports graph structure, not author intent. `Sub`, `Div`, `Mul`, `Cast`, `Transpose`,
or `Resize` near an input may be preprocessing, but confirm its constants and expected raw input
domain against the export/training code.

## Normalization Contract

Classify every location. Exactly one intended end-to-end contract must explain how the application
input becomes the tensor domain used during training.

| Location | State | Exact operation and channel order | Evidence |
|---|---|---|---|
| Embedded in ONNX graph | `unknown` | `unknown` | ONNX graph plus export/training code |
| Toolkit2 `mean_values` / `std_values` | `unknown` | `unknown` | Exact conversion config/log |
| Application/RGA before Runtime | `unknown` | `unknown` | Runtime source/config |

Also record:

| Field | Value |
|---|---|
| Source pixel/tensor format | `unknown` |
| Source value range | `unknown` |
| Resize/crop/letterbox policy | `unknown` |
| RGB/BGR order | `unknown` |
| NCHW/NHWC layout at each boundary | `unknown` |
| Runtime host input type and `pass_through` | `unknown` |
| Expected tensor values before the first learned operator | `unknown` |
| Known-input parity test | `not-run` |

Two active normalization locations usually cause double normalization. No active location causes
missing normalization when training expected it. Zero-valued means or unit standard deviations are
still part of an input transform and do not prove the channel order or training contract by
themselves.

## Quantization and Precision

| Field | Value | Evidence |
|---|---|---|
| `do_quantization` requested | `unknown` | Exact `rknn.build()` call/log |
| Quantized dtype/algorithm | `unknown` | Exact config/log |
| Calibration dataset path/hash/count | `unknown` | Dataset manifest |
| Calibration preprocessing | `unknown` | Dataset loader/conversion code |
| Build completed successfully | `unknown` | Conversion log |
| Actual graph/layer precision | `unknown` | Toolkit2 build report/accuracy analysis |
| Mixed/hybrid precision layers | `unknown` | Build report and quantization config |
| Accuracy versus source baseline | `not-run` | Reproducible parity evaluation |

`do_quantization=True` confirms that post-training quantization was requested. It does not by itself
prove that the exported RKNN is wholly INT8; conversion may use mixed precision, preserve selected
layers, or fail before exporting the artifact. Runtime input/output `qnt_type`, `zp`, and `scale`
describe external tensors, not every internal layer.

## Runtime-Queried Contract

For every input and output, record the deployed Runtime/API version and queried `rknn_tensor_attr`:

| Tensor | Input/output | Type | Format | Dimensions | Strides/bytes | Quantization | Evidence |
|---|---|---|---|---|---|---|---|
| `unknown` | `unknown` | `unknown` | `unknown` | `unknown` | `unknown` | `unknown` | Runtime query log |

## Gate Decision

| Decision | Status | Blocker or evidence |
|---|---|---|
| Normalization contract confirmed | `blocked` | `unknown` |
| Actual INT8/mixed graph precision confirmed | `blocked` | `unknown` |
| Runtime input and `pass_through` approved | `blocked` | `unknown` |
| Zero-copy tensor layout approved | `blocked` | `unknown` |
| Quantization-sensitive postprocessing approved | `blocked` | `unknown` |
| Production deployment approved | `blocked` | `unknown` |

Unrelated source-only work may continue while a decision is blocked. State the unknowns in reviews
and avoid silently substituting conventions from another model or conversion run.
