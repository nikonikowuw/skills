---
name: rknn-pro
description: >
  Load when the user asks to build, diagnose, review, or optimize Linux inference and media pipelines that use Rockchip RKNN, RKNN-Toolkit2, RKNN Runtime/RKNPU2, RGA/librga, MPP, DMA-BUF, or RK3568/RK3576/RK3588-class SoCs. Use this skill whenever a task mentions RKNN model conversion or quantization, Rockchip NPU operators, tensor stride or alignment, zero-copy camera/video pipelines, multi-model scheduling, runtime/BSP compatibility, high CPU or latency, memory corruption, service crashes, or kernel-facing safety, even when the user does not explicitly ask for an RKNN expert. Do NOT use this skill for frontend changes, web backend development, or non-Rockchip AI tasks.
---

# rknn-pro

Build or tune Rockchip inference and media pipelines on RK3568, RK3576, and RK3588 Linux systems.

## Always Read
- If `.agents/context/rknn-context/` exists in the target project, read the active machine's `.md` file to load board-specific context BEFORE starting diagnosis or design.
- If `.agents/rknn-model-context.md` exists, read it BEFORE making decisions about tensor layouts or normalization.

## Workflow

1. Classify the task before collecting evidence. Source-only review, conversion planning, and API explanation can start without board access; mark board-dependent conclusions as unverified.
2. Before developing or approving model input, preprocessing, zero-copy tensor layout, quantization-sensitive postprocessing, or deployment configuration, pass the Model Conversion Evidence Gate below. Keep model provenance separate from device provenance.
3. When ABI, allocator, driver, compatibility, or performance facts matter, select one device context. Run the bundled diagnostic on that board and render `.agents/context/rknn-context/{machine_id}.md` in the target project.
4. Read only the references needed for the active task:
   - Model conversion or quantization: [model-conversion.md](references/model-conversion.md), then [npu-op-compatibility.md](references/npu-op-compatibility.md) for operator or precision issues.
   - YOLO detection model deployment: [yolo-deployment-cookbook.md](references/yolo-deployment-cookbook.md).
   - RKNN Runtime API question: start with [api-quick-reference.md](references/api-quick-reference.md); add [rknn-api-reference.md](references/rknn-api-reference.md) only for lifecycle, ownership, version, tensor-layout, or subsystem-boundary questions.
   - RGA API question in an RKNN pipeline: start with [api-quick-reference.md](references/api-quick-reference.md); add [rga-api-reference.md](references/rga-api-reference.md) only for lifecycle, core/format constraints, version, buffer layout, or subsystem-boundary questions.
   - MPP API question in an RKNN pipeline: start with [api-quick-reference.md](references/api-quick-reference.md); add [mpp-api-reference.md](references/mpp-api-reference.md) only for lifecycle, ownership, buffer mode, version, or subsystem-boundary questions.
   - DMA-BUF or inference pipeline: [zero-copy-pipeline.md](references/zero-copy-pipeline.md); for an implementation audit, follow [zero-copy-check.md](references/zero-copy-check.md). For a large repository or independent call-path investigation, dispatch a subagent when one is available; for a small scope or no subagent availability, run the same checklist locally and report coverage.
   - Multi-model or cascade scheduling: [multi-model-scheduling.md](references/multi-model-scheduling.md).
   - SDK upgrade, tensor allocation, alignment, or stride: [memory-alignment.md](references/memory-alignment.md).
   - Crash or full safety audit: follow every phase in [project-crash-risk-audit.md](references/project-crash-risk-audit.md) and use [known-crash-patterns.md](references/known-crash-patterns.md) only as evidence anchors.
   - Performance or latency diagnosis: [perf-debugging.md](references/perf-debugging.md).
   - RGA kernel errors, debug nodes, or HAL logging: [rga-debug-guide.md](references/rga-debug-guide.md); use the error → root cause map in [rga-api-reference.md](references/rga-api-reference.md).
   - Version or BSP compatibility: [version-audit.md](references/version-audit.md).
   - Multiple boards or containers: [device-scoped-context.md](references/device-scoped-context.md).
   - Deployment strategy (PC-side vs board-side): [rknn-deployment.md](references/rknn-deployment.md).
   - Unfamiliar project onboarding: [project-onboarding-workflow.md](references/project-onboarding-workflow.md).
   - SoC capability or topology comparison: [soc-matrix.md](references/soc-matrix.md).
5. Separate observed facts, source-derived findings, hypotheses, and model- or board-dependent unknowns in the final answer.

Resolve `scripts/...` and `references/...` relative to this `SKILL.md`, not the target repository. Run bundled scripts by absolute path while keeping the shell working directory at the target project so generated context and reports land there.

## Model Conversion Evidence Gate (`.agents/rknn-model-context.md`)

Set one overall gate status before using it:

- `passed`: the model-dependent evidence below establishes the intended end-to-end contract.
- `blocked`: the requested model-dependent decision lacks required evidence. List only the decisions that are blocked and continue independent work.
- `not-applicable`: the requested conclusion does not depend on model provenance or tensor semantics, such as a simple API signature explanation, source-only cleanup audit, queue ownership review, or device baseline collection.

For a model-dependent decision, create or update the model context using [model-conversion-manifest.md](references/model-conversion-manifest.md) and preserve the evidence chain:

- [ ] ONNX artifact path and SHA-256; opset, inputs/outputs, shapes, dtypes, dynamic dimensions, metadata, and possible graph-embedded preprocessing. Run `python3 <skill-root>/scripts/inspect-onnx-model.py model.onnx` when the artifact is available.
- [ ] Exact conversion script/config, Toolkit2 version, target platform, and verbose conversion log.
- [ ] Exact `rknn.config()` input contract: `mean_values`, `std_values`, channel order, layout, raw value range, and any reorder/quantization options.
- [ ] Exact `rknn.build()` request, including `do_quantization`, quantized dtype/algorithm, calibration dataset identity, and calibration preprocessing.
- [ ] Build report or other Toolkit2 evidence that confirms actual graph/layer precision, including mixed precision; `do_quantization=True` proves only what was requested.
- [ ] RKNN artifact path and SHA-256, linked to the conversion evidence above.
- [ ] Runtime-queried input/output attributes: type, format, dimensions, strides, quantization type, zero point, and scale.

Assess all three possible normalization locations as **confirmed-present**, **confirmed-absent**, or **unknown**: ONNX graph, Toolkit2 `mean_values`/`std_values`, and application/RGA preprocessing. Mark the gate `passed` only when none remains unknown, the evidence establishes one intended end-to-end normalization contract, and actual graph/layer precision is confirmed. A graph inspection can identify candidates but cannot prove the training contract.

If only a `.rknn` file or host-side C buffer is available, record normalization and graph INT8 status as **unknown**. Runtime tensor attributes may confirm the external I/O contract but do not recover Toolkit2 normalization settings or prove whole-graph precision. Continue unrelated source review, but do not finalize preprocessing, `pass_through`, zero-copy input layout, quantization-sensitive postprocessing, or production deployment choices by guessing.

When the gate is `blocked`, make the boundary explicit in the response. Report:

1. A status for ONNX-embedded normalization, Toolkit2 normalization, application normalization, and actual graph/layer precision. Use `unknown` when evidence is missing.
2. Missing ONNX identity and contract fields by name: SHA-256, IR/opset, producer/metadata, every input/output name, shape, dtype, and dynamic dimension, plus input-prefix preprocessing candidates.
3. Missing conversion evidence: script/config, Toolkit2 version and target, build request/log/report, calibration provenance, mixed-precision configuration, and RKNN SHA-256.
4. Decisions blocked by those unknowns and the evidence needed to unblock them.
5. Work that may continue now because its correctness does not depend on the missing model facts.

## Initialization Checklist (`.agents/context/rknn-context/{machine_id}.md`)

When board-specific facts matter or fingerprint mismatches:
- [ ] Run `<skill-root>/scripts/rknn-diag.sh` on device (or use the checklist in [device-baseline-workflow.md](references/device-baseline-workflow.md)).
- [ ] Build baseline from the target project: `python3 <skill-root>/scripts/render-project-baseline.py pasted-evidence.txt --write-default`.
- [ ] The `--write-default` flag auto-detects `machine_id` and writes to `.agents/context/rknn-context/{machine_id}.md`. Use `--context-id <label>` to override the auto-detected ID.
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
- [ ] Model evidence gate status recorded; `passed` for model-dependent decisions or `not-applicable` for independent work?
- [ ] For a model-dependent decision, graph precision confirmed from a build report rather than host dtype?
- [ ] CMake uses `size_with_stride` gracefully with older headers?
- [ ] RKNN allocation covers the authoritative queried and physical-layout byte requirements for the selected Runtime/header?
- [ ] RGA dimensions, strides, and ROI coordinates validated for the selected core, format, and read mode?
- [ ] RGA destination matches NPU queried `w_stride` / `h_stride`?
- [ ] Math overflow / out-of-bounds proven impossible for strides/ROI?
- [ ] **RGA DMA-BUF lifecycle — `importbuffer_fd` once per pool, not per-frame `wrapbuffer_fd`?** (see [known-crash-patterns.md](references/known-crash-patterns.md) — RGA cascade)
- [ ] **RGA core load balancing — `im_set_core_mask()` set to use all available RGA cores?** (default single-core affinity is a common amplifier)
- [ ] **RGA buffer API uniform — all buffers use handle-based or all fd-based, no mixing?**
- [ ] **RGA resolution/scaling within core limits?** (RGA3 min 68px, max 1/8×–8×; RGA2 min 2px, max 1/16×–16×)
- [ ] **RGA physical memory below 4 GB for RGA2?** (DMA32 heap flag if system has >4 GB RAM)
- [ ] **FBC/AFBC buffer layout matches declared read mode alignment?** (AFBC16×16, AFBC32×8, etc.)
- [ ] **librga and kernel driver versions compatible?** (librga ≥ 1.4.0 requires driver ≥ v1.2.0)
- [ ] **RGA-to-RKNN synchronization present?** (IM_SYNC or fence before NPU reads RGA output)
- [ ] Resource acquisition (fd/mmap) paired with release across all paths?
- [ ] Queue limits enforced? Cache sync / fences ordered correctly?
- [ ] NPU cores assigned and memory budgeted for multi-model?

## Known Gotchas

- RGA ROI and stride constraints vary by core, pixel format, and read mode; derive them from the selected target instead of applying a universal 4-byte pixel rule → [rga-api-reference.md](references/rga-api-reference.md)
- `RKNN_TENSOR_FLOAT32` ≠ NPU FP32 execution; it triggers host→device format conversion → [memory-alignment.md](references/memory-alignment.md)
- `RKNN_FLAG_ASYNC_MASK` retrieves **previous** frame's output, not current; its previous-frame output semantics are runtime-version specific → [multi-model-scheduling.md](references/multi-model-scheduling.md)
- RGA `wrapbuffer_fd` with 4 args assumes tight stride; use 6-arg form → [rga-api-reference.md](references/rga-api-reference.md)
- RKNN allocation must cover the authoritative tensor and physical-layout requirements; an undersized buffer is dangerous, but a crash alone does not prove one fixed size formula or cause → [memory-alignment.md](references/memory-alignment.md)
- RGA validation helpers are version- and operation-dependent; use the installed validation path when applicable, but do not treat it as proof of allocation, lifetime, or synchronization safety → [rga-api-reference.md](references/rga-api-reference.md)
- `do_quantization=True` proves only what was requested, not actual graph precision → [model-conversion.md](references/model-conversion.md)
- **RGA3 minimum dimension is 68 px** (vs 2 px for RGA2); small detection crops fail on RGA3 → [rga-api-reference.md](references/rga-api-reference.md)
- **RGA3 scaling limit is 1/8×–8×** (vs 1/16×–16× for RGA2); extreme resize ratios need multi-pass or RGA2 routing → [rga-api-reference.md](references/rga-api-reference.md)
- **RGA2 MMU is 32-bit only**; buffers above 4 GB cause `RGA_MMU unsupported Memory larger than 4G!` → [known-crash-patterns.md](references/known-crash-patterns.md)
- **RK3588 RGA3+RGA2 scaling jitter** — different interpolation algorithms between core types cause per-frame visual inconsistency; pin to one core type → [known-crash-patterns.md](references/known-crash-patterns.md)
- **librga ≥ 1.4.0 requires driver ≥ v1.2.0**; mismatches cause pink/green color shift in CSC → [known-crash-patterns.md](references/known-crash-patterns.md)
- **Mixing `wrapbuffer_handle` and `wrapbuffer_fd`** in the same operation is rejected by librga → [known-crash-patterns.md](references/known-crash-patterns.md)
- **FBC/AFBC buffer alignment** must match block size (16×16, 32×8, etc.); mismatch causes hardware timeout, not clean rejection → [rga-api-reference.md](references/rga-api-reference.md)

## Operating Rules

- Precision inquiry → read Toolkit2 build report. Missing? → mark precision as `unknown`, list in gate-blocked report §4.
- Normalization inquiry → read preserved conversion config/log. Do not infer from ONNX input dtype, `.rknn` filename, host C buffer type, `pass_through`, `want_float`, or Runtime convenience conversion. Missing? → mark as `unknown`.
- DMA-BUF feasibility → verify ownership + layout + sync + consumer support for every hop. If any is unproven, keep the measured known-good path or block the zero-copy claim until evidence closes the gap; do not select a virtual-address path merely because evidence is missing.
- RGA image processing → derive dimension, ROI, and stride constraints from the selected core, format, read mode, installed headers, and version-matched guide. Use the available validation API when applicable and check its return status; still prove allocation size, ownership, lifetime, and synchronization separately.
- RGA kernel error or dmesg output → start from the Complete Kernel Error → Root Cause Map in [rga-api-reference.md](references/rga-api-reference.md); follow the debug workflow in [rga-debug-guide.md](references/rga-debug-guide.md). Do not guess from one log line.
- RGA resolution/scaling failure → check per-core limits (RGA2: 2–8192 px input, 1/16–16× scale; RGA3: 68–8176 px, 1/8–8×). If the request exceeds limits, split passes or route to a different core.
- RGA color error (pink/green tint) → check librga/driver version match first; then CSC color space configuration.
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
| Have ONNX artifact, need contract | `python3 <skill-root>/scripts/inspect-onnx-model.py model.onnx` |
| Need device baseline | `<skill-root>/scripts/rknn-diag.sh -o evidence.txt` on board |
| Build baseline doc from evidence | `python3 <skill-root>/scripts/render-project-baseline.py evidence.txt -o .agents/rknn-context.md` |
| Source safety audit | `python3 <skill-root>/scripts/audit-rockchip-memory-safety.py --preprocess src/` |
| Board crashed, collect evidence | `<skill-root>/scripts/collect-rockchip-crash-evidence.sh [PID]` on board |
| Have latency logs, need stats | `python3 <skill-root>/scripts/summarize-stage-latency.py log.txt` |
| Run repeatable trigger/behavior evals | `python3 <skill-root>/scripts/run-skill-evals.py --help` |
| RGA kernel errors, need debug info | See [rga-debug-guide.md](references/rga-debug-guide.md) for debug nodes and HAL logging |
| Check RGA/librga versions | `cat /sys/kernel/debug/rkrga/driver_version` + `strings librga.so \| grep version` |
| Check RGA core load balance | `cat /proc/interrupts \| grep rga` on board |
