---
name: ascend-pro
description: >
  Expert on Huawei Ascend inference and media pipelines — PyTorch/TF → ONNX conversion, ONNX-to-OM
  via ATC, zero-copy buffer flow, inference optimization, AscendCL/DVPP/AIPP API usage, device-environment
  baselining, and memory alignment. Use this skill whenever the user mentions Ascend, Atlas, CANN, ATC,
  AscendCL, DVPP, AIPP, OM model, NPU, model conversion, or Ascend inference pipelines. It replaces
  the old ascend-performance skill with broader scope.
---

# ascend-pro

Build or tune Ascend inference and media pipelines on Atlas devices. Covers: model conversion
(PyTorch/TF → ONNX → OM via ATC), runtime inference (AscendCL), media processing (DVPP, AIPP),
zero-copy analysis, and device-environment baselining.

Prefer C/C++ for product runtime; use Python for model conversion checks, env inspection, profiling.

## Workflow

1. **Initialize project context** — collect device evidence + generate `.agents/ascend-context.md` (see below).
2. **Identify the user's stage:**
   - **Model conversion** → route to [onnx-to-om.md](references/onnx-to-om.md) (PT/TF→ONNX→OM).
   - **Inference pipeline** → route to [zero-copy-inference.md](references/zero-copy-inference.md).
   - **API query** → route to [acl-api-reference.md](references/acl-api-reference.md) or [dvpp-api-reference.md](references/dvpp-api-reference.md).
3. **For pipeline work**: draw data path → prefer device-resident handoff → prove copies → tune one bottleneck.

## Session Start: Device Identity Verification

**Every session** must verify the current device's serial number before using any cached context.

### Step 1 — Read existing context (if any)

If `.agents/ascend-context.md` exists, read it. Extract the stored `chip_sn`.

### Step 2 — Get current device serial number

Ask the user to run this **one command** on the target device:

```bash
npu-smi info -t board 2>/dev/null | grep -i "Chip Sn"
```

The user pastes back the serial number (e.g., `Chip Sn: 0123456789`).

### Step 3 — Compare

| Result | Action |
|---|---|
| **Match** (same device) | Cached context is valid. Proceed with `.agents/ascend-context.md`. |
| **Mismatch** (different device) | The cached context is for a different physical device. **Do not use it.** Run full initialization below for the new device. Append the new context as a separate device section. |
| No `.agents/ascend-context.md` exists | Run full initialization below. |

> ⚠️ Even if the device model is the same (both are Ascend310P), different serial numbers mean
> different physical hardware with potentially different drivers, firmware, or CANN configurations.
> Always verify.

### Full Initialization: `.agents/ascend-context.md`

When no valid context exists for the current device, generate one:

```
.agents/ascend-context.md
```

This file combines **device baseline + API context** so every session starts with the same facts.

### How to generate it

**Step 1 — Collect device evidence**

If the user has device access:
```bash
# Run on target device
bash scripts/detect-ascend-env.sh      # device model, NPU, kernel, CANN paths
bash scripts/collect-ascend-debug.sh   # .so, symbols, headers, linkages
npu-smi info
npu-smi info -t board                  # chip serial number (context key)
```
If no direct access: give the user the command checklist from [first-response-template.md](references/first-response-template.md) and ask them to paste output.

> ⚠️ **Device serial number is mandatory.** The chip serial number (`chip_sn`) uniquely identifies a physical Ascend device.
> Even the same device model with a different driver version is a **different context**. Do not reuse a cached context
> without verifying the serial number matches.

**Step 2 — Build baseline**
```bash
python3 scripts/render-project-baseline.py pasted-evidence.txt -o .agents/ascend-context.md
```
This parses device evidence (including `chip_sn`) and emits a structured baseline section.

**Step 3 — Append API context**

After the baseline, append a section with:
- The key API signatures from [acl-api-reference.md](references/acl-api-reference.md) that match the project's usage.
- Memory alignment rules from [memory-alignment.md](references/memory-alignment.md) (stride alignment, buffer size formulas).
- Any active AIPP config or conversion notes from current project.
- A pointer to `ctx_search(source: "ascend-...")` for deeper official docs.

**Step 4 — Set context ID with serial number**
- Context ID format: `{chip_sn}-{device_model}-{host_or_container}-{purpose}`.
  Example: `SN0123456789-Ascend310P-host-video-infer`
- Review the baseline with [baseline-review-checklist.md](references/baseline-review-checklist.md).
- If multiple devices, select one active context.
- The `.agents/ascend-context.md` file is then the canonical project context for all future turns.

### When to regenerate
- New device evidence is collected (different hardware, CANN update).
- Project switches deployment target.
- Onboarding a new team member or fresh agent session.

### Read the existing context
When `.agents/ascend-context.md` already exists, read it first before requesting new evidence — it may already contain the needed baseline.

## Start Here (quick helpers)

- `scripts/detect-ascend-env.sh`
- `scripts/collect-ascend-debug.sh`
- `scripts/render-project-baseline.py`

## References

### Device & environment (carried forward from ascend-performance)

| File | When to read |
|---|---|
| [platform-matrix.md](references/platform-matrix.md) | Device families, CANN surfaces, what to confirm |
| [device-scoped-context.md](references/device-scoped-context.md) | Multiple device models, containers, or CANN installs |
| [version-audit.md](references/version-audit.md) | CANN version compatibility checks |
| [project-onboarding-workflow.md](references/project-onboarding-workflow.md) | Unfamiliar project onboarding |
| [device-evidence-workflow.md](references/device-evidence-workflow.md) | Collecting device info from user |
| [first-response-template.md](references/first-response-template.md) | First reply when no device baseline exists |
| [device-command-checklist.md](references/device-command-checklist.md) | Exact commands for user to run on device |
| [baseline-review-checklist.md](references/baseline-review-checklist.md) | Reviewing baseline draft output |
| [baseline-file-convention.md](references/baseline-file-convention.md) | Storing baseline in project |
| [acl-dvpp-pipeline.md](references/acl-dvpp-pipeline.md) | Camera, decode, DVPP, AIPP, memory flow, stream sync |
| [ascend-deployment.md](references/ascend-deployment.md) | ATC, OM artifacts, ACL model loading, deployment |
| [perf-debugging.md](references/perf-debugging.md) | Throughput, CPU/NPU load, hidden copies, sync waits |

### New references for ascend-pro

| File | When to read |
|---|---|
| [onnx-to-om.md](references/onnx-to-om.md) | Model conversion — PyTorch→ONNX, TF→ONNX, ONNX→OM via ATC, dynamic shape, precision tuning |
| [zero-copy-inference.md](references/zero-copy-inference.md) | Zero-copy buffer flow, anti-patterns, async pipeline design, copy verification |
| [acl-api-reference.md](references/acl-api-reference.md) | AscendCL API signatures, parameters, calling sequences, error handling |
| [dvpp-api-reference.md](references/dvpp-api-reference.md) | DVPP API signatures, VPC/JPEG/VDEC/VENC parameters, format constraints |
| [aipp-config-reference.md](references/aipp-config-reference.md) | AIPP config template, static/dynamic modes, CSC matrix, insert_op_conf |
| [memory-alignment.md](references/memory-alignment.md) | **Critical**: stride alignment, buffer size formulas, per-operation constraints |

### Indexed official docs

Use `ctx_search(source: "ascend-...")` to retrieve excerpts:

| Source label | Content |
|---|---|
| `ascend-atc-onnx-conversion` | ATC ONNX model conversion quick start |
| `ascend-atc-params` | ATC parameter reference |
| `ascend-aipp-config-template` | Full AIPP config template with defaults |
| `ascend-aipp-howto` | How to enable AIPP |
| `ascend-aipp-dynamic-example` | Dynamic AIPP parameter structure |
| `ascend-acl-api-list` | AscendCL API list per CANN version |
| `ascend-acl-flow` | AscendCL call flow overview |
| `ascend-acl-model-exec-flow` | Model execution flow |
| `ascend-dvpp-vpc-dev-guide` | DVPP VPC development guide |
| `ascend-dvpp-intro` | DVPP API introduction |

## Device-Scoped Context

Runtime context = `device model + driver/firmware + CANN root + .so set + headers + container/host + OM artifact`.

- Do not mix `libascendcl.so`, DVPP libs, headers, or OM artifacts across device models.
- Maintain separate context blocks (e.g., `Ascend310P-host`, `Atlas200I-A2-container`).
- State which context is active before proposing code.
- Design explicit runtime selection for multi-device projects.

## Design Checklist

- [ ] Input origin: V4L2, FFmpeg, OpenCV, GStreamer, custom allocator, preloaded tensors?
- [ ] Pixel format, W×H, stride, channel order, normalization, tensor layout at each hop?
- [ ] Does next stage consume device memory directly or force a host-visible buffer?
- [ ] Should AIPP absorb resize/CSC/crop/normalization instead of CPU code?
- [ ] Is DVPP used only where the device + CANN support the format + operation combination?
- [ ] Do ACL I/O buffers use stable pools, not per-frame alloc?
- [ ] Does CPU postprocess dominate after NPU inference?
- [ ] Does async code still block on stream sync, output readback, queue waits, or logging?

## Operating Rules

- Keep data in device memory after preprocessing when APIs allow.
- Treat repeated `aclrtMemcpy`, CPU image conversion, full tensor readback as suspects.
- Don't claim zero-copy until every ownership transfer, boundary, sync, and format change is explained.
- Prefer explicit stage timing over whole-pipeline timing for regression debugging.
- Check version compatibility before deep changes — mismatched CANN/driver/firmware/toolkit/OM is a frequent root cause.
- Separate verified facts from device-specific assumptions.

## Non-Goals

- Not generic CUDA, TensorRT, OpenVINO, or Android guidance.
- Not training-cluster or HCCL tuning unless task is explicitly Ascend training.
- Not assuming all devices have DVPP, AIPP, or identical media capabilities — require evidence.

## Deliverables

For substantial tasks produce:
1. Device-scoped project baseline
2. Data-flow or buffer-flow summary
3. Bottleneck hypothesis
4. Code or config changes
5. Measurement method
6. Unverified device-specific risks
