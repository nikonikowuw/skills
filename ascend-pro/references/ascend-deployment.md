# Ascend Deployment Notes

## Deployment Boundary

Treat Ascend deployment as two distinct phases:

- Conversion and validation of a framework or ONNX model into an OM artifact, usually with ATC.
- Device-side inference with AscendCL or project wrappers around ACL model loading and execution.

Do not let model-conversion success stand in for runtime deployment success.

## Model Conversion Facts To Capture

For each OM artifact, record:

- Source model path and framework.
- ATC version and full command line.
- Target chip or SOC version flag when used.
- Input names and shapes.
- Dynamic shape, dynamic batch, or dynamic resolution policy.
- Precision and operator flags.
- AIPP configuration and whether it is static or dynamic.
- Calibration or quantization provenance when relevant.

## Runtime Guidance

- Prefer C or C++ AscendCL for product runtime unless the repository is explicitly Python-first.
- Use Python tools for conversion checks, smoke testing, model accuracy validation, and benchmark harnesses.
- Keep conversion tool version, runtime CANN version, and target device aligned where possible.
- Treat framework adapters, benchmark wrappers, ATC, and ACL runtime as different surfaces with different responsibilities.

## Integration Questions

Before editing code, answer these:

- Is the current model already converted to `.om`?
- Was it converted with a toolchain compatible with the deployed CANN runtime and target device?
- Does the code use copy-based input staging or stable device buffers?
- Does preprocessing happen on CPU, DVPP, AIPP, or a mixed path?
- Is postprocess dominating wall time after a fast NPU run?
- Are shapes static, dynamic, batched, or changed per request?

## Failure Patterns

- ATC succeeds but runtime load fails because the target device or CANN version differs.
- Runtime execution is fast but end-to-end latency is poor because preproc and postproc are still CPU-bound.
- AIPP is configured but CPU preprocessing remains in the hot path.
- Dynamic shape policy differs between conversion and runtime input binding.
- Python benchmark numbers are copied into a C++ product design without matching memory movement.
- Multiple OM artifacts exist and the project deploys a different one than the developer tested.

## What To Document In Code Changes

- Conversion tool version used to produce the OM artifact.
- Runtime CANN version observed on the device.
- Tensor layout and shape assumptions.
- Whether input staging is copy-based or device-buffer based.
- Whether output readback is full-tensor, partial, batched, or avoided.
- How accuracy was revalidated after preprocessing or AIPP changes.
