# DVPP API Verification Guide

DVPP capability, API families, descriptors, pixel formats, alignment, dimension ranges, and callback models
vary across Ascend devices and CANN releases. Establish the target's surface before choosing an API.

## Capability Gate

For the selected runtime context, answer:

1. Which media operation is required: VPC, JPEGD/JPEGE, PNGD, VDEC, VENC, or another surface?
2. Does the exact device/CANN combination support it?
3. Which input/output formats, dimensions, strides, ROI rules, and scaling ratios are supported?
4. Which memory domains and allocators may feed and consume the operation?
5. Is completion stream-based, callback-based, or synchronous in this API generation?

Verify with installed headers, symbols in the actual loaded DVPP library, and official documentation for the
exact target. Record the source and verification date in the reviewed context.

## Establish The API Surface

```bash
rg -n 'acldvpp|Vpc|Jpeg|Vdec|Venc|PicDesc|StreamDesc|Roi' \
  "$ASCEND_HOME_PATH/include" <project-source>
readelf -Ws <actual-loaded-dvpp-library> | rg 'acldvpp'
```

Copy prototypes from the selected installed header. Do not copy signatures or enum values from another
device family or CANN release. In particular, descriptor destroy functions, VDEC/VENC channel types,
callback signatures, and interpolation enums have changed across surfaces.

## Descriptor Contract

For every image or stream descriptor, record and validate:

- buffer pointer, allocation capacity, and allocation/free API;
- logical width/height and actual width/height stride;
- pixel or stream format and plane layout;
- descriptor-reported size and per-plane offsets;
- producer, consumer, stream/context, and lifetime through completion.

Use [memory-alignment.md](memory-alignment.md) to implement checked calculations. When DVPP exposes a
format/operation-specific size query, prefer it to a handwritten formula.

## Channel And Resource Lifetime

- Create reusable channels, descriptors, configs, and buffer pools outside the per-frame hot path when the
  selected API permits it.
- Assign ownership before coding. Descriptor destruction and underlying buffer freeing are separate actions.
- Tear down only after queued operations and callbacks can no longer reference resources.
- Check the return convention of every selected create/destroy/set/submit API from the installed header.

## VPC Review

Before resize, crop, paste, color conversion, or rotation:

- verify the input/output format pair and operation combination;
- verify logical dimensions, actual strides, ROI coordinate parity and boundary semantics;
- verify scaling range and interpolation values for the selected release;
- prove output allocation capacity from actual output strides/planes;
- determine whether the next model/AIPP stage can consume the output without host readback or repack.

Do not assume a crop rectangle is inclusive or that `right > left` is sufficient; extract the exact coordinate
contract from target documentation and test odd/even boundaries.

## JPEG Review

- Query or parse JPEG metadata using the target-supported API before allocating output.
- Verify supported JPEG subsampling, colorspace, progressive/baseline mode, resolution, and output formats.
- Use the documented output-size query or exact-version formula.
- Verify where the compressed input buffer may reside and how long it must remain valid.
- Treat encoded output capacity and returned encoded length as separate values.

## VDEC And VENC Review

- Determine the selected API generation and descriptor/channel types from installed headers.
- Record codec/profile/level, bitstream framing, resolution, output format, stride, and reference-frame needs.
- Make callback thread/context rules and `userData` ownership explicit.
- Size queues and buffer pools from measured producer/consumer behavior.
- Define EOS, flush, error, timeout, and teardown behavior before the normal hot path.
- Never free an input/output descriptor or buffer until the corresponding completion contract is satisfied.

## Submission Procedure

1. Validate all descriptor fields and capacities.
2. Submit and check the immediate return status.
3. Establish completion using the documented stream/event/callback mechanism.
4. Check completion status and recent error detail if supported.
5. Verify output descriptor fields; codecs may report actual output properties.
6. Pass ownership to the next stage or return the buffer to its pool.

Async submission is not evidence of overlap. Measure queueing, completion, stream waits, callback latency,
and downstream backpressure.

## Verification Matrix

| Case | What to verify |
|---|---|
| Nominal | exact formats, output correctness, no unexpected copy |
| Non-aligned logical size | actual strides and allocation capacity |
| Minimum/maximum supported size | documented boundary behavior |
| Invalid ROI/format | deterministic error and safe cleanup |
| Multiple in-flight buffers | lifetime, ordering, and callback safety |
| EOS/flush | all buffers returned exactly once |
| Performance | stage completion latency and end-to-end throughput |

Do not claim a DVPP optimization until accuracy/output validation and same-workload end-to-end measurement
both pass on the selected device context.
