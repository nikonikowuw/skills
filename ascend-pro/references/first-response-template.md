# First Response Template

## Purpose

Use this template when a user asks for Ascend development or optimization help but the device evidence has not been collected yet.

## Agent Behavior

The first response should:

1. State that implementation should wait until the device baseline is collected.
2. Give the user a concrete command checklist.
3. Tell the user exactly what to paste back.
4. Promise to turn that evidence into a project baseline for subsequent development.

## Suggested Response Shape

Use wording close to this:

```text
Before changing code, I need the target Ascend device and runtime baseline. On Ascend work, the device model, driver, firmware, CANN, headers, runtime libraries, container mounts, and OM artifacts must line up; coding first is risky.

Please run these on the target device, and if the app runs in a container, run the library and environment checks both on the host and inside the container. If you have multiple Ascend or Atlas device models, paste one labeled block per device, for example `== Device Context: Ascend310P host ==`.

1. Device and OS identity
   uname -a
   cat /etc/os-release
   npu-smi info
   npu-smi info -t board 2>/dev/null || true

2. Device nodes and permissions
   ls -l /dev/davinci* /dev/davinci_manager /dev/devmm_svm /dev/hisi_hdc 2>/dev/null
   groups

3. CANN tools and environment
   which npu-smi atc aclprof msame ais_bench 2>/dev/null
   atc --version 2>/dev/null || true
   printf 'ASCEND_HOME_PATH=%s\n' "${ASCEND_HOME_PATH:-}"
   printf 'ASCEND_TOOLKIT_HOME=%s\n' "${ASCEND_TOOLKIT_HOME:-}"

4. Ascend libraries
   find /usr/local/Ascend /usr /usr/local -maxdepth 6 \( -name 'libascendcl.so*' -o -name 'libacl_dvpp.so*' -o -name 'libacl_op_compiler.so*' -o -name 'libge_runner.so*' \) 2>/dev/null

5. Target binary linkage
   ldd <target-binary-or-so>
   readelf -d <target-binary-or-so>

6. Exported symbols
   nm -D <ascend-shared-object> | grep -E 'aclInit|aclFinalize|aclrt|aclmdl|acldvpp'
   readelf -Ws <ascend-shared-object> | grep -E 'aclInit|aclFinalize|aclrt|aclmdl|acldvpp'

7. Build-system and model clues from the project root
   rg -n 'ascend|CANN|ASCEND|aclrt|aclmdl|acldvpp|dvpp|aipp|atc|\\.om|LD_LIBRARY_PATH|find_library|target_link_libraries|include_directories|dlopen' .

After you paste that, I will turn it into a compact device-scoped project baseline, select the active device context with you, and use only that context as the development standard for code changes.
```

## Reference

For the full command set and fallback instructions, use [device-command-checklist.md](device-command-checklist.md). After generating a baseline draft, review it with [baseline-review-checklist.md](baseline-review-checklist.md). Store the reviewed version as `.agents/ascend-context.md` (see [baseline-file-convention.md](baseline-file-convention.md)).
