# Device-Scoped Context

## Purpose

Use this reference whenever a project or conversation mentions more than one Ascend device model, more than one CANN install, multiple containers, or multiple `.so` versions. The goal is to prevent context pollution: applying one device's runtime facts to another device.

## Core Rule

Treat each target runtime as an indivisible context:

`chip serial number + device model + driver/firmware + CANN root + runtime .so set + headers + Python packages + container or host environment + OM artifact`

The **chip serial number** (`chip_sn`) is the unique identifier. Even the same device model with a different driver version is a different context. Always verify the serial number matches before reusing a cached context.

Do not carry a library path, exported symbol, ATC flag, AIPP config, or performance conclusion from one context into another unless the evidence explicitly proves they are the same (same serial number, same driver, same CANN version).

## Context ID

Assign a context ID that includes the chip serial number:

```text
<chip-sn>-<device-model>-<host-or-container>-<purpose>
```

Examples:

- `SN0123456789-Ascend310P-host-video-infer`
- `SN9876543210-Atlas200I-A2-container-edge-app`
- `SN1122334455-Ascend910B-host-batch-infer`

When reporting or handing off context, put the active ID first. The serial number ensures you never confuse two physically different devices.

## Required Fields Per Context

For each device-scoped context, record:

- **Chip serial number** (`chip_sn`) — mandatory, unique per device. Get via `npu-smi info -t board`.
- Device model and NPU count.
- Driver and firmware versions.
- Kernel and OS image.
- Host or container boundary.
- CANN root and package provenance.
- `libascendcl.so` path and version clues.
- DVPP-related library path and version clues when media acceleration is involved.
- Header roots used at compile time.
- Exported symbols checked from the actual runtime `.so`.
- Python packages when Python is part of runtime or benchmark.
- OM artifact path, ATC command, target device, input shape, precision, and AIPP config.
- Target binary linkage or `dlopen` behavior.

## Multi-Device Behavior

If evidence contains several devices:

1. Split evidence into one section per device model or deployment target.
2. Create a device-scoped runtime matrix.
3. Mark a single active context before code changes.
4. Keep other contexts available as alternatives, not as merged facts.

If the user asks for a generic change that affects all devices, design an explicit compatibility strategy:

- Build-time profiles per device.
- Runtime selection by device model.
- Per-device library and model artifact directories.
- A verification matrix with one row per supported device.

## Handoff Format

Use this shape when passing context to another agent or future turn:

```text
Active Ascend runtime context: SN0123456789-Ascend310P-host-video-infer
- Chip serial number: SN0123456789
- Device: Ascend310P, 1 NPU
- Driver/firmware: <observed values or unknown>
- CANN root: /usr/local/Ascend/ascend-toolkit/latest
- Runtime libs: libascendcl.so=<path>, libacl_dvpp.so=<path>
- Headers: <paths>
- OM artifact: <path and ATC command or unknown>
- Linkage: <ldd/readelf/dlopen facts>
- Open risks: <facts that could invalidate changes>

Other contexts exist: SN9876543210-Atlas200I-A2-container-edge-app. Do not reuse its .so or OM facts unless explicitly selected.
```

## Red Flags

- The prompt says "Ascend" but the project has several Atlas or Ascend targets.
- `find` output shows several CANN roots and no `ldd` evidence.
- Host and container outputs are pasted together without labels.
- An OM file name includes one device target but the runtime is another device.
- Headers come from a toolkit path while the binary loads runtime libraries from a different mount.
- A performance result is quoted without device model, CANN version, input shape, and model artifact.
