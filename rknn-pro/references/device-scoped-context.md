# Device-Scoped Context

## Purpose

Use this reference whenever a project or conversation mentions more than one Rockchip board model, SoC, BSP image, rootfs, container, SDK copy, or `.so` version. The goal is to prevent context pollution: applying one board's runtime facts to another board.

## Core Rule

Treat each target runtime as an indivisible context:

`device ID or label + board model + SoC + kernel/BSP + driver versions + userspace .so set + headers + exported symbols + container or rootfs + RKNN artifact`

Do not carry a library path, exported symbol, RGA capability, MPP memory mode, RKNN runtime feature, or performance conclusion from one context into another unless evidence explicitly proves they are the same.

## Context ID

Assign a short context ID before implementation:

```text
<device-id-or-label>-<soc>-<environment-fingerprint>-<purpose>
```

Examples:

- `camera-01-RK3568-a13f42c9-video-infer`
- `lab-rk3576-RK3576-42e91b0c-camera-pipeline`
- `demo-RK3588-91b72fe0-container`

When reporting or handing off context, put the active ID first.

## Required Fields Per Context

For each device-scoped context, record:

- Device identifier: board serial when available, otherwise a stable asset tag or user-provided label.
- Environment fingerprint derived from the observed software/runtime fields below.
- Board model and SoC.
- Kernel, BSP, and rootfs provenance.
- RGA driver version and debug node evidence.
- RKNN runtime and NPU driver evidence.
- `librga.so`, `librknnrt.so`, and `libmpp` or `librockchip_mpp.so` paths and version clues.
- Header roots used at compile time.
- Exported symbols checked from the actual runtime `.so`.
- RKNN artifact path, toolkit version, target SoC, input shape, and conversion provenance.
- Target binary linkage or `dlopen` behavior.

## Multi-Device Behavior

If evidence contains several boards or SoCs:

1. Split evidence into one section per board, SoC, or deployment target.
2. Create a device-scoped runtime matrix.
3. Mark a single active context before code changes.
4. Keep other contexts available as alternatives, not as merged facts.

If the user asks for a generic change that affects all boards, design an explicit compatibility strategy:

- Build-time profiles per board or SoC.
- Runtime selection by SoC or device tree compatible string.
- Per-board library and model artifact directories.
- A verification matrix with one row per supported board.

## Handoff Format

Use this shape when passing context to another agent or future turn:

```text
Active Rockchip runtime context: camera-01-RK3568-a13f42c9-video-infer
- Device identifier: camera-01 (board serial unavailable)
- Environment fingerprint: a13f42c9
- Board/SoC: Rockchip RK3568 EVB1, RK3568
- Kernel/BSP: <observed values or unknown>
- RGA driver: <version or unknown>
- Runtime libs: librga.so=<path>, librknnrt.so=<path>, libmpp.so=<path>
- Headers: <paths>
- RKNN artifact: <path and toolkit/version or unknown>
- Linkage: <ldd/readelf/dlopen facts>
- Open risks: <facts that could invalidate changes>

Other contexts exist: RK3576-vendor-BSP-camera-pipeline. Do not reuse its `.so`, driver, symbol, or RKNN facts unless explicitly selected.
```

## Red Flags

- The prompt says "Rockchip" but the project has several RK3568, RK3576, or RK3588 targets.
- `find` output shows several SDK roots and no `ldd` evidence.
- Host and container outputs are pasted together without labels.
- An RKNN artifact was converted for one SoC but the runtime board is another SoC.
- Headers come from a vendor SDK path while the binary loads runtime libraries from the rootfs.
- A performance result is quoted without board model, BSP, runtime library versions, input shape, and model artifact.
