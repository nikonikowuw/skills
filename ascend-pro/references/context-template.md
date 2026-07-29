# Reviewed Ascend Runtime Context: <context-id>

Use this template for `.agent/ascend-pro/context/<context-id>.md`. Replace placeholders; do not link back
to the installed skill with relative paths because the project and skill live in different directories.

## Metadata

- Context ID: `<filename-safe composite context ID>`
- Status: `reviewed | stale | provisional`
- Deployment: `host | container | VM | other`
- Purpose: `<runtime role>`
- Evidence source: `<sanitized bundle or commands>`
- Created: `YYYY-MM-DD`
- Last verified: `YYYY-MM-DD`
- Reviewer: `<name or role>`

## Identity Fingerprint

- Pseudonymous host token: `<h-...>`
- NPU serial token: `<s-... or unavailable>`
- Selected device index: `<index>`
- Device model/count: `<observed values>`
- Container image/digest: `<value or not applicable>`

## Runtime Stack

- Driver/firmware: `<observed values or unknown>`
- Kernel/OS: `<observed values>`
- CANN root/version/provenance: `<observed values>`
- ATC version: `<observed value or not applicable>`
- Loaded ACL/DVPP libraries: `<ldd/readelf/dlopen evidence>`
- Compile-time headers: `<paths/package>`
- Required exported symbols: `<verified list>`
- Python packages: `<versions or not applicable>`

## Model Artifact

- OM path/checksum: `<value or unknown>`
- Source model/checksum: `<value or unknown>`
- ATC command and log: `<value or unknown>`
- Target SoC, shapes, precision, dynamic policy: `<values>`
- AIPP configuration: `<path/checksum/summary or not applicable>`

## Data And Buffer Flow

| Stage | Owner/domain | Format and shape | Stride/size source | Copy or sync |
|---|---|---|---|---|
| Input | | | | |
| Preprocess | | | | |
| Model input | | | | |
| Inference output | | | | |
| Postprocess | | | | |

## Verified Device-Specific Rules

| Claim | Device/CANN scope | Evidence source | Verified date |
|---|---|---|---|
| | | | |

## Verification History

| Date | Fingerprint/check | Result |
|---|---|---|
| | | |

## Invalidation Events

- Card replacement or device-index reassignment
- Driver, firmware, CANN, container image, library path, headers, or OM change

## Open Risks

- [ ] `<unknown that could invalidate current work>`
