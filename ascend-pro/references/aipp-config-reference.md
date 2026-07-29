# AIPP Configuration Verification Guide

AIPP can absorb supported preprocessing into the deployed model, but configuration fields, supported
formats, processing order, dynamic controls, and constraints vary by ATC/CANN/device release. Generate the
configuration from the exact installed template or official versioned documentation.

## Decision Gate

Use AIPP only when all of these hold:

- the selected target supports the required input format and operations;
- the model's expected color order, layout, shape, scale, mean, and normalization are precisely known;
- the desired crop/resize/padding policy is expressible in that release;
- the runtime can provide the required input memory and dynamic parameters;
- a reference implementation exists for accuracy comparison;
- end-to-end measurement shows that CPU/DVPP work or copies are actually removed.

Do not assume AIPP performs an operation simply because a field appeared in another CANN template. Do not
combine old CPU preprocessing with AIPP unless each stage is intentional and validated.

## Build The Configuration

1. Record target device, `atc --version`, source-model checksum, input names/shapes/layouts/dtypes, and
   expected preprocessing equation.
2. Obtain the AIPP config template from the installed ATC/CANN package or exact-version official docs.
3. Select static or dynamic mode based on supported target behavior, not generic examples.
4. Fill only fields declared by that template. Record units, numeric representation, defaults, and operation
   order from the same version.
5. Preserve the config, ATC command/log, output OM checksum, and target SoC together.
6. Inspect generated model metadata to confirm the resulting runtime input contract.

## Color And Normalization Contract

Write the intended transformation mathematically before setting coefficients:

```text
input byte layout and range
  -> color-space/range conversion
  -> channel order
  -> crop/resize/pad policy
  -> per-channel subtract/scale
  -> model tensor layout, dtype, and range
```

Do not reuse a CSC matrix without confirming source standard, full/limited range, channel order, coefficient
scaling/rounding, output bias convention, and the selected AIPP processing order. Validate with color ramps,
edge values, and real inputs against the trusted CPU reference.

## Static Mode

For static AIPP, confirm which parameters are frozen into the OM and whether runtime input dimensions remain
fixed or profile-dependent. Any change to input format, CSC, normalization, crop, resize, or padding requires
regeneration and a new artifact checksum/accuracy result.

## Dynamic Mode

For dynamic AIPP:

- verify the target exposes the required dynamic AIPP APIs and exact parameter structures;
- inspect the deployed model for its dynamic-control input and index;
- allocate/fill parameter objects using installed-header prototypes and matching destroy APIs;
- validate interaction with dynamic batch/image/shape features from the same release documentation;
- keep parameter objects and input buffers alive for the documented execution lifetime.

Do not copy a struct layout or direct field assignment from a generic snippet. Use official setters or exact
installed structures as required by the selected CANN version.

## Accuracy Verification

Use deterministic inputs and compare these checkpoints where possible:

1. decoded source pixels;
2. CPU reference after color conversion;
3. CPU reference after crop/resize/pad;
4. normalized model tensor;
5. model outputs without AIPP and with AIPP.

Define tolerances per dtype and model sensitivity. Inspect channel swaps, limited/full range, odd dimensions,
padding boundaries, and rounding. Passing a few final detections is not enough for a reusable conversion rule.

## Performance Verification

Compare the same workload and runtime context. Measure decode, preprocess, copy, inference completion, and
postprocess separately, plus end-to-end throughput/latency. AIPP is beneficial only if removed CPU/copy work
outweighs any new constraints, serialization, or artifact-management cost.

## Artifact Checklist

- [ ] Installed template or exact-version official source recorded.
- [ ] Input format/layout/range and preprocessing equation explicit.
- [ ] Static/dynamic behavior and dynamic-shape interactions verified for target release.
- [ ] ATC version/command/log and source/config/OM checksums archived.
- [ ] Runtime input and parameter API contract inspected from deployed model and headers.
- [ ] Tensor-level accuracy and same-workload performance comparisons passed.
