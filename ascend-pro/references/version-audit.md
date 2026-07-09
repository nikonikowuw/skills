# Version Audit

## Purpose

Use this reference when Ascend behavior does not match the code, especially after CANN upgrades, driver changes, container image changes, toolkit copying, or model artifact replacement.

## Why This Matters

Ascend deployments span device model, driver, firmware, runtime libraries, toolkit tools, Python packages, and OM artifacts. A partial upgrade or cross-device context mix can create failures that look like business logic bugs:

- Model conversion succeeds but runtime load or execution fails.
- Runtime works but performance regresses due to changed operator placement, AIPP behavior, or fallback paths.
- The project compiles against one CANN header set but loads another `libascendcl.so`.
- Containers see a different runtime than the host driver expects.
- One device model's `.so` set or OM artifact is accidentally reused as context for another device model.

## Minimum Audit Set

Record these before debugging performance or correctness:

- Device model and NPU visibility from `npu-smi info`.
- Driver and firmware versions from `npu-smi` output and package metadata.
- CANN runtime and toolkit versions.
- `atc --version` output when model conversion is involved.
- Paths to `libascendcl.so`, DVPP libraries, and headers used by the project.
- Python packages used for ACL, benchmark, conversion, or framework adapters.
- OM artifact creation command, conversion logs, input shape, precision, and AIPP config when available.

Record the full set separately for every target device model. Do not create one combined "Ascend libraries" list when the project supports multiple devices.

## Device-Scoped Version Matrix

For multi-device projects, maintain a matrix with one row per context:

| Context ID | Device model | Driver/firmware | CANN root | `libascendcl.so` | DVPP lib | Headers | OM artifact | Linkage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `Ascend310P-host-video-infer` | Ascend310P | observed or unknown | observed path | observed path | observed path | observed path | model path | ldd/readelf facts |

Use this matrix when handing context to another agent. The active row is the only row that should drive implementation unless the task is explicitly multi-device compatibility work.

## Runtime Library Audit

Find the deployed libraries:

```bash
find /usr/local/Ascend /usr /usr/local -maxdepth 6 \
  \( -name 'libascendcl.so*' -o -name 'libacl_dvpp.so*' -o -name 'libacl_op_compiler.so*' -o -name 'libge_runner.so*' \) 2>/dev/null
```

Then verify what the binary actually uses:

```bash
ldd <target-binary-or-so>
readelf -d <target-binary-or-so>
```

If there are multiple plausible CANN installs, stop and resolve which one is used at runtime for the active device context.

## Header And Symbol Audit

Check compile-time and runtime API surfaces:

```bash
rg -n 'acl/acl|acl_dvpp|ascendcl|aclrt|aclmdl|acldvpp|ATC|ASCEND_HOME_PATH|LD_LIBRARY_PATH' .
readelf -Ws <ascend-shared-object> | grep -E 'aclrt|aclmdl|acldvpp|aclInit|aclFinalize'
nm -D <ascend-shared-object> | grep -E 'aclrt|aclmdl|acldvpp|aclInit|aclFinalize'
```

Do not code to a function mentioned in documentation until the deployed shared object exports it and the selected headers match the intended build target.

## Model Artifact Audit

For each `.om` file, record:

- Source model path and framework.
- ATC version and command line.
- Input names, shapes, dynamic shape settings, format, and batch policy.
- Precision or operator flags.
- AIPP config file and whether preprocessing is static or dynamic.
- Runtime device model for which the artifact was validated.

If those facts are unknown, performance conclusions are provisional.

## Escalation Rules

- If driver and CANN package provenance conflict, stop major optimization work and fix the stack first.
- If the project links one CANN copy but the shell environment points to another, resolve environment and rpath before changing code.
- If the OM was produced by an unknown ATC version or for an unknown device target, archive current behavior and regenerate a known artifact before deep runtime tuning.
- If a container is involved, audit host driver, mounted device nodes, mounted CANN paths, and container library paths together.
- If multiple device contexts exist and the active context is not selected, ask which device model is targeted before changing code.
