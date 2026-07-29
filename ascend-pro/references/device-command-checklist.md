# Device Command Checklist

Use this only when the bundled collector cannot run. Prefer
`scripts/collect-ascend-debug.sh`, which derives safe identity tokens and sanitizes output.

## Privacy Rules

- Do not paste `/etc/machine-id`, raw board/chip serials, complete environment output, `dmesg`, user groups,
  home-directory contents, container inspection JSON, or credentials.
- Replace serial values with stable local tokens or `<redacted>`.
- Inspect every command result before transferring it. Command output can contain project-sensitive paths.
- Label host and container blocks separately. Run once per selected NPU device index.

## Context Label

Start each block with non-sensitive metadata:

```text
== Device Context: host device-0 ==
Host Token: h-<locally-derived-token>
Deployment: host
Device Index: 0
Collected UTC: YYYY-MM-DDTHH:MM:SSZ
```

If a pseudonymous host token cannot be generated, use `unavailable`; do not substitute the raw machine ID.

## System And Device

```bash
uname -a
sed -n 's/^PRETTY_NAME=//p' /etc/os-release
npu-smi info
npu-smi info -t board -i 0 2>/dev/null || true
npu-smi info -t chip -i 0 2>/dev/null || true
ls -l /dev/davinci* /dev/davinci_manager /dev/devmm_svm /dev/hisi_hdc 2>/dev/null || true
```

Redact serial-number fields before sharing. Retain device index, model, driver/firmware, health, and
visibility fields needed for diagnosis.

## CANN Tools And Environment

```bash
command -v npu-smi atc aclprof msprof msame ais_bench 2>/dev/null || true
atc --version 2>/dev/null || true
printf 'ASCEND_HOME_PATH=%s\n' "${ASCEND_HOME_PATH:-}"
printf 'ASCEND_TOOLKIT_HOME=%s\n' "${ASCEND_TOOLKIT_HOME:-}"
printf 'ASCEND_AICPU_PATH=%s\n' "${ASCEND_AICPU_PATH:-}"
```

Do not print the entire environment or `LD_LIBRARY_PATH`. If runtime search paths are relevant, extract only
Ascend-related entries and inspect them before sharing.

## Libraries, Headers, Linkage, And Symbols

Search only known Ascend roots rather than all of `/usr`:

```bash
find "${ASCEND_HOME_PATH:-/usr/local/Ascend}" -maxdepth 7 \
  ( -name 'libascendcl.so*' -o -name 'libacl_dvpp.so*' \
  -o -name 'libacl_op_compiler.so*' -o -name 'libge_runner.so*' \
  -o -name 'acl.h' -o -name 'acl_rt.h' -o -name 'acl_mdl.h' -o -name 'acl_dvpp.h' ) \
  2>/dev/null

ldd <target-binary-or-so>
readelf -d <target-binary-or-so>
readelf -Ws <actual-loaded-ascend-so> | rg 'aclInit|aclFinalize|aclrt|aclmdl|acldvpp'
```

For `dlopen`, inspect the repository and runtime-resolved paths. A discovery scan does not prove which
library the application loads.

## Model Evidence

Collect only paths relevant to the selected deployment and record checksums where practical:

```bash
find <model-directory> -maxdepth 3 \
  ( -name '*.om' -o -name '*.onnx' -o -name '*aipp*.cfg' -o -name '*atc*.log' ) \
  2>/dev/null
sha256sum <selected-model.om>
```

Also retain the exact ATC version/command, source model checksum, target SoC, input names/shapes/layouts,
precision policy, dynamic-shape policy, and AIPP config.

## Container Deployment

Collect separate host and in-container blocks. Record only the relevant device mounts, Ascend runtime
mounts, and container image digest. Do not paste full `docker inspect` output. Verify host driver/device
visibility together with the libraries and headers actually used inside the container.
