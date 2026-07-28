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

1. **Initialize project context** — collect device evidence + generate `.agent/ascend-pro/context/{machine_id}.md` (see [context.md format](#contextmd-document-format)).
2. **Identify the user's stage:**
   - **Model conversion** → route to [onnx-to-om.md](references/onnx-to-om.md) (PT/TF→ONNX→OM).
   - **Inference pipeline** → route to [zero-copy-inference.md](references/zero-copy-inference.md).
   - **API query** → route to [acl-api-reference.md](references/acl-api-reference.md) or [dvpp-api-reference.md](references/dvpp-api-reference.md).
3. **For pipeline work**: draw data path → prefer device-resident handoff → prove copies → tune one bottleneck.

## Session Start: Device Identity Verification

**Every session** must verify the current device's serial number before using any cached context.

### Step 1 — Get device machine-id

Ask the user to run this command on the target device:

```bash
cat /etc/machine-id
```

The user pastes back the output (a 32-character hex string). This is used as the device
context key — it is stable, unique per machine, and available on all Linux systems including
containers (where it inherits the host's ID).

> 💡 `/etc/machine-id` is preferred over `npu-smi` because it works regardless of driver
> version, container permissions, or NPU model. The machine-id is the device identity key;
> NPU-specific details (chip model, CANN version) are captured in the context file itself.

If `/etc/machine-id` is unavailable (unusual), fall back to:
```bash
cat /var/lib/dbus/machine-id 2>/dev/null || echo "unknown"
```

### Step 2 — Look up device context by machine-id

Check for `.agent/ascend-pro/context/{machine_id}.md`:

| Result | Action |
|---|---|
| **File exists** | Cached context is valid (machine-id guarantees match). Read and proceed. |
| **File missing** | Run [Full Initialization](#full-initialization-agentascend-procontextmachine_idmd) below for this device. |

> ⚠️ The machine-id uniquely identifies a physical machine. Even if the device model is the
> same (both are Ascend310P), different machines may have different drivers, firmware, or
> CANN configurations. Always start with the machine-id.

When the file exists, read `.agent/ascend-pro/context/{machine_id}.md` to restore project context.

### Full Initialization: `.agent/ascend-pro/context/{machine_id}.md`

When no valid context exists for the current device, generate one:

```
.agent/ascend-pro/context/{machine_id}.md
```

This file combines **device baseline + API context** in a well-archived format (see [context.md format](#contextmd-document-format)) so every session starts with the same facts.

### How to generate it

**Step 1 — Collect device evidence**

If the user has device access:
```bash
# Run on target device
bash scripts/detect-ascend-env.sh      # device model, NPU, kernel, CANN paths
bash scripts/collect-ascend-debug.sh   # .so, symbols, headers, linkages
cat /etc/machine-id                     # device context key
npu-smi info                            # NPU info
```
If no direct access: give the user the command checklist from [first-response-template.md](references/first-response-template.md) and ask them to paste output.

> ⚠️ **Machine ID is mandatory.** Used as the device context key (`machine_id`).

**Step 2 — Build baseline**

Use `--write-default` to auto-detect machine_id and write to the correct path:
```bash
python3 scripts/render-project-baseline.py pasted-evidence.txt --write-default
```

Or specify the path explicitly (substitute actual machine_id):
```bash
mkdir -p .agent/ascend-pro/context
python3 scripts/render-project-baseline.py pasted-evidence.txt -o .agent/ascend-pro/context/abc123def4567890abc123def4567890.md
```

This parses device evidence (including `machine_id`) and emits a structured baseline section.

> 💡 With `--write-default`, the script auto-detects `machine_id` from the pasted evidence (from `/etc/machine-id` or as a fallback from npu-smi) and writes to `.agent/ascend-pro/context/{machine_id}.md`.

**Step 3 — Append API context**

After the baseline, append a section with:
- The key API signatures from [acl-api-reference.md](references/acl-api-reference.md) that match the project's usage.
- Memory alignment rules from [memory-alignment.md](references/memory-alignment.md) (stride alignment, buffer size formulas).
- Any active AIPP config or conversion notes from current project.
- A pointer to `ctx_search(source: "ascend-...")` for deeper official docs.

**Step 4 — Set context ID**
- Context ID format: `{machine_id}-{device_model}-{host_or_container}-{purpose}`.
  Example: `abc123def456-Ascend310P-host-video-infer`
- Review the baseline with [baseline-review-checklist.md](references/baseline-review-checklist.md).
- If multiple devices, each gets its own file under `.agent/ascend-pro/context/`. Select one active context before coding.
- The `.agent/ascend-pro/context/{machine_id}.md` file is then the canonical project context for all future turns.

### When to regenerate
- New device evidence is collected (different hardware, CANN update).
- Project switches deployment target.
- Onboarding a new team member or fresh agent session.
- To regenerate, simply re-run the [How to generate it](#how-to-generate-it) steps — the output path is already determined by machine_id.

### context.md Document Format

Each device context file is stored at `.agent/ascend-pro/context/{machine_id}.md`, keyed by the machine ID
(from `/etc/machine-id`). This allows multiple machines to coexist — every physical machine gets its own
file. The format is consistent and well-archived so it can be reliably parsed by both human readers and
future agent sessions.

```markdown
# Ascend Device Context — {machine_id}

**File**: `.agent/ascend-pro/context/{machine_id}.md`

---
## Context Metadata

Identification and provenance for this context document.

- **Context ID**: `{machine_id}-{device_model}-{host_or_container}-{purpose}`
  - Example: `abc123def4567890abc123def4567890-Ascend310P-host-video-infer`
- **Machine ID**: `abc123def4567890abc123def4567890`  *(from `/etc/machine-id` — filename basis)*
- **Device Model**: Ascend310P / Atlas 200I A2 / ...
- **Deployment**: host | container | docker
- **Purpose**: video-infer | model-conversion | benchmark | ...
- **CANN Version**: x.x.x
- **Driver Version**: x.x.x
- **Firmware Version**: x.x.x
- **Created**: YYYY-MM-DD
- **Last Verified**: YYYY-MM-DD
- **Verification Checklist**: [baseline-review-checklist.md](references/baseline-review-checklist.md)

---
## Device Baseline

### Chip Identity
- serial number, model, device nodes (`/dev/davinci*`)

### Kernel and OS
- kernel version, OS release

### CANN and Tools
- `ASCEND_HOME_PATH`, `ASCEND_TOOLKIT_HOME`
- `atc --version`, `npu-smi info`

### Userspace Libraries
- Paths to `libascendcl.so`, `libacl_dvpp.so`, `libacl_op_compiler.so`, `libge_runner.so`
- Which copy the project actually uses (linkage evidence)

### ABI and Symbols
- ACL runtime, memory, model, DVPP symbol presence
- Any symbol mismatches vs. intended integration

### Project Build Configuration
- Header roots (`-I` / `include_directories`)
- Library roots (`-L` / `link_directories`)
- SDK paths, dlopen usage

### Model Artifacts
- OM files (path, provenance, conversion command)
- AIPP config files
- Dynamic shape / precision settings

---
## API Context

Key AscendCL API signatures relevant to the project, extracted from [acl-api-reference.md](references/acl-api-reference.md):

| API | Signature | Notes |
|---|---|---|
| aclrtMalloc | `aclError aclrtMalloc(void **devPtr, size_t size, aclrtMemMallocPolicy policy)` | 64-byte alignment |
| ... | ... | ... |

Key DVPP API signatures from [dvpp-api-reference.md](references/dvpp-api-reference.md):

| API | Operation | Alignment Constraints |
|---|---|---|
| acldvppVpcResizeAsync | resize | W: 16-align, H: 2-align |
| ... | ... | ... |

---
## Memory Alignment Rules

From [memory-alignment.md](references/memory-alignment.md). Critical for buffer allocation:

| Operation | Width Align | Height Align | Stride Formula | Buffer Size Formula |
|---|---|---|---|---|
| VPC resize | 16 | 2 | `align(width, 16)` | ... |
| JPEG decode (YUV) | 16 | 1 | ... | ... |
| Model input | varies | varies | ... | ... |

> ⚠️ Always recalculate buffer sizes from actual resolution, device constraints, and operation type.

---
## AIPP Configuration

- **Mode**: static | dynamic
- **Config file** (for static): `path/to/aipp.cfg`
- **CSC matrix**: RGB→BGR / YUV→RGB / ...
- **Mean / Std**: `mean_chn_0: 128 mean_chn_1: 128 mean_chn_2: 128`
- **Crop**: `crop_size_w: 224 crop_size_h: 224`
- **Dynamic AIPP params** (if applicable): rotation, padding

---
## Conversion Notes

- **Source framework**: PyTorch | TensorFlow | ...
- **ONNX export opset**: 15 / 17 / ...
- **ATC command**: `atc --model=model.onnx --framework=5 --output=model --soc_version=Ascend310P3 ...`
- **Dynamic shape** (if any): `--input_shape_range="images:[1,3,224,224-640]"`
- **Precision**: FP16 | INT8 | mixed

---
## Device-Scoped Runtime Contexts

When multiple devices exist (e.g., container + host), maintain one section per context:

### Host (Ascend310P)
```
- Context ID: abc123def4567890abc123def4567890-Ascend310P-host-video-infer
- CANN root: /usr/local/Ascend/ascend-toolkit/latest
- libascendcl: /usr/local/Ascend/ascend-toolkit/latest/lib64/libascendcl.so
...
```

### Container (Atlas 200I A2)
```
- Context ID: fedcba0987654321fedcba0987654321-Atlas200I_A2-container-api-serve
- CANN root: /usr/local/Ascend/ascend-toolkit/latest
...
```

> ⚠️ **Do not merge** .so, headers, symbols, or OM artifacts across contexts. Select one active context before coding.

---
## Verification History

| Date | Check | Result |
|---|---|---|
| YYYY-MM-DD | Baseline reviewed per [baseline-review-checklist.md](references/baseline-review-checklist.md) | ✅ Pass |
| YYYY-MM-DD | API context verified against project source | ✅ Pass |
| YYYY-MM-DD | Memory alignment rules match project operations | ✅ Pass |

---
## Open Risks

- [ ] Machine ID not yet obtained (run `cat /etc/machine-id`)
- [ ] Missing DVPP symbol: `acldvppJpegDecodeAsync`
- [ ] No AIPP config for current model

---
*This document is auto-generated by the ascend-pro skill. Update it when device evidence, CANN version, or project scope changes.*
```

The render script (`render-project-baseline.py`) generates the **Device Baseline** section. The remaining sections are appended manually following the instructions in [How to generate it](#how-to-generate-it).

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
| [debug-logging.md](references/debug-logging.md) | **Must read during development.** Two spdlog loggers: `ascend` (debug, stderr) + `ascend_perf` (timing CSV, file), mandatory logging points, ACL_CHECK wrapper, throttled logging, CSV analysis script, debug checklist |
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
| `ascend-aoe-tuning` | AOE auto-tuning parameters and job types |
| `ascend-hi-mpi-guide` | HI_MPI unified media API guide (CANN 7.0+) |
| `ascend-torch-npu` | PyTorch NPU backend (`torch_npu`) integration guide |
| `ascend-mindie` | MindIE LLM inference serving engine reference |
| `ascend-fp8-guide` | FP8 precision mode configuration for Ascend910B |
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

## Debugging and Logging

> ⚠️ **During development, you MUST read [debug-logging.md](references/debug-logging.md) and add logging at all the specified stages before running any tests.**

Ascend pipelines run on remote NPU hardware with limited visibility — once a bug hits, you cannot `printf` into the NPU.
**Every pipeline must embed controllable debug logging from day one**, not retrofitted after a bug surfaces.

The reference [debug-logging.md](references/debug-logging.md) specifies:

| Must-do | Details |
|---|---|
| **Configure two loggers** | `ascend` for debug (stderr, human-readable) + `ascend_perf` for timing (CSV, file, `ASCEND_PERF=1`) — see [Multi-Configuration Setup](references/debug-logging.md#multi-configuration-setup-c-spdlog) |
| **Add debug logging at all mandatory points** | device init, model loading, memory alloc, DVPP operations, inference, stream sync, error paths — see the table in [Mandatory Logging Points](references/debug-logging.md#mandatory-logging-points) |
| **Add performance timing at all "Perf?" points** | each stage marked Yes logs latency to `ascend_perf.csv` — allows stage-by-stage bottleneck analysis |
| **Wrap every ACL call with ACL_CHECK** | never ignore an `aclError` return value — see [AscendCL Error Wrapping](references/debug-logging.md#ascendcl-error-wrapping) |
| **Use spdlog with compile-time + runtime dual control** | production strips levels via `SPDLOG_ACTIVE_LEVEL`; dev enables verbosity via `ASCEND_LOG_LEVEL` env var — see [Logging Control Strategy](references/debug-logging.md#logging-control-strategy) |
| **Save ATC conversion logs** | `--log=debug 2>&1 | tee` alongside `.om` — see [ATC / Model Conversion Logging](references/debug-logging.md#atc--model-conversion-logging) |
| **Verify with the Debug Checklist** | 12 items covering both loggers — see [Debug Checklist](references/debug-logging.md#debug-checklist) |

**Bottom line**: If you are writing or modifying Ascend pipeline code, you must open `references/debug-logging.md` and follow it. This is not optional.

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
