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
V4L2/MPP ──[DMA-BUF fd]──> RGA ──[DMA-BUF fd]──> RKNN ──[partial readback]──> display/encode
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

- [ ] MPP decoder uses `MPP_BUFFER_EXTERNAL` mode (not internal/half-internal)
- [ ] RGA input uses `importbuffer_fd(dma_fd)` (NOT `importbuffer_virtualaddr`)
- [ ] RGA input dimensions and format align with hardware requirements (e.g. 4-byte/even width)
- [ ] `importbuffer_fd` called **once** per buffer (not per frame in the hot path)
- [ ] RGA output buffer is also a DMA-BUF fd (NOT CPU memory)
- [ ] RGA operation is strictly validated via `imcheck()` before execution, especially for dynamic ROIs

**Anti-patterns — classify as eliminable ✅ or unavoidable ❌:**

| Anti-pattern | Classification | Why / Workaround |
|---|---|---|
| MPP internal mode → must copy out decoded frames | ✅ **Eliminable** | Switch to `MPP_BUFFER_EXTERNAL`, provide your own DMA-BUF pool |
| `importbuffer_virtualaddr` → CPU page-table walk | ✅ **Eliminable** | Use `importbuffer_fd` with DMA-BUF instead |
| `importbuffer_fd` inside per-frame loop | ✅ **Eliminable** | Call once per buffer at init, reuse handles |
| MPP external buffer mode unavailable on old BSP | ❌ **Unavoidable** | Kernel/BSP too old; upgrade BSP or accept copy |
| RGA doesn't support the exact format conversion needed | ❌ **Unavoidable** | CPU NEON fallback for unsupported format paths |

#### RGA → RKNN

- [ ] RKNN input uses `rknn_create_mem_from_fd(rga_dma_fd)` (NOT `rknn_inputs_set` with host buffer)
- [ ] `rknn_set_io_mem` used to bind the imported memory to the input tensor
- [ ] `w_stride` / `h_stride` in the tensor attr match the actual RGA output stride

**Anti-patterns — classify as eliminable ✅ or unavoidable ❌:**

| Anti-pattern | Classification | Why / Workaround |
|---|---|---|
| `rknn_inputs_set` with host `malloc` buffer | ✅ **Eliminable** | Use `rknn_create_mem_from_fd` with RGA's output DMA-BUF |
| `rknn_input.buf = mmap(rga_dma_fd)` → CPU mapping | ✅ **Eliminable** | NPU can access DMA-BUF directly, no mmap needed |
| Wrong `w_stride` in `rknn_set_io_mem` | ✅ **Eliminable** | Bug fix — query and set correct stride |
| RKNN model requires specific stride not matching RGA output | ❌ **Unavoidable** | Must copy to adjust stride, or retrain model with matching input size |

#### RKNN → Postprocess

- [ ] Output uses `rknn_create_mem` + `rknn_set_io_mem` (device-resident output)
- [ ] Postprocess reads only metadata (bounding boxes, class IDs), not full tensor
- [ ] If full tensor readback is required: `rknn_outputs_get(want_float=0)` for raw INT8, manual dequantize

**Anti-patterns — classify as eliminable ✅ or unavoidable ❌:**

| Anti-pattern | Classification | Why / Workaround |
|---|---|---|
| `rknn_outputs_get(want_float=1)` in hot path | ✅ **Eliminable** | Use `want_float=0`, manual dequantize with scale/zp |
| Full output readback when only top-5 needed | ✅ **Eliminable** | Read only first N bytes (classification) or use NPU postprocess |
| `rknn_outputs_get` + memcpy to app buffer | ✅ **Eliminable** | Use `rknn_create_mem` for output, cast pointer directly |
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
| Encode input format doesn't match decoder output | ❌ **Unavoidable** | RGA format conversion needed (still DMA-BUF, but not fd-to-fd)

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
2. **Expected gain** (latency reduction or throughput increase estimate)
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
