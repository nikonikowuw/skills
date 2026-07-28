# Device Baseline Workflow

Single reference for the full device-evidence loop: first response when no baseline exists →
collect evidence on the board → turn it into a reviewed baseline → store it as
`.agents/context/rknn-context/{machine_id}.md`. The command checklist in Step 2 is the only copy in this skill;
other documents link here instead of repeating it.

For multi-board/multi-BSP context rules (context IDs, handoff format, red flags), see
[device-scoped-context.md](device-scoped-context.md). For repository-side onboarding phases,
see [project-onboarding-workflow.md](project-onboarding-workflow.md).

## Step 1 — First Response When No Baseline Exists

When a user asks for Rockchip development or optimization help and no device evidence has been
collected yet, the first response should:

1. State that source-only analysis can start immediately, and which board-specific conclusions
   (ABI, allocator, driver, performance) require a device baseline.
2. Give the user the Standard Collection Commands below as a paste-ready checklist.
3. Tell the user exactly what to paste back (see Minimum Required Sections).
4. If they have multiple Rockchip boards, SoCs, rootfs images, or containers, ask for one
   labeled block per target (see the labeling rule below).
5. Promise to turn that evidence into a device-scoped project baseline used as the development
   standard for subsequent code changes.

## Step 2 — Standard Collection Commands

Run on the target device and paste the outputs back. Collect a board serial when available; if
the platform exposes none, use a stable asset tag or user-provided label and record the
limitation. Device identity alone does not validate the software environment — kernel/BSP,
drivers, libraries, headers, rootfs/container, and model artifacts form the environment
fingerprint.

### Multi-device labeling rule

If the project supports multiple board models, SoCs, rootfs images, or containers, run the
checklist separately for each target and wrap each output with a label:

```text
== Device Context: RK3568 EVB1 Debian video service ==
<outputs>

== Device Context: RK3576 vendor BSP camera pipeline ==
<outputs>
```

Without labels, BSP, driver, `.so`, header, and RKNN artifact facts are easy to mix.

### 1. Board, kernel, and OS identity

```bash
uname -a
cat /etc/os-release
cat /sys/firmware/devicetree/base/model
cat /sys/firmware/devicetree/base/compatible
cat /proc/cpuinfo
```

### 2. Rockchip-related drivers and device nodes

```bash
lsmod | grep -Ei 'rockchip|rga|mpp|vcodec|rknpu|iep'
ls -l /dev/media* /dev/video* /dev/rga /dev/dri/renderD* 2>/dev/null
dmesg | grep -Ei 'rockchip|rga|mpp|rknpu|vcodec|iep'
```

### 3. RGA driver and debug nodes

```bash
cat /sys/kernel/debug/rkrga/driver_version 2>/dev/null
cat /proc/rkrga/driver_version 2>/dev/null
cat /sys/kernel/debug/rkrga/debug 2>/dev/null
cat /proc/rkrga/debug 2>/dev/null
```

### 4. Rockchip shared libraries

```bash
find /usr /usr/local -maxdepth 4 \( -name 'librga.so*' -o -name 'librknnrt.so*' -o -name 'librockchip_mpp.so' -o -name 'libmpp.so' \) 2>/dev/null
```

### 5. Binary linkage

Replace `<target-binary-or-so>` with the real executable or shared object from the project.

```bash
ldd <target-binary-or-so>
readelf -d <target-binary-or-so>
```

### 6. Exported symbol checks

Replace `<rockchip-shared-object>` with the actual deployed library path, for example
`librga.so`, `librknnrt.so`, or `libmpp.so`.

```bash
nm -D <rockchip-shared-object> | grep -E 'importbuffer_fd|wrapbuffer_fd|imcheck|rga|rknn_|mpi'
readelf -Ws <rockchip-shared-object> | grep -E 'importbuffer_fd|wrapbuffer_fd|imcheck|rga|rknn_|mpi'
strings <rockchip-shared-object> | grep -Ei 'version|rknn|rga_api'
```

### 7. Project build clues

Run this from the project root:

```bash
rg -n 'rknn|rga|im2d|mpp|rk_mpi|find_library|target_link_libraries|include_directories|dlopen' .
```

### Minimum required sections

If the full output is too large, paste at least:

- `uname -a` and `/etc/os-release`
- device tree `model` and `compatible`
- RGA driver version
- the `find` results for `librga`, `librknnrt`, and `libmpp`
- `ldd` and `readelf -d` for the target binary
- one symbol dump for each relevant Rockchip `so`
- the key build-system lines showing include and link paths
- which board, SoC, BSP, rootfs, or container each output block belongs to

### Preferred shortcut

Resolve bundled paths from the directory containing `SKILL.md`. Run the commands with the target
project as the working directory so generated reports and context stay with that project:

```bash
<skill-root>/scripts/rknn-diag.sh          # single-command diagnostic reporter
# Or legacy individual scripts:
# bash <skill-root>/scripts/detect-rockchip-env.sh
# bash <skill-root>/scripts/collect-rockchip-debug.sh
```

Then paste the resulting report or the relevant excerpts.

## Step 3 — Turn Evidence Into a Baseline

Rule: do not treat guessed board details as development truth when user-provided device evidence
exists. If evidence covers multiple boards, do not merge the outputs — require one labeled block
per device context.

Generate a draft with the bundled parser, or write it manually:

```bash
# Auto-detect machine_id and write to .agents/context/rknn-context/{machine_id}.md:
python3 <skill-root>/scripts/render-project-baseline.py pasted-evidence.txt --write-default

# Or specify custom context ID:
python3 <skill-root>/scripts/render-project-baseline.py pasted-evidence.txt --write-default --context-id my-rk3588-board
```

Use this structure (the parser emits the same shape):

```text
Project baseline

Active device context
- Active context ID:
- Rule:

Board baseline
- SoC:
- Board model:
- Compatible string:

Kernel and BSP baseline
- Kernel:
- OS release:
- BSP or image source:

Driver baseline
- RGA driver:
- V4L2 or media nodes:
- DRM or display nodes:
- Other relevant modules:

Userspace library sightings
- librga:
- librknnrt:
- libmpp or librockchip_mpp:
- Which copy the project actually uses:
- Rule:

ABI and symbol baseline
- Required RGA symbols present:
- Required RKNN symbols present:
- Required MPP symbols present:
- Any symbol mismatches:

Project link and include baseline
- Header roots:
- Library roots:
- Bundled vendor SDK paths:
- Runtime loading behavior:

Device-scoped runtime contexts
- One section per labeled board, SoC, BSP, rootfs, or container context

Open risks
- Unknowns that still block strong conclusions
```

Keep the baseline short but concrete — it is a standing context block for future turns. Record
only observed versions, selected headers/libraries, model artifacts, unresolved gaps, and the
active context; keep API reference text in this skill rather than copying it into every project.

## Step 4 — Review the Draft (Mandatory)

The generated baseline is a draft, not final truth. Manually verify:

1. **Board identity** — the model line is really the board (not a kernel line); the SoC is
   unambiguous; each board/SoC/BSP/container is split into its own device context; the active
   context is named before any implementation recommendation.
2. **Kernel and BSP** — the kernel string is correctly captured; BSP/image provenance still
   unknown is worth asking about.
3. **Drivers** — the RGA driver version is actually present (not parser inference); missing
   device nodes may simply be absent from the pasted excerpt.
4. **Userspace libraries** — listed `.so` files are real deployment candidates; watch for
   multiple conflicting copies; the project's actual runtime copy may still be unknown; keep
   `.so`/header/driver/symbol/RKNN-artifact facts separate per board context.
5. **ABI and symbols** — required symbols are present in the correct library; absent symbols may
   be an incomplete paste rather than a real ABI gap.
6. **Project integration** — include/link paths reflect the real build; look for `dlopen`,
   sysroot, rpath, or bundled SDK usage the parser missed.
7. **Open risks** — add missed unknowns; soften any "no obvious gaps" statement that is too
   strong for the evidence quality.

After review, produce: `Reviewed baseline`, `Corrections made to parser draft`, `Still unknown`,
and `Questions to ask the user before implementation`.

**Escalation rule**: if the active driver stack, actual runtime library copy, required exported
symbols, BSP provenance, or the active board context (when several exist) remain uncertain, stop
short of implementation and ask for more evidence.

## Step 5 — Store the Baseline

The baseline is stored at a per-device path:

1. `.agents/context/rknn-context/{machine_id}.md` (recommended per-device baseline)
2. `.agents/rknn-context.md` (legacy single-file baseline fallback)
3. `.agent-context/rockchip-baseline.md` (legacy fallback)
4. `docs/rockchip-baseline.md` (project documentation fallback)

`scripts/render-project-baseline.py` supports `--write-default` (auto-detects `machine_id` and creates `.agents/context/rknn-context/{machine_id}.md`), `--context-id <label>` to override the machine ID, and `-o <path>` for an explicit target. Do not store the file until it has passed the Step 4 review.

## Using the Baseline

- Treat the selected device context as the default hardware/runtime context for the project, and
  state the active context ID before implementation. If several contexts exist and none is
  selected, ask which board is targeted.
- Pass only the active device context to future agents by default; mention other contexts
  separately to avoid `.so`/driver/RKNN-artifact mixing.
- If a proposed change depends on a capability the baseline does not support, flag it before
  implementation; if later requests conflict with the baseline, call out the conflict instead of
  silently switching assumptions.
- Update the file when the user supplies better evidence, and refresh it when the device ID,
  BSP/kernel, runtime libraries, headers, rootfs/container, or RKNN artifacts change.
