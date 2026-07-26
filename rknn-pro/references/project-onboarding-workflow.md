# Project Onboarding Workflow

## Purpose

Use this workflow before writing or modifying Rockchip performance code in an unfamiliar repository. The goal is to prevent development against the wrong driver, wrong shared object, wrong headers, or an imagined API surface.

## Rule

Start source-only analysis immediately when it does not depend on board facts. Before changing ABI,
allocator, buffer layout, core masks, or performance-sensitive integration, complete the relevant
phases below or state exactly which target facts remain unverified.

## Phase 1: Board and BSP Identification

Record for the active target board:

- Board model from `/sys/firmware/devicetree/base/model`
- Compatible string from `/sys/firmware/devicetree/base/compatible`
- Kernel version from `uname -a`
- OS release from `/etc/os-release`
- BSP or vendor image source if known

If the repository is supposed to run on multiple boards, SoCs, BSP images, or containers, create separate device context IDs before coding. Do not merge their libraries, drivers, headers, or RKNN artifacts into one baseline.

## Phase 2: Driver and Device Audit

Identify which subsystems are actually present:

- V4L2 nodes: `/dev/video*`, `/dev/media*`
- DRM render nodes: `/dev/dri/renderD*`
- RGA nodes and debug entries
- NPU-related kernel modules or devices when visible

Check (exact commands: sections 2–3 of the
[device-baseline-workflow.md](device-baseline-workflow.md) checklist):

- Rockchip-related modules via `lsmod`
- RGA driver version nodes under `/sys/kernel/debug/rkrga` or `/proc/rkrga`
- `dmesg` for driver init, fallback, or parameter errors

Required output:

- Which media, preprocess, display, and inference drivers appear active
- Which critical nodes are missing

## Phase 3: Shared Library Audit

Find the actual deployed libraries for the active device context, not the ones the developer assumes exist.

Search for:

- `librga.so*`
- `librknnrt.so*`
- `librockchip_mpp.so`
- `libmpp.so`

Check:

- Where each library is located
- Whether the project links by system path, rpath, copied SDK path, or container mount
- Whether multiple conflicting copies exist

Exact commands: sections 4–5 of the [device-baseline-workflow.md](device-baseline-workflow.md)
checklist (`find` for the Rockchip `.so` set, then `ldd` / `readelf -d` on the target binary).

If more than one plausible Rockchip userspace stack is installed, stop and resolve which one the project really uses for the selected board context.

## Phase 4: Header and API Audit

Check the compile-time API surface before changing code.

Locate headers for:

- `im2d` or `rga`
- `rk_mpi`
- `rknn_api`

Verify:

- Include paths used by the project
- Header versions or version macros when available
- Whether the headers match the runtime libraries found on the board or rootfs

Failure pattern:

- The code compiles against one SDK snapshot but runs with a different rootfs library set.

## Phase 5: Exported Symbol Audit

Confirm the required runtime APIs exist in the deployed shared objects. Exact commands:
section 6 of the [device-baseline-workflow.md](device-baseline-workflow.md) checklist
(`nm -D` / `readelf -Ws` / `strings` on each Rockchip shared object).

Check for:

- The exact RGA import or wrap APIs the code plans to call
- RKNN Runtime entry points expected by the integration
- MPP interfaces referenced by the current repository

If a symbol is absent, do not “code to the docs”. Code to the deployed ABI or update the deployment target first.

## Phase 6: Project Integration Audit

Inspect the repository and answer:

- Which binaries or shared objects are built here
- Which prebuilt vendor libraries are committed into the tree
- Whether CMake, Make, or Bazel picks headers and libs from SDK directories, sysroot, or host system
- Whether runtime loading happens through `dlopen` instead of normal linking

Required outcome:

- A concrete map from source code includes and link flags to deployed runtime files

## Phase 7: Buffer Path Audit

Only after the environment audit is complete for the active board context, map the runtime data path:

- Capture or decode source
- Buffer allocator or owner
- DMA-BUF export or import path
- RGA usage
- RKNN input staging
- Postprocess and sink

Do not call the project “zero-copy” until this map is explicit.

## Development Gate

Begin implementation only if:

- Drivers are identified
- Runtime libraries are identified
- Headers and runtime libraries are not obviously mismatched
- Required symbols exist
- The project's actual linkage model is understood
- Exactly one active device context is selected, unless the task is explicitly to implement multi-board support

If any item is missing, report a blocker instead of guessing.

## Suggested Command Order

1. Run `scripts/rknn-diag.sh` (or the legacy `detect-rockchip-env.sh` + `collect-rockchip-debug.sh`)
2. Inspect project build files with `rg`
3. Inspect binary dependencies with `ldd` or `readelf -d`
4. Inspect library symbols with `nm -D` or `readelf -Ws`
5. Compare findings against [version-audit.md](version-audit.md)
6. Only then inspect or change pipeline code
