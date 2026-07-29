---
name: ascend-pro
description: >
  Load when a task targets Huawei Ascend or Atlas hardware and involves CANN, ATC/OM conversion,
  AscendCL/ACL, DVPP, AIPP, NPU inference, profiling, device memory, or runtime compatibility.
  Do not use for generic ONNX or NPU questions, Rockchip/RKNN, CUDA/TensorRT, or OpenVINO unless
  Huawei Ascend is also an explicit deployment target.
---

# Ascend Pro

Build, diagnose, review, and optimize Huawei Ascend inference and media pipelines. Prefer the
project's existing language, logging, build, and error-handling conventions. Use C/C++ for product
runtime when the repository does; use Python for conversion, validation, inspection, and profiling.

## Route First

Identify the task before requesting device evidence. Read only the references on the selected route.

| Task | Required reads | Evidence gate | Verification |
|---|---|---|---|
| Skill maintenance or meta-review | [skill-evals.md](references/skill-evals.md) | None | Run the skill validation commands in that file |
| General explanation or static code review | Relevant API reference below | None | Separate source facts from device assumptions |
| PyTorch/TF export to ONNX for an Ascend target | [onnx-to-om.md](references/onnx-to-om.md) | Model inputs and intended ATC target | Validate ONNX with its checker and reference runtime |
| ONNX to OM or AIPP configuration | [onnx-to-om.md](references/onnx-to-om.md), [aipp-config-reference.md](references/aipp-config-reference.md), [version-audit.md](references/version-audit.md) | Target SoC and installed ATC/CANN version | Preserve the exact command and compare accuracy |
| AscendCL API or model execution | [acl-api-reference.md](references/acl-api-reference.md), [ascend-deployment.md](references/ascend-deployment.md) | CANN version for code changes | Build against selected headers and verify deployed symbols |
| DVPP, VDEC/VENC, VPC, or media preprocessing | [dvpp-api-reference.md](references/dvpp-api-reference.md), [memory-alignment.md](references/memory-alignment.md), [acl-dvpp-pipeline.md](references/acl-dvpp-pipeline.md) | Device model, CANN version, formats, dimensions, and strides | Recalculate sizes and test on the target |
| Zero-copy or async inference design | [zero-copy-inference.md](references/zero-copy-inference.md), [acl-dvpp-pipeline.md](references/acl-dvpp-pipeline.md), [debug-logging.md](references/debug-logging.md) | Active runtime context and complete buffer path | Account for every owner, memory domain, copy, and sync |
| Performance regression or low utilization | [perf-debugging.md](references/perf-debugging.md), [debug-logging.md](references/debug-logging.md), [version-audit.md](references/version-audit.md) | Reviewed baseline plus stage timings | Change one bottleneck and compare the same workload |
| Runtime failure, environment mismatch, or unfamiliar project | [project-onboarding-workflow.md](references/project-onboarding-workflow.md), [device-evidence-workflow.md](references/device-evidence-workflow.md), [platform-matrix.md](references/platform-matrix.md) | Full reviewed baseline | Reproduce in exactly one selected context |
| Multi-device or host/container deployment | [device-scoped-context.md](references/device-scoped-context.md), [baseline-file-convention.md](references/baseline-file-convention.md) | One context per runtime target | Test every supported context independently |
| Other Ascend work | [platform-matrix.md](references/platform-matrix.md) | Determine from the nearest route | State the chosen route and remaining unknowns |

## Evidence Gates

Use the lowest gate that can support the requested conclusion.

### Gate 0: No device baseline

Use for skill maintenance, conceptual explanations, source-only review, and framework-to-ONNX work
that does not choose ATC flags. Do not block these tasks on device access.

### Gate 1: Target facts

Use for API selection, ATC flags, AIPP, and device-sensitive design. Confirm the device model, CANN
or ATC version, host/container boundary, input contract, and relevant installed headers. If unavailable,
continue only where the result is version-independent and label the rest as provisional.

### Gate 2: Reviewed runtime context

Use before device-specific implementation, deployment changes, runtime diagnosis, or performance claims.
Follow [device-evidence-workflow.md](references/device-evidence-workflow.md) and review the generated draft
with [baseline-review-checklist.md](references/baseline-review-checklist.md). A cached context is reusable
only after its identity and version fingerprint are revalidated. File existence alone proves nothing.

Never request or store raw `/etc/machine-id`. It is a host identifier and may be confidential. The helper
scripts emit an application-specific context token and redact common identifiers. Ask the user to inspect
the bundle before sharing it.

## Runtime Context Rules

A runtime context includes: pseudonymous host token, NPU identity or selected device index, device model,
driver/firmware, CANN root and version, loaded libraries, headers, host/container boundary, and OM
artifact provenance.

- Select exactly one active context before context-dependent code changes.
- Do not mix headers, `.so` files, symbols, AIPP settings, OM artifacts, or measurements across contexts.
- Treat a card replacement, device-index change, CANN/driver update, container image change, or regenerated
  OM as a context change that requires revalidation.
- Store generated drafts separately from reviewed context. Never silently overwrite reviewed notes.
- Use [context-template.md](references/context-template.md) for reviewed context files.

## Documentation Evidence

Ascend APIs and constraints vary by device and CANN release. Use this precedence:

1. Headers, shared-object symbols, tool help, and documentation installed with the selected runtime.
2. Official Huawei documentation for the exact CANN/device version.
3. This skill's references as working guidance, never as proof of a device-specific numeric limit.

If `ctx_search` and the indexed `ascend-*` sources are available, use them. Otherwise inspect the local
CANN installation or search official Huawei sources. If none is available, mark the claim unverified.
Record the source, CANN version, device family, and verification date for alignment or capability facts.

## Pipeline Procedure

For implementation or optimization work:

1. State the active context and input/output contract.
2. Draw `source -> decode -> preprocess -> model input -> inference -> output -> postprocess`.
3. Annotate every hop with owner, memory domain, format, dimensions, stride, allocation API, copy, and sync.
4. Prefer device-resident handoff when the selected APIs support it; prove rather than assume zero-copy.
5. Reuse stable buffer pools; treat per-frame allocation, repeated `aclrtMemcpy`, CPU conversion, full
   output readback, and eager stream synchronization as suspects.
6. Integrate diagnostics through the project's existing logging and error-handling system. Use
   [debug-logging.md](references/debug-logging.md) as an adapter pattern, not a mandatory dependency.
7. Measure stage latency with a fixed workload, change one bottleneck, and repeat the same measurement.

## Known Gotchas

- Async API calls can still serialize at stream sync, output readback, queue waits, or CPU postprocess.
- A discovered library is not necessarily the loaded library; prove linkage with `ldd`, `readelf`, or
  the project's `dlopen` path.
- An OM that loads is not necessarily compatible or performant; retain ATC version, command, source model,
  input contract, precision policy, AIPP config, and target SoC.
- DVPP formats, dimensions, address rules, and stride formulas are device/CANN specific. Recalculate from
  the selected documentation and actual descriptors before allocation.
- Do not add logging dependencies or replace an established logger solely because an example uses spdlog.

## Deliverables

For substantial tasks, report the active context, verified facts, data/buffer flow, bottleneck or failure
hypothesis, changes made, measurement or reproduction method, results, and unresolved device-specific risks.
