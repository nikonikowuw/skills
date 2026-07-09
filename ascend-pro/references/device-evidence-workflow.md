# Device Evidence Workflow

## Purpose

Use this workflow when Codex cannot directly access the target Ascend device. The user's pasted command output becomes the hardware and runtime baseline for implementation, scoped to a specific device model and deployment environment.

## Evidence Collection

Ask the user to run the commands from [device-command-checklist.md](device-command-checklist.md) on the target device or inside the exact deployment container. If the project runs in a container, collect both host-side and container-side evidence.

If there are multiple target devices, require one labeled evidence block per device:

```text
== Device Context: Ascend310P host video service ==
<command outputs>

== Device Context: Atlas200I-A2 container edge app ==
<command outputs>
```

Do not accept a mixed dump as authoritative. Ask the user to label which output belongs to which device model or deployment target.

Prefer complete command output over summaries. Small omissions often hide version or path mismatches.

## Baseline Rendering

After the user pastes evidence:

1. Save it to a temporary text file if useful.
2. Run `scripts/render-project-baseline.py` against the text.
3. Review the generated baseline manually using [baseline-review-checklist.md](baseline-review-checklist.md).
4. Correct parser mistakes before treating the baseline as authoritative.
5. Mark unknowns explicitly instead of filling them with assumptions.

## What The Baseline Must Cover

- One device-scoped section per target device model.
- Device model, NPU visibility, driver, firmware, kernel, and OS.
- CANN roots, tools, runtime libraries, headers, and Python packages for that device context.
- Project build and runtime linkage for that device context.
- OM artifact provenance and model conversion constraints for that device context.
- Device nodes and permissions.
- Open risks and missing facts.

## Rules For Later Work

- Use the reviewed baseline as the source of truth for device-specific claims.
- Before implementation, state the active device context ID. If more than one exists and none is selected, ask which one is targeted.
- Pass only the active device context to future agents by default; mention other contexts separately to avoid accidental `.so` or OM mixing.
- Do not contradict pasted evidence unless newer evidence supersedes it.
- If later code inspection reveals a different CANN path or model artifact than the baseline, update the baseline before continuing.
- If the baseline is incomplete, label code changes as provisional and state which device facts could invalidate them.
