# Copy-Minimized Inference Pipeline

Use “zero-copy” only for a precisely bounded path after accounting for every buffer transition. Many useful
pipelines still require an input upload or output readback; the engineering goal is to eliminate unnecessary
copies and repacks, not to win a label.

## Buffer Ledger

Create one row for every hop:

| Buffer/hop | Producer | Owner | Allocation API | Memory domain | Format/shape/stride | Consumer | Copy/map/sync |
|---|---|---|---|---|---|---|---|
| | | | | | | | |

Do not infer visibility from an allocator name. Verify producer/consumer access for the selected device,
CANN release, run mode, and API path. “Pinned”, “device”, “DVPP”, shared, imported, and mapped buffers are
not interchangeable terms.

## Verification Procedure

1. Identify where bytes originate and which component first owns them.
2. Trace decode/capture, format conversion, crop/resize/pad, model input, model output, and postprocess.
3. Search source and wrappers for memcpy, map/unmap, imports/exports, CPU image operations, serialization,
   temporary tensor construction, and fallback paths.
4. Record actual descriptors, strides, capacities, and allocation/free pairs.
5. Record every stream/event/callback and the buffer lifetime it protects.
6. Use profiling/tracing or controlled counters to prove copy direction and bytes when tools expose them.
7. Verify output correctness before and after removing a boundary.
8. Compare end-to-end latency, throughput, CPU use, and memory pressure with the same workload.

## Common Copy Boundaries

- CPU decode or OpenCV preprocessing followed by host-to-device upload.
- DVPP output read back for inspection and uploaded again for inference.
- DVPP/AIPP/model format mismatch requiring an intermediate repack.
- Framework or wrapper code allocating a hidden staging tensor.
- Full output readback when the application needs only a smaller result.
- Per-frame allocation or descriptor construction that looks like copy cost in profiles.
- Immediate synchronization after each asynchronous operation.

Selective debug readback can be valid. Keep it sampled and outside production measurements.

## Buffer Pool Design

For each slot, track allocation capacity, descriptor wrappers, owner, state, generation, completion token,
and the exact point at which it can be reused. Check all allocation calls and preserve the old allocation
until a replacement succeeds; do not free-then-allocate and leave a corrupted slot on failure.

Pool size is a measured backpressure decision. Double or triple buffering does not create concurrency by
itself, and several pipeline stages cannot safely reuse one stream or buffer without explicit dependencies.

## Async Design

- Model streams, DVPP streams, callbacks, and CPU queues as a dependency graph.
- Keep input, output, datasets, descriptors, and dynamic/AIPP parameter objects alive through completion.
- Use the completion primitive supported by the exact CANN/API surface.
- Avoid global device synchronization unless recovery or shutdown requires it.
- Bound queues and define drop/backpressure behavior for real-time workloads.
- Handle submit failure, partial pipeline completion, cancellation, EOS, timeout, and shutdown.

Measure device completion and downstream availability, not only enqueue duration. Prove overlap with a
timeline or throughput experiment rather than counting async API names.

## Output Strategy

Start from application requirements. If CPU code needs complete logits, a D2H copy may be correct. If only
top-k, boxes, or metadata are required, evaluate device-side or reduced postprocessing only when supported by
the project/toolchain and justified by accuracy, maintenance, and performance results. Do not assume an
arbitrary slice of an output allocation can be copied independently of tensor layout.

## Claim Template

Use this wording for verified results:

```text
Between <producer> and <consumer>, the selected runtime passes <buffer identity/domain> without an explicit
host copy or repack. Evidence: <source trace + runtime profile>. Remaining transfers: <list>. Synchronization:
<list>. Verified on <context ID>, <workload>, <date>.
```

If any wrapper, driver, framework, or imported-buffer behavior is unobserved, say “no explicit application
copy observed” rather than “zero-copy”.
