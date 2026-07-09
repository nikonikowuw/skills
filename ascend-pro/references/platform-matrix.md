# Ascend Platform Matrix

## Purpose

Use this reference to scope Ascend performance work before making platform claims. Ascend devices and CANN packages vary enough that documentation alone is not a reliable substitute for target-device evidence.

## Device Scope

This skill is centered on Linux inference and media pipelines using Huawei Ascend software surfaces:

- Atlas edge and embedded inference devices, commonly built around Ascend 310, 310B, or 310P class processors.
- Atlas server inference devices where CANN and AscendCL are the runtime surface.
- Ascend 910 or 910B systems when the task is runtime inference, profiling, model deployment, or CANN compatibility. Training and distributed HCCL tuning are outside the default path unless explicitly requested.

Always confirm the actual device model with `npu-smi info`, package metadata, deployment docs, or vendor image notes. Do not infer capabilities from the product family name alone.

## Software Surfaces

Record which of these are actually present:

- Driver and firmware package.
- CANN runtime and toolkit.
- AscendCL or ACL C/C++ headers and shared libraries.
- ATC model conversion tool.
- DVPP media processing libraries and headers.
- AIPP model preprocess configuration, either embedded during conversion or configured through model artifacts.
- Python packages such as `acl`, `ais_bench`, model conversion dependencies, or framework adapters.
- Profiling tools such as `aclprof` or msprof-based tooling, depending on the installed CANN release.

## Common Project Shapes

### C/C++ Product Runtime

Typical path:

`input source -> optional DVPP or CPU preprocess -> ACL device buffer -> aclmdlExecute or aclmdlExecuteAsync -> postprocess`

The main risks are host/device copy churn, per-frame allocation, stream synchronization, and model/runtime version mismatch.

### Python Validation Or Benchmark

Typical path:

`image or tensor loader -> conversion or benchmark wrapper -> OM inference -> result validation`

Use Python for validation and measurement, but do not assume a Python benchmark represents product runtime performance unless it mirrors memory movement and preprocessing.

### Containerized Deployment

Typical path:

`host driver and devices -> mounted CANN runtime -> container binary or Python app`

The main risks are missing device nodes, mismatched host driver and container CANN runtime, incomplete library paths, and copying a toolkit image that differs from the target host.

## Capability Rules

- DVPP support, supported formats, maximum dimensions, and alignment rules are device and CANN dependent.
- AIPP can eliminate CPU preprocessing only when the model conversion configuration and runtime input layout match the task.
- Async APIs are not automatically concurrent; stream synchronization, blocking output retrieval, queue design, and host postprocess can serialize the pipeline.
- An OM model that loads successfully can still be a poor deployment artifact if conversion flags, input shape, precision, or AIPP configuration are wrong for the runtime path.

## Minimum Facts To Confirm

- Device model and NPU visibility.
- Driver, firmware, and CANN versions.
- Whether the project runs on bare metal, in a container, or in a cross-compiled rootfs.
- Actual `libascendcl.so`, DVPP libraries, headers, and Python packages used by the project.
- Model conversion tool version and OM artifact provenance.
- Whether the target path needs image/video media acceleration or pure tensor inference.
