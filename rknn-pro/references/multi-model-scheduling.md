---
toolkit2_version: v2.3.2
last_validated: 2026-07-26
---

# Multi-Model Scheduling on Rockchip NPU

Use this reference for detector/classifier cascades, multiple independent models, or worker pools
that share a Rockchip NPU. Treat the selected `rknn_api.h`, Runtime, driver, and board image as the
contract; enum names in a header do not prove that every mask or scheduling pattern works on a given
SoC and model.

## Contents

- [Core rules](#core-rules)
- [Platform topology](#platform-topology)
- [RKNN async flag semantics](#rknn-async-flag-semantics)
- [Context and thread model](#context-and-thread-model)
- [Memory budget](#memory-budget)
- [Scheduling patterns](#scheduling-patterns)
- [Cascade buffer contract](#cascade-buffer-contract)
- [Implementation skeleton](#implementation-skeleton)
- [Measurement plan](#measurement-plan)
- [Failure patterns](#failure-patterns)

## Core Rules

1. Give each concurrently executing worker its own `rknn_context` unless the exact Runtime contract
   explicitly permits a shared-context pattern.
2. Set and check `rknn_set_core_mask` deliberately on multi-core targets, then benchmark AUTO and
   explicit masks. A wider mask is not guaranteed to reduce latency.
3. Bound every inter-stage queue and crop pool. Backpressure is part of correctness because retained
   frames also retain DMA-BUF, MPP, and RGA resources.
4. Carry tensor format, quantization, dimensions, `w_stride`, `h_stride`, allocation bytes, owner,
   synchronization state, and lifetime through every handoff.
5. Measure end-to-end latency and throughput. Per-model `rknn_run` timing cannot reveal queue waits,
   Runtime conversion, RGA work, output conversion, or memory pressure.

## Platform Topology

These are common hardware topologies for the primary targets, not substitutes for board evidence:

| SoC | Common NPU topology | Scheduling implication |
|---|---|---|
| RK3568 | One NPU core | Multiple contexts contend for one execution resource; overlap CPU/RGA work and use bounded scheduling rather than expecting NPU parallelism. |
| RK3576 | Two NPU cores | Compare one core per model with a combined mask for the bottleneck model. Check which masks the deployed Runtime accepts. |
| RK3588 | Three NPU cores | Compare dedicated cores, two-plus-one partitioning, and AUTO. Memory bandwidth and model scaling can dominate core count. |

Record the return from `rknn_set_core_mask`. Also record the exact model artifact, input shape,
Runtime/API version, driver version, and board power/thermal mode with every result.

## RKNN Async Flag Semantics

Do not model `RKNN_FLAG_ASYNC_MASK` as a generic nonblocking `rknn_run` switch.

In the current official header, enabling the flag changes `rknn_outputs_get` so it can retrieve the
previous frame rather than the current frame. The header describes this as a single-threaded
throughput optimization and says multithreaded mode does not need the flag. Consequences:

- frame identity and warm-up behavior must be handled explicitly;
- the flag does not prove that one context can receive concurrent `rknn_run` calls;
- double buffering alone does not establish completion, ownership, or output ordering;
- behavior must be re-checked against the target header when Runtime versions differ.

For a multi-stage service, prefer explicit workers with separate contexts, bounded queues, and clear
buffer ownership. Use the async flag only when its documented previous-frame semantics are actually
desired and tested.

## Context and Thread Model

Use one of these patterns:

| Pattern | Appropriate when | Required proof |
|---|---|---|
| One worker, multiple contexts | Models execute serially and latency is acceptable | Context switching and total memory are measured. |
| One worker per context | Models can use separate cores or CPU/RGA work overlaps inference | Queue bounds, shutdown, context ownership, and core masks are explicit. |
| Context pool for one model | Multiple independent requests need bounded concurrency | Each leased context has isolated I/O memory and cannot be returned while work is in flight. |

### Context Creation and Duplication

The current official header declares:

```c
int rknn_dup_context(rknn_context* context_in, rknn_context* context_out);
```

Both arguments are pointers. A call shaped like `rknn_dup_context(root_ctx, &worker_ctx)` has the
wrong first-argument type. The header describes context duplication but does not promise a specific
read-only weight-sharing or memory-saving contract. Do not present duplication as mandatory or use
it to calculate memory capacity without measurement.

For concurrent workers, keep one owned context per worker unless the exact Runtime documentation
explicitly permits concurrent calls on one context. Establish an independently initialized context
per worker as the compatibility baseline. For several workers running the same model, separately
test checked `rknn_dup_context(&root_ctx, &worker_ctx)` on the deployed stack, validate numerical
results and lifecycle behavior, and compare RSS/PSS plus `RKNN_QUERY_MEM_SIZE` against independent
`rknn_init` calls. On any failed duplicate, destroy only contexts successfully created and fall back
to a supported initialization plan. Different models require their own initialization path.

## Memory Budget

`rknn_query(ctx, RKNN_QUERY_MEM_SIZE, ...)` reports Runtime-defined weight and internal-memory
fields. It is useful evidence, but it is not a complete process or system memory measurement.

Budget at least:

- model weights and Runtime internal workspace for every context;
- input and output tensor allocations using stride-aware sizes;
- RGA/MPP buffer pools and retained decoded frames;
- DMA-BUF mappings and allocator alignment overhead;
- CPU postprocessing buffers and queue contents;
- temporary memory during model reload, resolution change, or error recovery.

Measure process RSS/PSS, DMA-heap usage when exposed, fd count, MPP group usage, and
`RKNN_QUERY_MEM_SIZE` together. Test steady state and repeated reload/reconfigure cycles.

## Scheduling Patterns

### Serial Cascade

```text
frame -> detector -> CPU decode/NMS -> RGA crop/resize -> classifier -> result
```

This is simplest and minimizes retained buffers. Use it first as a correctness baseline.

### Pipelined Cascade

```text
detector worker:   frame N+1 -> detector -> bounded detection queue
classifier worker: frame N   -> crop pool -> classifier -> result
```

The queue item must own or retain the original frame until every crop is complete. Do not pass only
an fd or RGA handle while returning the MPP/V4L2 frame upstream.

### Parallel Independent Models

```text
core/context A: frame N -> model A
core/context B: frame N -> model B
```

Fan-out is zero-copy only if both consumers share the same DMA-BUF without a hidden format copy and
the producer lifetime covers both submissions. Track fences/cache synchronization for each
consumer.

## Multi-Core Binding Strategies (NPU, RGA, MPP)

For SoCs with multiple accelerator cores, start from driver/Runtime automatic scheduling and measure
it. Contention, memory bandwidth, cache behavior, model structure, and thermal limits are hypotheses,
not consequences that can be inferred from stream count alone.

### NPU Core Binding
- For a heavy model, benchmark AUTO, supported combined masks, and single-core masks. A combined mask
  does not guarantee that every layer is split or that latency falls.
- For independent streams, benchmark separate contexts with AUTO before one-core-per-context masks.
  Explicit masks may improve isolation or may reduce utilization; record every return code.

### RGA Core Binding
RK3588 exposes RGA2- and RGA3-generation cores, but their limits differ by format and operation. Use
the detected core capability output, pinned librga guide, and `imcheck`; for example, RGA2 may allow
a wider scale ratio while RGA3 may allow a larger output, so neither is universally preferable.

Current librga scheduler values include `IM_SCHEDULER_RGA3_CORE0`,
`IM_SCHEDULER_RGA3_CORE1`, and `IM_SCHEDULER_RGA2_CORE0`. They are passed through
`imconfig(IM_CONFIG_SCHEDULER_CORE, value)` or `im_opt_t.core` with the matching extended API, not
ORed into ordinary operation flags. The official guide warns that explicit core/priority
configuration can crash or deadlock the system and advises using it only during development and
debugging, not in products. Use it only as a controlled diagnostic with checked returns, then return
to automatic production scheduling unless the board vendor provides a validated contract.

### MPP Core Binding (VDPU/VEPU)
The pinned upstream MPP headers/examples do not define a generic decoder/encoder context key for
binding a stream to a VDPU/VEPU core. Leave core selection to the driver. A vendor BSP may add a
private control, but use it only when that exact BSP documents the key, accepted values, and
lifecycle; check the configuration and `mpi->control` returns. Do not copy an unrecognized string
key into portable MPP code.

## Cascade Buffer Contract

For every crop buffer, record:

| Field | Source of truth |
|---|---|
| Logical tensor shape and format | `RKNN_QUERY_INPUT_ATTR` plus conversion report |
| Width/height stride | Queried read-only `w_stride` plus the actual backing allocation's `h_stride`, supplied through the current header's write-only field |
| Minimum RKNN bytes | Available `size_with_stride`/size fields, feature-detected at build time |
| RGA destination bytes | Checked format-specific calculation from actual destination strides |
| Allocation bytes | Checked maximum of all applicable minima, then required alignment |
| Owner and release | Pool slot or RAII object that owns RKNN memory and RGA import handle |
| In-flight state | Fence/completion or synchronous boundary that permits reuse |

Initialization sequence for a bounded crop pool:

1. Zero-initialize and query the classifier input attributes; check every return code.
2. Compute allocation bytes with checked multiplication/addition and the real pixel format.
3. Allocate with `rknn_create_mem`; reject null and clean up previously acquired slots on failure.
4. Import each returned fd into RGA; reject invalid handles and preserve one release per import.
5. Wrap RGA destinations with queried read-only `w_stride` and the actual backing height stride,
   not logical width/height defaults; set write-only `h_stride` to that physical value at bind time.
6. Bind or lease a slot only while it is not in flight; release all RGA handles before destroying
   their RKNN memory.

Direct Model A output to Model B input sharing is valid only when tensor format, shape, stride,
quantization, byte offset, allocation size, ownership, and synchronization are compatible. Matching
logical dimensions alone is insufficient.

## Implementation Skeleton

This is a lifecycle outline, not copy-ready C++:

```text
initialize:
  load each model and create one context per worker
  query and validate all tensor attributes
  set/check core masks
  allocate bounded input/output/crop pools with rollback on partial failure
  start owned, joinable workers

detector worker:
  acquire a frame reference
  preprocess into a free detector slot
  run detector and check outputs
  decode, clamp, and validate ROIs
  adapt ROIs to the source format/core/read-mode pixel constraints, clamp, then run imcheck
  enqueue a bounded task that retains the frame reference

classifier worker:
  dequeue task
  for each accepted ROI:
    lease crop slot
    RGA validate and crop/resize using real source/destination strides
    synchronize as required
    bind input, run classifier, and consume output
    return crop slot
  release retained frame reference

shutdown/error:
  stop producers, close queues, wake waiters, and join workers
  wait for hardware work to finish
  release RGA imports, RKNN tensor memory, contexts, and frame pools in reverse order
```

Implement with RAII or an equivalent single-owner cleanup discipline. Do not detach hardware
workers, leave queues unbounded, or rely on process exit for cleanup.

## Measurement Plan

Compare at least:

1. Serial correctness baseline.
2. Separate contexts with AUTO masks.
3. Explicit one-core-per-model assignment where supported.
4. Combined mask for the bottleneck model.
5. Queue depths of 1 and the smallest larger bound justified by burst behavior.

Report throughput, p50/p95 end-to-end latency, per-stage time, dropped work, queue wait, CPU usage,
memory, fd count, and thermal frequency. Warm up first and keep model artifacts and input data fixed.

## Failure Patterns

- Enabling `RKNN_FLAG_ASYNC_MASK` without tracking previous-frame output identity.
- Concurrently calling one context because the application has multiple threads.
- Assuming AUTO is bad or a wider core mask is always faster without measurement.
- Allocating crop buffers from `width * height * channels` while ignoring queried read-only
  `w_stride`, actual backing height stride, and checked byte sizing.
- Applying a universal byte-based ROI rule instead of format/core/read-mode pixel constraints and `imcheck`.
- Returning an MPP/V4L2 frame before downstream RGA work completes.
- Passing an fd between contexts without importing it separately or defining ownership.
- Ignoring `rknn_set_core_mask`, query, allocation, RGA, or output return codes.
- Retaining unlimited detections, frames, or requests under overload.
- Destroying contexts or memory while workers or hardware tasks remain in flight.

## Sources

- RKNN Runtime API header (snapshot `59a913d`): https://github.com/airockchip/rknn-toolkit2/blob/59a913d172e7f5ff03c9076e2ec7b1b1288ffd08/rknpu2/runtime/Linux/librknn_api/include/rknn_api.h
- RKNN Toolkit2 repository and examples: https://github.com/airockchip/rknn-toolkit2
- RKNN model zoo: https://github.com/airockchip/rknn_model_zoo
- librga developer guide (snapshot `2b32edc`): https://github.com/airockchip/librga/blob/2b32edcb97b601b25683e2941d888c8515da6d55/docs/Rockchip_Developer_Guide_RGA_EN.md
- MPP source snapshot (`df4864b`): https://github.com/rockchip-linux/mpp/tree/df4864bd1e907cbfd427c397348976c5b2b05ee9
