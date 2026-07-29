# Device-Scoped Context

## Core Rule

Treat each deployed runtime as an indivisible context:

```text
pseudonymous host token + NPU identity + device model + driver/firmware + CANN fingerprint
+ loaded libraries + headers + deployment boundary + OM artifact
```

Do not transfer a library path, exported symbol, ATC flag, AIPP config, alignment value, or performance
conclusion between contexts without evidence that the relevant fields match.

## Pseudonymous Identity

Do not ask the user to paste `/etc/machine-id` or raw board serials. The collection helper derives:

- `host token`: an application-specific HMAC-derived token calculated locally from machine ID;
- `serial token`: a locally HMAC-derived token for board/chip serial fields when those fields exist;
- `device index`: the selected runtime index, retained because one host may expose several NPUs.

These tokens support correlation without storing the original identifiers. They are not anonymous,
authentication credentials, or proof of device identity; a party with candidate values can try to derive
matching tokens. Keep evidence access-controlled. Containers may share a host token, device indexes may
change, and cloned systems can contain bad identity data. Always validate the full fingerprint.

## Context ID

Use:

```text
<host-token>-<serial-token-or-device-index>-<host-or-container>-<cann-fingerprint>
```

Example: `h-8f21a94c-s-311af027-container-c-73f102b0`.

Only lowercase ASCII letters, digits, dots, underscores, and hyphens are allowed in filenames. Device
model and purpose belong in context metadata rather than the filename.

## Required Fields

Record for each context:

- pseudonymous host token, serial token when available, selected NPU index, and device model/count;
- driver, firmware, kernel, OS, host/container boundary, and container image identifier when relevant;
- CANN root, version, package provenance, and tool versions;
- actual loaded `libascendcl.so` and DVPP libraries, not only discovery results;
- compile-time header roots and exported symbols required by the code;
- target binary linkage or `dlopen` behavior;
- Python runtime packages when applicable;
- OM checksum/provenance, ATC command/version, target SoC, shapes, precision, and AIPP config;
- source date, last verification date, invalidation events, and open risks.

## Multi-Device Behavior

1. Collect one labeled evidence block per runtime target.
2. Give each target its own reviewed context file.
3. Select exactly one active context before a device-dependent change.
4. Keep other contexts as separate alternatives.
5. For multi-target code, define build/runtime selection and a verification matrix with one row per target.

Host and container are separate deployment contexts even when they share the same host and physical NPU.
They may use different headers, runtime libraries, environment paths, and OM artifacts.

## Reuse Decision

Reuse cached context only when current evidence matches all fields that can affect the requested task. For
example, a documentation question may need only CANN version, while a performance comparison needs the
entire runtime and workload fingerprint. Mark mismatches as stale and refresh before drawing conclusions.

## Red Flags

- Several CANN roots are discovered but actual binary linkage is missing.
- Host and container output is mixed without labels.
- A serial token or selected device index changed unexpectedly.
- The OM target or checksum differs from the reviewed artifact.
- Headers come from one package while runtime libraries load from another.
- A performance number lacks device, runtime, model, shape, and workload identity.
