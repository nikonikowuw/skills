# AscendCL API Verification Guide

AscendCL signatures, availability, constraints, and deprecations vary by CANN release. This file is a
workflow for establishing the selected runtime's API contract; it is not a substitute for installed headers.

## Establish The API Surface

1. Select the active runtime context and CANN root.
2. Locate the headers actually used by the build:

   ```bash
   rg -n 'aclInit|aclFinalize|aclrtSetDevice|aclrtMalloc|aclrtMemcpy|aclmdl' \
     "$ASCEND_HOME_PATH/include" <project-build-files>
   ```

3. Prove the target's loaded libraries with `ldd`, `readelf -d`, rpath/runpath inspection, or the actual
   `dlopen` resolution path.
4. Verify required exported symbols in those shared objects:

   ```bash
   readelf -Ws <actual-libascendcl.so> | rg 'aclInit|aclFinalize|aclrt|aclmdl'
   ```

5. Compare the exact device/CANN version with official Huawei documentation. Record source and date.
6. Copy an exact prototype into code or reviewed context only after steps 2-5 agree.

## Stable Lifecycle Model

The common lifecycle is:

```text
ACL initialization
  -> device/context selection
  -> stream and model setup
  -> model descriptor and I/O contract discovery
  -> buffer/dataset construction
  -> input preparation and execution
  -> completion and output consumption
  -> reverse-order resource cleanup
  -> device reset/finalization when owned by this component
```

Do not copy a generic teardown sequence into a library without checking ownership. A process-level runtime
manager, framework, or another component may own initialization, device selection, and finalization.

## Contract Checks

### Initialization And Context

- Determine whether the application uses an implicit/default context or explicit contexts.
- Check thread/context rules in the selected release before assuming a thread must call a device API.
- Record who owns initialization, reset, and finalization.
- For callbacks or worker threads, make context propagation explicit.

### Memory And Copies

- Select allocation and copy APIs using actual run mode, memory domain, producer, and consumer.
- Get model I/O byte requirements from the model descriptor APIs declared in the installed headers; do not
  hard-code an alignment guarantee or infer byte size from logical dimensions alone.
- For copy APIs, distinguish destination capacity from bytes copied. Validate both against the selected
  prototype; do not require source and destination capacities to be equal unless that release says so.
- Keep asynchronous source/destination buffers alive until completion. Separate submission from completion.
- Prefer pools outside the hot path, but preserve the project's ownership and cleanup rules.

### Models, Descriptors, Datasets, And Buffers

- Discover model I/O through the selected model descriptor API. Function names and signatures must come
  from the installed header, not memory.
- Match dataset buffer order, byte capacity, dtype, format, shape, dynamic-control inputs, and AIPP contract
  to the deployed OM.
- Track the ownership of raw allocations, data-buffer wrappers, datasets, model descriptors, models, streams,
  and contexts separately. Destroying a wrapper may not free its underlying allocation.
- Keep every object referenced by asynchronous execution alive until completion is established.

### Dynamic Shape And AIPP

- Inspect model metadata to identify the dynamic control input and supported profiles.
- Extract the applicable setter prototypes and call order from the selected headers/documentation.
- Confirm runtime shapes and AIPP output match the OM's conversion-time contract.
- Validate accuracy for every shape/profile used in production.

## Error Handling

Classify each API by return convention before writing wrappers:

| Convention | Check | Typical cleanup action |
|---|---|---|
| `aclError` return | compare with `ACL_SUCCESS` | unwind resources acquired by the current scope |
| Pointer factory | check `nullptr` | destroy previously created wrappers/allocations |
| Direct value/query | use documented invalid/sentinel contract | propagate a typed project error |
| Async submit | check submit status and later completion status | retain buffers until completion/cancellation |

Use [debug-logging.md](debug-logging.md) for an adaptable error/timing pattern. Verify whether the selected
release declares `aclGetRecentErrMsg()` before using it and read recent detail immediately after failure.

## Review Checklist

- [ ] Exact header root and CANN version recorded.
- [ ] Actual loaded runtime library and required symbols proved.
- [ ] Prototypes copied from the selected header, including return types and parameter order.
- [ ] Initialization/finalization and raw-buffer/wrapper ownership assigned.
- [ ] Async lifetimes and completion points explicit.
- [ ] Model byte sizes and dynamic/AIPP contracts come from deployed artifact metadata.
- [ ] Every return convention handled without applying one macro to incompatible functions.
