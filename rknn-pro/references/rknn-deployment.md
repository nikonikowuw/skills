# RKNN Deployment Notes

## Deployment Boundary

Treat RKNN deployment as two distinct phases:

- PC-side model conversion and evaluation with `RKNN-Toolkit2`
- Board-side inference with `RKNN Runtime` in C or C++, or `Toolkit-Lite2` in Python when only a lightweight validation path is needed

The Rockchip `rknn-toolkit2` README explicitly describes this split.

## Verified Support Scope

The `rknn-toolkit2` README lists these relevant supported platforms:

- `RK3588 Series`
- `RK3576 Series`
- `RK3566/RK3568 Series`

The older standalone `rknpu2` repository is deprecated and points to the `rknn-toolkit2` tree instead. Do not build new guidance around the old repository layout.

## Runtime Guidance

- Prefer the C or C++ runtime path for product code.
- Use Python for model conversion, smoke testing, and benchmark harnesses only.
- Keep model conversion artifacts and deployment artifacts version-aligned with the board runtime where possible.
- Treat `RKNN-Toolkit2`, `Toolkit-Lite2`, and `RKNN Runtime` as different surfaces with different responsibilities.

## Performance-Relevant Release Notes

The old `rknpu2` release log is still useful as historical evidence of runtime evolution. It documents features such as:

- Zero-copy related runtime improvements
- Support for `w_stride` and `h_stride` in tensor attributes
- Increased or changed operator support
- Improved dynamic shape support
- Logging that can show MAC utilization and bandwidth occupation at higher log levels in some releases

Do not assume every board image includes these capabilities. Confirm the installed runtime release first.

## Practical Deployment Rules

- Do not let model-conversion success stand in for deployment success.
- Do not assume the fastest `rknn_run` path is the fastest end-to-end path if preproc still copies into host memory.
- If tensor attributes expose `w_stride` and `h_stride`, use them to audit whether layout assumptions match the runtime rather than assuming tightly packed memory.
- If the runtime package is unknown, archive the library and version strings used for the benchmark so results are reproducible.

## Integration Questions

Before editing code, answer these:

- Is the current model already converted to `.rknn`
- Was it converted with a toolkit release compatible with the deployed runtime
- Does the code use classic input copy APIs or runtime-managed memory APIs
- Are preprocessed tensors being materialized in host memory when they could remain in shared buffers longer
- Is postprocess dominating wall time after a fast NPU run

## Failure Patterns

- Model converts successfully but runtime rejects or misbehaves because toolkit and runtime are out of sync
- Inference is “fast” but end-to-end latency is poor because preproc and postproc are still CPU-bound
- Zero-copy claims are made for RKNN itself, but the expensive copies actually happen before `rknn_run`
- Dynamic shape or layout assumptions differ from the installed runtime capabilities
- The code depends on a newer zero-copy or stride-related runtime feature than the board image actually ships

## What To Document In Code Changes

- Conversion tool version used to produce the `.rknn` artifact
- Runtime version observed on the board
- Tensor layout assumptions
- Whether input staging is copy-based or imported-memory based
- Whether output readback is full-tensor, partial, or avoided

## Sources

- Rockchip RKNN Toolkit2 README: https://github.com/airockchip/rknn-toolkit2
- Rockchip legacy rknpu2 README and release log: https://github.com/airockchip/rknpu2
- Rockchip RKNN model zoo: https://github.com/airockchip/rknn_model_zoo
