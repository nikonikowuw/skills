---
name: rknn-pro
description: >
  Build, diagnose, review, or optimize Linux inference and media pipelines
  using Rockchip RKNN, RKNN-Toolkit2, RKNN Runtime, RGA/librga, MPP,
  DMA-BUF, or RK3568/RK3576/RK3588 SoCs. Use when a task mentions RKNN
  conversion, NPU operators, tensor stride, zero-copy pipelines,
  multi-model scheduling, BSP compatibility, memory corruption, crashes,
  or kernel-facing safety. Do not use for Ascend/ACL, TensorRT/CUDA,
  OpenVINO, or non-Rockchip Linux DMA-BUF.
---

# rknn-pro

Build or tune Rockchip inference and media pipelines on RK3568, RK3576, and RK3588 Linux systems.

## Workflow

1. Classify the task before collecting evidence. Source-only review, conversion planning, and API explanation can start without board access; mark board-dependent conclusions as unverified.
2. Before developing or approving model input, preprocessing, zero-copy tensor layout, quantization-sensitive postprocessing, or deployment configuration, pass the Model Conversion Evidence Gate below. Keep model provenance separate from device provenance.
3. When ABI, allocator, driver, compatibility, or performance facts matter, select one device context. Run the bundled diagnostic on that board and render `.agents/rknn-context.md` in the target project.
4. Read only the references needed for the active task:
   - Model conversion or quantization: [model-conversion.md](references/model-conversion.md), then [npu-op-compatibility.md](references/npu-op-compatibility.md) for operator or precision issues.
   - YOLO detection model deployment: [yolo-deployment-cookbook.md](references/yolo-deployment-cookbook.md).
   - RKNN Runtime API question: [api-quick-reference.md](references/api-quick-reference.md), then [rknn-api-reference.md](references/rknn-api-reference.md).
   - RGA API question: [api-quick-reference.md](references/api-quick-reference.md), then [rga-api-reference.md](references/rga-api-reference.md).
   - MPP API question: [api-quick-reference.md](references/api-quick-reference.md), then [mpp-api-reference.md](references/mpp-api-reference.md).
   - DMA-BUF or inference pipeline: [zero-copy-pipeline.md](references/zero-copy-pipeline.md); for an implementation audit, follow [zero-copy-check.md](references/zero-copy-check.md) and dispatch the required subagent.
   - Multi-model or cascade scheduling: [multi-model-scheduling.md](references/multi-model-scheduling.md).
   - SDK upgrade, tensor allocation, alignment, or stride: [memory-alignment.md](references/memory-alignment.md).
   - Crash or full safety audit: follow every phase in [project-crash-risk-audit.md](references/project-crash-risk-audit.md) and use [known-crash-patterns.md](references/known-crash-patterns.md) only as evidence anchors.
   - Performance or latency diagnosis: [perf-debugging.md](references/perf-debugging.md).
   - Version or BSP compatibility: [version-audit.md](references/version-audit.md).
   - Multiple boards or containers: [device-scoped-context.md](references/device-scoped-context.md).
   - Deployment strategy (PC-side vs board-side): [rknn-deployment.md](references/rknn-deployment.md).
   - Unfamiliar project onboarding: [project-onboarding-workflow.md](references/project-onboarding-workflow.md).
   - SoC capability or topology comparison: [soc-matrix.md](references/soc-matrix.md).
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
- [ ] RGA dimensions, strides, and ROI coordinates strictly validated for hardware alignment?
- [ ] RGA destination matches NPU queried `w_stride` / `h_stride`?
- [ ] Math overflow / out-of-bounds proven impossible for strides/ROI?
- [ ] Resource acquisition (fd/mmap) paired with release across all paths?
- [ ] Queue limits enforced? Cache sync / fences ordered correctly?
- [ ] NPU cores assigned and memory budgeted for multi-model?

## Known Gotchas

- Two-stage cascade crops (e.g. from bounding boxes) often produce unaligned coordinates causing RGA corruption; snap to 4-byte boundaries before calling RGA → [rga-api-reference.md](references/rga-api-reference.md)
- `RKNN_TENSOR_FLOAT32` ≠ NPU FP32 execution; it triggers host→device format conversion → [memory-alignment.md](references/memory-alignment.md)
- `RKNN_FLAG_ASYNC_MASK` retrieves **previous** frame's output, not current; its previous-frame output semantics are runtime-version specific → [multi-model-scheduling.md](references/multi-model-scheduling.md)
- RGA `wrapbuffer_fd` with 4 args assumes tight stride; use 6-arg form → [rga-api-reference.md](references/rga-api-reference.md)
- `rknn_create_mem` must use max(tensor_size, stride_size) or SIGSEGV → [memory-alignment.md](references/memory-alignment.md)
- Missing `imcheck` before RGA operations causes silent corruption → [rga-api-reference.md](references/rga-api-reference.md)
- `do_quantization=True` proves only what was requested, not actual graph precision → [model-conversion.md](references/model-conversion.md)

## Operating Rules

- Precision inquiry → read Toolkit2 build report. Missing? → mark precision as `unknown`, list in gate-blocked report §4.
- Normalization inquiry → read preserved conversion config/log. Do not infer from ONNX input dtype, `.rknn` filename, host C buffer type, `pass_through`, `want_float`, or Runtime convenience conversion. Missing? → mark as `unknown`.
- DMA-BUF feasibility → verify ownership + layout + sync + consumer support for every hop. Any unproven? → use virtual-address path, note as measured fallback.
- RGA image processing → verify all dimensions, ROI coordinates, and strides are strictly aligned to hardware boundaries (e.g. 4-byte/even). ALWAYS mandate `imcheck()` validation before `improcess/imresize/imcrop`.
- `RKNN_FLAG_ASYNC_MASK` question → read [multi-model-scheduling.md](references/multi-model-scheduling.md). Cite the previous-frame output rule; do not generalize to "nonblocking" or "multithreaded".
- Zero-copy claim → identify every allocation, fd/import, CPU mapping, cache operation, fence, and release point. Any gap? → reject the claim.
- Static-audit match → trace call paths, sizes, ownership, cleanup, and deployed versions before assigning severity. Matches are candidates, not confirmed findings.
- Treat the selected target headers and version-matched official examples as the API contract; bundled signatures are navigation aids.
- Verify Toolkit2, model target, Runtime, driver, and headers before deployment or compatibility conclusions.

## Response Contract

For substantial diagnostics or reviews, report in this order:
1. Findings ordered by impact, with source location and confidence.
2. Evidence and violated invariant for each finding.
3. Recommended fix and a concrete regression or measurement method.
4. Coverage, exclusions, facts still unverified for the model conversion or target board, blocked decisions, and work still permitted.

## Quick Helpers

| When | Run |
|---|---|
| Have ONNX artifact, need contract | `scripts/inspect-onnx-model.py model.onnx` |
| Need device baseline | `scripts/rknn-diag.sh -o evidence.txt` on board |
| Build baseline doc from evidence | `scripts/render-project-baseline.py evidence.txt -o .agents/rknn-context.md` |
| Source safety audit | `scripts/audit-rockchip-memory-safety.py --preprocess src/` |
| Board crashed, collect evidence | `scripts/collect-rockchip-crash-evidence.sh [PID]` on board |
| Have latency logs, need stats | `scripts/summarize-stage-latency.py < log.txt` |
