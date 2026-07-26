---
name: rknn-pro
description: >
  Build, diagnose, review, or optimize Linux inference and media pipelines that use Rockchip RKNN, RKNN-Toolkit2, RKNN Runtime/RKNPU2, RGA/librga, MPP, DMA-BUF, or RK3568/RK3576/RK3588-class SoCs. Use this skill whenever a task mentions RKNN model conversion or quantization, Rockchip NPU operators, tensor stride or alignment, zero-copy camera/video pipelines, multi-model scheduling, runtime/BSP compatibility, high CPU or latency, memory corruption, service crashes, or kernel-facing safety, even when the user does not explicitly ask for an RKNN expert.
---

# rknn-pro

Build or tune Rockchip inference and media pipelines on RK3568, RK3576, and RK3588 Linux systems.

## Workflow

1. Classify the task before collecting evidence. Source-only review, conversion planning, and API explanation can start without board access; mark board-dependent conclusions as unverified.
2. Before developing or approving model input, preprocessing, zero-copy tensor layout, quantization-sensitive postprocessing, or deployment configuration, pass the Model Conversion Evidence Gate below. Keep model provenance separate from device provenance.
3. When ABI, allocator, driver, compatibility, or performance facts matter, select one device context. Run the bundled diagnostic on that board and render `.agents/rknn-context.md` in the target project.
4. Read only the references needed for the active task:
   - Model conversion or quantization: [model-conversion.md](references/model-conversion.md), then [npu-op-compatibility.md](references/npu-op-compatibility.md) for operator or precision issues.
   - Runtime/RGA/MPP API question: start with [api-quick-reference.md](references/api-quick-reference.md), then open the subsystem reference.
   - DMA-BUF or inference pipeline: [zero-copy-pipeline.md](references/zero-copy-pipeline.md); for an implementation audit, follow [zero-copy-check.md](references/zero-copy-check.md) and dispatch the required subagent.
   - Multi-model or cascade scheduling: [multi-model-scheduling.md](references/multi-model-scheduling.md).
   - SDK upgrade, tensor allocation, alignment, or stride: [memory-alignment.md](references/memory-alignment.md).
   - Crash or full safety audit: follow every phase in [project-crash-risk-audit.md](references/project-crash-risk-audit.md) and use [known-crash-patterns.md](references/known-crash-patterns.md) only as evidence anchors.
5. Separate observed facts, source-derived findings, hypotheses, and model- or board-dependent unknowns in the final answer.

Resolve `scripts/...` and `references/...` relative to this `SKILL.md`, not the target repository. Run bundled scripts by absolute path while keeping the shell working directory at the target project so generated context and reports land there.

## Model Conversion Evidence Gate (`.agents/rknn-model-context.md`)

This gate is required when a development decision depends on what the RKNN artifact expects. Create or update the model context using [model-conversion-manifest.md](references/model-conversion-manifest.md) and preserve the evidence chain:

- [ ] ONNX artifact path and SHA-256; opset, inputs/outputs, shapes, dtypes, dynamic dimensions, metadata, and possible graph-embedded preprocessing. Run `python3 <skill-root>/scripts/inspect-onnx-model.py model.onnx` when the artifact is available.
- [ ] Exact conversion script/config, Toolkit2 version, target platform, and verbose conversion log.
- [ ] Exact `rknn.config()` input contract: `mean_values`, `std_values`, channel order, layout, raw value range, and any reorder/quantization options.
- [ ] Exact `rknn.build()` request, including `do_quantization`, quantized dtype/algorithm, calibration dataset identity, and calibration preprocessing.
- [ ] Build report or other Toolkit2 evidence that confirms actual graph/layer precision, including mixed precision; `do_quantization=True` proves only what was requested.
- [ ] RKNN artifact path and SHA-256, linked to the conversion evidence above.
- [ ] Runtime-queried input/output attributes: type, format, dimensions, strides, quantization type, zero point, and scale.

Assess all three possible normalization locations as **confirmed-present**, **confirmed-absent**, or **unknown**: ONNX graph, Toolkit2 `mean_values`/`std_values`, and application/RGA preprocessing. Pass the gate only when none remains unknown, the evidence establishes one intended end-to-end normalization contract, and actual graph/layer precision is confirmed. A graph inspection can identify candidates but cannot prove the training contract.

If only a `.rknn` file or host-side C buffer is available, record normalization and graph INT8 status as **unknown**. Runtime tensor attributes may confirm the external I/O contract but do not recover Toolkit2 normalization settings or prove whole-graph precision. Continue unrelated source review, but do not finalize preprocessing, `pass_through`, zero-copy input layout, quantization-sensitive postprocessing, or production deployment choices by guessing.

When the gate is blocked, make the boundary explicit in the response. Report:

1. A status for ONNX-embedded normalization, Toolkit2 normalization, application normalization, and actual graph/layer precision. Use `unknown` when evidence is missing.
2. Missing ONNX identity and contract fields by name: SHA-256, IR/opset, producer/metadata, every input/output name, shape, dtype, and dynamic dimension, plus input-prefix preprocessing candidates.
3. Missing conversion evidence: script/config, Toolkit2 version and target, build request/log/report, calibration provenance, mixed-precision configuration, and RKNN SHA-256.
4. Decisions blocked by those unknowns and the evidence needed to unblock them.
5. Work that may continue now, limited to analysis or implementation whose correctness does not depend on the missing model facts.

## Initialization Checklist (`.agents/rknn-context.md`)

When board-specific facts matter or fingerprint mismatches:
- [ ] Run `<skill-root>/scripts/rknn-diag.sh` on device (or use the checklist in [device-baseline-workflow.md](references/device-baseline-workflow.md)).
- [ ] Build baseline from the target project: `python3 <skill-root>/scripts/render-project-baseline.py pasted-evidence.txt -o .agents/rknn-context.md`.
- [ ] Set context ID: `{device_id_or_label}-{soc}-{environment_fingerprint}-{purpose}`. Maintain separate blocks per board/BSP.
- [ ] Review parser output against the raw evidence. A generated baseline is a draft, not proof.

## Precision and Tensor-I/O Boundary

- Confirm graph/layer precision from Toolkit2 build reports; don't infer from host ONNX dtype, C buffer type, or output convenience flags.
- Confirm Toolkit2 normalization from the preserved conversion config/log; don't infer it from ONNX input dtype or Runtime tensor attributes.
- `RKNN_TENSOR_FLOAT32` with `pass_through=0` converts host FP32 to model native format. It is not NPU FP32 execution. Measure conversion cost.

## Design Checklist

- [ ] Buffer origin known (V4L2, MPP, DRM, custom)? Format/stride at each hop?
- [ ] Direct DMA-BUF fd handoff? (No implicit conversion/software copy?)
- [ ] RKNN I/O uses runtime-managed or imported memory?
- [ ] Model evidence gate passed for normalization, input contract, and actual graph/layer precision?
- [ ] Graph precision confirmed from report, not host dtype?
- [ ] CMake uses `size_with_stride` gracefully with older headers?
- [ ] `rknn_create_mem` uses max of tensor size vs stride-derived size?
- [ ] RGA destination matches NPU queried `w_stride` / `h_stride`?
- [ ] Math overflow / out-of-bounds proven impossible for strides/ROI?
- [ ] Resource acquisition (fd/mmap) paired with release across all paths?
- [ ] Queue limits enforced? Cache sync / fences ordered correctly?
- [ ] NPU cores assigned and memory budgeted for multi-model?

## References

### Core
| File | Topic |
|---|---|
| [soc-matrix.md](references/soc-matrix.md) | RK3568 vs RK3576 vs RK3588 vs RV1106 differences, RKLLM bounds |
| [model-conversion.md](references/model-conversion.md) | PT/TF→ONNX→RKNN, quantization, version checks |
| [model-conversion-manifest.md](references/model-conversion-manifest.md) | Required model provenance and normalization/precision evidence template |
| [yolo-deployment-cookbook.md](references/yolo-deployment-cookbook.md) | YOLOv8/v11/RT-DETR deployment, hybrid quantization |
| [npu-op-compatibility.md](references/npu-op-compatibility.md) | Operator verification, CPU/custom operators, quantization |
| [multi-model-scheduling.md](references/multi-model-scheduling.md) | Multi-model concurrent inference, NPU core assignment |
| [rknn-api-reference.md](references/rknn-api-reference.md) | RKNN Runtime API signatures, parameters, memory modes |
| [rga-api-reference.md](references/rga-api-reference.md) | RGA im2d API, DMA-BUF import, format/alignment constraints |
| [mpp-api-reference.md](references/mpp-api-reference.md) | MPP decode/encode, external buffer mode, buffer pool |
| [api-quick-reference.md](references/api-quick-reference.md) | Condensed API signatures for RKNN, RGA, MPP |
| [memory-alignment.md](references/memory-alignment.md) | **Critical**: RKNN `size_with_stride`, allocation fallback, RGA/MPP stride |

### Pipeline, Audit, & Workflow
| File | Topic |
|---|---|
| [zero-copy-pipeline.md](references/zero-copy-pipeline.md) | DMA-BUF pipeline, MPP/RGA zero-copy patterns |
| [zero-copy-check.md](references/zero-copy-check.md) | **Audit procedure** — subagent dispatch for max zero-copy |
| [project-crash-risk-audit.md](references/project-crash-risk-audit.md) | **Comprehensive safety audit** — overflow, lifetime, crash risk |
| [known-crash-patterns.md](references/known-crash-patterns.md) | Official failure modes and community cases |
| [perf-debugging.md](references/perf-debugging.md) | Throughput, hidden copies, sync waits |
| [device-baseline-workflow.md](references/device-baseline-workflow.md) | Full device-evidence loop: collect, baseline, review |
| [device-scoped-context.md](references/device-scoped-context.md) | Multiple boards, containers, or BSP images |
| [version-audit.md](references/version-audit.md) | BSP library version compatibility |
| [project-onboarding-workflow.md](references/project-onboarding-workflow.md) | Unfamiliar project onboarding |
| [rknn-deployment.md](references/rknn-deployment.md) | Deployment strategies, PC-side vs board-side |

## Operating Rules
- Treat the selected target headers and version-matched official examples as the API contract; bundled signatures are navigation aids.
- Distinguish host dtype from graph precision. `RKNN_TENSOR_FLOAT32` or `want_float=1` does not prove FP32 NPU execution.
- Never infer Toolkit2 normalization or INT8 graph precision from a `.rknn` filename, ONNX input dtype, host C buffer type, `pass_through`, `want_float`, or Runtime convenience conversion.
- Prefer DMA-BUF when ownership, layout, synchronization, and consumer support are proven. Virtual-address processing is a measured fallback, not automatically a defect.
- Do not describe `RKNN_FLAG_ASYNC_MASK` as a generic nonblocking or multithreaded execution API. Its previous-frame output semantics are runtime-version specific.
- Treat static-audit matches as candidates. Confirm call paths, sizes, ownership, cleanup, and deployed versions before assigning severity.
- Never claim zero-copy without identifying every allocation, fd/import, CPU mapping, cache operation, fence, and release point.
- Verify Toolkit2, model target, Runtime, driver, and headers before deployment or compatibility conclusions.

## Response Contract

For substantial diagnostics or reviews, report in this order:
1. Findings ordered by impact, with source location and confidence.
2. Evidence and violated invariant for each finding.
3. Recommended fix and a concrete regression or measurement method.
4. Coverage, exclusions, facts still unverified for the model conversion or target board, blocked decisions, and work still permitted.

## Quick Helpers
- `scripts/inspect-onnx-model.py`, `scripts/rknn-diag.sh`, `scripts/render-project-baseline.py`, `scripts/audit-rockchip-memory-safety.py` (`--preprocess` + `--preprocess-include DIR`), `scripts/collect-rockchip-crash-evidence.sh`
