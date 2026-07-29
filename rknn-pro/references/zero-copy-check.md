# Zero-Copy Audit Procedure

Audit an existing Rockchip pipeline implementation to find **unnecessary** host copies —
copies that CAN be eliminated but weren't. Not every pipeline can be 100% zero-copy;
the goal is to eliminate every copy that the hardware CAN avoid, and use CPU fallback
only where it's genuinely impossible to do otherwise.

## Core Principle

> **Zero-copy where hardware allows. CPU fallback only where unavoidable.**

Identify each copy, classify it:
- **Unnecessary** → hardware API supports DMA-BUF handoff but the code uses CPU memcpy
- **Unavoidable** → no hardware path exists (e.g., format conversion not in RGA, NPU output
  must be read back for complex post-processing, display subsystem doesn't accept DMA-BUF)

The report should tell the user: **which copies can be eliminated, and which are truly necessary.**

## The Golden Reference Path

This is the ideal — but not every pipeline can achieve it:

```
V4L2/MPP ──[DMA-BUF fd]──> RGA ──[DMA-BUF fd]──> RKNN ──[required output access]──> application
```

Every hop passes a DMA-BUF file descriptor where possible. **No `mmap` + `memcpy` in the hot path.**

## Audit Procedure

Dispatch a subagent to perform these checks against the implementation code.
The subagent should read the relevant source files and produce a structured report.

---

### Phase 1: Pipeline Map

Read the code and identify each stage:

| Stage | API | Buffer type observed | DMA-BUF possible? |
|---|---|---|---|
| Source (camera/file/rtsp) | V4L2 / MPP / ffmpeg | | |
| Preprocess | RGA / CPU | | |
| Inference | RKNN Runtime | | |
| Postprocess | CPU / NPU | | |
| Sink (display/encode/file) | DRM / MPP / file | | |

### Phase 2: Per-Stage Buffer Audit

For **each stage**, check:

#### Source → RGA

- [ ] The selected MPP mode yields an `MppBuffer` whose DMA-BUF fd, size, layout, and lifetime meet the downstream contract; external mode is required only when the application must supply the pool
- [ ] RGA input uses `importbuffer_fd(dma_fd)` (NOT `importbuffer_virtualaddr`)
- [ ] RGA geometry, strides, format, read mode, and eligible core satisfy their exact constraints
- [ ] `importbuffer_fd` called **once** per buffer (not per frame in the hot path)
- [ ] RGA output buffer is also a DMA-BUF fd (NOT CPU memory)
- [ ] RGA operation is strictly validated via `imcheck()` before execution, especially for dynamic ROIs

**Anti-patterns — classify as eliminable ✅ or unavoidable ❌:**

| Anti-pattern | Classification | Why / Workaround |
|---|---|---|
| Copying from an exportable internal `MppBuffer` | ✅ **Eliminable** | Import its validated DMA-BUF fd downstream; external mode is not inherently required |
| `importbuffer_virtualaddr` despite a compatible DMA-BUF fd | ✅ **Eliminable** | Use `importbuffer_fd` after proving exporter/importer compatibility |
| `importbuffer_fd` inside per-frame loop | ✅ **Eliminable** | Call once per buffer at init, reuse handles |
| Returned MPP buffer cannot be exported/imported with a compatible layout | ❌ **Unavoidable at that boundary** | Try a supported external pool or conversion target; otherwise retain a measured copy fallback |
| RGA doesn't support the exact format conversion needed | ❌ **Unavoidable** | CPU NEON fallback for unsupported format paths |

#### RGA → RKNN

- [ ] When layout/import support is compatible, RKNN input uses `rknn_create_mem_from_fd(rga_dma_fd)` rather than a copied host buffer
- [ ] `rknn_set_io_mem` used to bind the imported memory to the input tensor
- [ ] The backing width stride satisfies queried read-only `w_stride`; write-only `h_stride` is set from the physical layout

**Anti-patterns — classify as eliminable ✅ or unavoidable ❌:**

| Anti-pattern | Classification | Why / Workaround |
|---|---|---|
| `rknn_inputs_set` with host buffer although an import-compatible layout already exists | ✅ **Eliminable** | Import and bind the existing DMA-BUF after parity and synchronization tests |
| CPU mapping retained although no CPU stage touches the buffer | ✅ **Eliminable** | Remove the mapping if the installed RKNN import contract permits it; mapping alone is not a pixel copy |
| Overwriting read-only `w_stride` to describe a different buffer | ✅ **Eliminable** | Make RGA/backing memory satisfy the queried width stride; set only write-only `h_stride` from the real layout |
| Upstream layout is incompatible with RKNN input | ❌ **Unavoidable at that boundary** | Use RGA into a compatible DMA-BUF when supported; otherwise a measured conversion/copy fallback is required |

#### RKNN → Postprocess

- [ ] Where the selected Runtime/output contract supports it and measurement justifies it, compare preallocated output via `rknn_create_mem` + `rknn_set_io_mem` with `rknn_outputs_get`
- [ ] Postprocess reads every value required by the algorithm; classification top-k normally scans the complete class vector
- [ ] Compare raw quantized output plus correct dequantization against `want_float=1`; select from parity and measured end-to-end cost

**Anti-patterns — classify as eliminable ✅ or unavoidable ❌:**

| Anti-pattern | Classification | Why / Workaround |
|---|---|---|
| `want_float=1` dominates measured output time and raw output is supported | ✅ **Potentially eliminable** | Use raw output only after quantization-aware parity and full-pipeline measurement |
| Reading only a prefix to compute classification top-k | ❌ **Incorrect optimization** | Scan all class elements unless the model itself returns top-k indices/scores |
| `rknn_outputs_get` followed by an unnecessary duplicate app buffer | ✅ **Eliminable** | Consume the owned/preallocated output in place with required cache sync and lifetime controls |
| Complex postprocess (NMS, tracking) needs full float tensor | ❌ **Unavoidable** | Algorithm requires full tensor; optimize dequantize or move to NPU |

#### Postprocess → Sink (display/encode)

- [ ] Display uses DRM DMA-BUF import (not memcpy to fb)
- [ ] Encode uses MPP external buffer mode with the same DMA-BUF fd
- [ ] No full-frame memcpy between postprocess and sink

**Anti-patterns — classify as eliminable ✅ or unavoidable ❌:**

| Anti-pattern | Classification | Why / Workaround |
|---|---|---|
| memcpy to framebuffer display | ✅ **Eliminable** | Use DRM DMA-BUF import if display hardware supports it |
| memcpy to MPP encode input | ✅ **Eliminable** | Use MPP external buffer mode, import the DMA-BUF fd directly |
| Display uses fbdev (no DRM) | ❌ **Unavoidable** | Legacy driver; upgrade to DRM/KMS or accept the copy |
| Encode input format doesn't match decoder output | ❌ **Unavoidable** | RGA format conversion may be needed while retaining DMA-BUF-backed handoff |

### Phase 3: Quantify Copies

Count every `memcpy`, `memmove`, `cpy`, `copy`, `clone`, `duplicate` in the hot path.

Classify each:

| Copy type | Location | Bytes/frame | Eliminable? | Why? |
|---|---|---|---|---|
| H2D | | | ✅ Yes / ❌ No | Reason |
| D2H | | | ✅ Yes / ❌ No | Reason |
| H2H | | | ✅ Yes / ❌ No | Reason |
| D2D | | | ✅ Yes / ❌ No | Reason |

For each copy marked **unavoidable**, document the exact constraint that prevents zero-copy:
- RGA doesn't support the required format conversion (which format?)
- MPP external buffer mode not available on this kernel/BSP
- RKNN model requires NHWC but RGA outputs NV12 → can't avoid CSC copy
- Display subsystem (fbdev) doesn't support DMA-BUF import
- Postprocess runs on CPU and needs full tensor (which model? which output?)

### Phase 4: Score

| Level | Criteria |
|---|---|
| **Gold** 🥇 | All copies eliminated where hardware allows. Only genuinely unavoidable copies remain (if any). |
| **Silver** 🥈 | Most copies eliminated. 1-2 unnecessary copies remain (easy fixes). |
| **Bronze** 🥉 | Several unnecessary copies. Needs refactoring but core pipeline structure is sound. |
| **Needs work** | Copies everywhere. Pure internal MPP, CPU preprocess, rknn_inputs_set with host buffer. |

### Phase 5: Recommendations

For each **unnecessary** copy, provide:
1. **What to change** (specific code change)
2. **Expected gain** as a hypothesis, followed by a required before/after measurement
3. **Risk** (what could break)
4. **Verification** (how to confirm the change worked)

## Subagent Prompt Template

```markdown
You are a zero-copy audit agent for Rockchip RKNN pipelines.

Read the following source files and perform a zero-copy audit following the procedure
in references/zero-copy-check.md. Focus on:

1. How are buffers allocated at each stage?
2. Is there any memcpy/memmove in the frame-processing loop?
3. Are DMA-BUF fds passed between stages or is there a host memory detour?
4. Does the RKNN path use rknn_create_mem_from_fd (zero-copy) or rknn_inputs_set (copy)?

Source files: [list of files]
Pipeline description: [user's description]

Produce a structured report with:
- Pipeline map (each stage + buffer type)
- Per-stage audit findings (pass/fail for each check item)
- Copy quantification table
- Zero-copy score (Gold/Silver/Bronze/Needs work)
- Specific recommendations for each anti-pattern found
```

## Usage

When the user asks "check if my pipeline is zero-copy" or "audit my RKNN implementation":

1. Read the relevant source files.
2. If the codebase is large, dispatch a subagent with the prompt template above.
3. Read the subagent report.
4. Present findings to the user with copy count, score, and fix recommendations.
