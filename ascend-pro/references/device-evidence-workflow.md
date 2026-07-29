# Device Evidence Workflow

## When To Use

Use this workflow only for device-sensitive implementation, deployment, runtime diagnosis, or performance
work. Do not require it for skill maintenance, conceptual explanations, or source-only review.

## Collection

Prefer direct read-only inspection when the target is accessible. Otherwise ask the user to run the bundled
collector from a trusted copy of this skill:

```bash
bash scripts/collect-ascend-debug.sh \
  --output ascend-evidence \
  --deployment host \
  --device-index 0 \
  --target-binary /path/to/application
```

The collector intentionally omits `dmesg`, user groups, full CPU/memory dumps, raw machine ID, and the full
environment. It derives pseudonymous identity tokens and sanitizes common serial, home-directory, IP, and MAC fields.
Sanitization is risk reduction, not a guarantee: the user must inspect every file before sharing it.
Use `<output>/ascend-evidence.txt` as renderer input after that inspection; the numbered files preserve
individual command output for review.

For a container deployment, run once on the host and once inside the exact container with different
`--deployment` values. For several NPUs or targets, run once per selected device index and label each block.
Use [device-command-checklist.md](device-command-checklist.md) when the helper scripts cannot be copied.

## Rendering And Review

1. Combine sanitized text only when blocks have explicit `== Device Context: ... ==` labels.
2. Run `scripts/render-project-baseline.py <evidence>`. Inspect stdout first.
3. Correct parser false positives and missing facts. The parser is not an authority.
4. Use `--write-draft` only after identity fields are present.
5. Review with [baseline-review-checklist.md](baseline-review-checklist.md).
6. Transfer verified facts into [context-template.md](context-template.md).
7. Select the active reviewed context before device-dependent code changes.

## Minimum Evidence By Task

| Task | Minimum evidence |
|---|---|
| ATC/OM conversion | target SoC, ATC/CANN version, source model/input contract, exact command |
| AscendCL build/runtime | selected headers, loaded libraries, required symbols, target linkage |
| DVPP/AIPP | device/CANN, pixel formats, dimensions, strides, allocation APIs, installed API surface |
| Runtime failure | device visibility, driver/firmware, CANN, loaded libraries, logs, OM provenance |
| Performance | complete runtime context plus fixed workload and per-stage timings |

If evidence below the required level is unavailable, continue only with version-independent work, label
device-specific decisions provisional, and state exactly what observation would validate them.
