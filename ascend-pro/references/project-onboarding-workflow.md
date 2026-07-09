# Project Onboarding Workflow

## Purpose

Use this workflow before writing or modifying Ascend performance code in an unfamiliar repository. The goal is to prevent development against the wrong driver, wrong CANN package, wrong headers, wrong model artifact, or an imagined API surface.

## Rule

Do not start implementation until this workflow is complete or an explicit exception is stated.

## Phase 1: Device And Image Identification

Record for the active target device:

- Device model and NPU count from `npu-smi info`.
- Driver and firmware versions from `npu-smi` and package metadata.
- Kernel version from `uname -a`.
- OS release from `/etc/os-release`.
- CANN install root and package provenance if known.
- Whether the runtime is bare metal, containerized, or cross-rootfs.

If the repository is supposed to run on multiple device models or images, create separate device context IDs before coding. Do not merge their libraries or model artifacts into one baseline.

## Phase 2: Driver And Device Audit

Identify which subsystems are actually present:

- Device nodes such as `/dev/davinci*`, `/dev/davinci_manager`, `/dev/devmm_svm`, and `/dev/hisi_hdc`.
- NPU visibility through `npu-smi info`.
- Kernel logs for driver initialization, reset, memory, or permission failures.
- Container device mounts if the project runs in Docker or another container runtime.

Required output:

- Which devices and critical nodes are visible.
- Which expected nodes or permissions are missing.
- Whether `npu-smi` sees the same target device the project expects.

## Phase 3: Tool And Library Audit

Find the actual deployed tools and libraries for the active device context, not the ones the developer assumes exist.

Search for:

- `atc`
- `aclprof` or profiler tools
- `msame`, `ais_bench`, or project benchmark wrappers
- `libascendcl.so*`
- `libacl_dvpp.so*`
- `libacl_op_compiler.so*`
- `libge_runner.so*`

Check:

- Where each tool or library is located.
- Whether the project links by system path, rpath, copied SDK path, container mount, or `dlopen`.
- Whether multiple conflicting CANN installs exist.

Useful commands:

```bash
which npu-smi atc aclprof msame ais_bench 2>/dev/null
find /usr/local/Ascend /usr /usr/local -maxdepth 6 \( -name 'libascendcl.so*' -o -name 'libacl_dvpp.so*' -o -name 'libacl_op_compiler.so*' -o -name 'libge_runner.so*' \) 2>/dev/null
ldd <binary-or-shared-object>
readelf -d <binary-or-shared-object>
```

If more than one plausible Ascend userspace stack is installed, stop and resolve which one the project really uses for the selected device context.

## Phase 4: Header And API Audit

Check the compile-time API surface before changing code.

Locate headers for:

- `acl/acl.h`
- `acl/ops/acl_dvpp.h` or DVPP-related headers for the installed CANN release.
- Project wrappers around `aclrt`, `aclmdl`, `acldvpp`, streams, and memory helpers.

Verify:

- Include paths used by the project.
- CANN version macros or package metadata when available.
- Whether headers match the runtime libraries found on the device or container.

Failure pattern:

- The code compiles against one toolkit snapshot but runs with a different CANN runtime set.

## Phase 5: Exported Symbol Audit

Confirm the required runtime APIs exist in the deployed shared objects.

Useful commands:

```bash
nm -D <shared-object> | grep -E 'aclInit|aclFinalize|aclrt|aclmdl|acldvpp'
readelf -Ws <shared-object> | grep -E 'aclInit|aclFinalize|aclrt|aclmdl|acldvpp'
```

Check for:

- Runtime initialization and memory APIs expected by the integration.
- Model load and execute APIs expected by the current code.
- DVPP APIs referenced by preprocess or decode code.

If a symbol is absent, do not "code to the docs". Code to the deployed ABI or update the deployment target first.

## Phase 6: Model Artifact Audit

Inspect the repository and answer:

- Which `.om` files are deployed.
- Which source model and ATC command produced them.
- Whether AIPP is embedded or external.
- Whether input shapes are static, dynamic, batched, or resolution-dependent.
- Whether the runtime device model matches the conversion target.

If conversion provenance is missing, state that runtime behavior is not reproducible yet.

## Phase 7: Data Path Audit

Only after the environment audit is complete for the active device context, map the runtime data path:

- Capture, decode, image loading, or tensor source.
- Allocator or memory owner.
- Host-to-device and device-to-host copy boundaries.
- DVPP or CPU preprocessing.
- AIPP usage.
- ACL model input staging.
- Output handling and postprocess.

Do not call the project "zero-copy" or "device-resident" until this map is explicit.

## Development Gate

Begin implementation only if:

- Driver, firmware, and device visibility are identified.
- Runtime libraries and tools are identified.
- Headers and runtime libraries are not obviously mismatched.
- Required symbols exist.
- OM artifact provenance is understood or explicitly marked unknown.
- The project's actual linkage and environment model is understood.
- Exactly one active device context is selected, unless the task is explicitly to implement multi-device support.

If any item is missing, report a blocker instead of guessing.

## Suggested Command Order

1. Run `scripts/detect-ascend-env.sh`.
2. Run `scripts/collect-ascend-debug.sh`.
3. Inspect project build files with `rg`.
4. Inspect binary dependencies with `ldd` or `readelf -d`.
5. Inspect library symbols with `nm -D` or `readelf -Ws`.
6. Compare findings against [version-audit.md](version-audit.md).
7. Only then inspect or change pipeline code.
