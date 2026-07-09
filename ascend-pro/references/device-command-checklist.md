# Device Command Checklist

## Purpose

Use this checklist when you need exact commands for a user to run on a target Ascend device.

If the project supports multiple device models, tell the user to run the checklist separately for each device and wrap each output with a label:

```text
== Device Context: Ascend310P host video service ==
<outputs>

== Device Context: Atlas200I-A2 container edge app ==
<outputs>
```

Without labels, host, container, and device-specific `.so` facts are easy to mix.

> ⚠️ **Device serial number is mandatory.** The chip serial number (`chip_sn`) uniquely identifies a physical device. Even same-model devices with different driver versions are separate contexts. Always collect it.

## Host Or Bare-Metal Device

```bash
uname -a
cat /etc/os-release
npu-smi info
npu-smi info -t board 2>/dev/null || true
npu-smi info -t chip 2>/dev/null || true
npu-smi info -t usages 2>/dev/null || true
ls -l /dev/davinci* /dev/davinci_manager /dev/devmm_svm /dev/hisi_hdc 2>/dev/null
groups
```

The serial number is in the output of `npu-smi info -t board` (look for `Chip Sn` or `Serial Number`). Record it as the context key.

## CANN Tools And Environment

```bash
which npu-smi atc aclprof msame ais_bench 2>/dev/null
atc --version 2>/dev/null || true
aclprof --help 2>/dev/null | head -n 20 || true
printf 'ASCEND_HOME_PATH=%s\n' "${ASCEND_HOME_PATH:-}"
printf 'ASCEND_TOOLKIT_HOME=%s\n' "${ASCEND_TOOLKIT_HOME:-}"
printf 'LD_LIBRARY_PATH=%s\n' "${LD_LIBRARY_PATH:-}"
```

Avoid posting unrelated environment variables. They may contain credentials.

## Library And Header Discovery

```bash
find /usr/local/Ascend /usr /usr/local -maxdepth 6 \
  \( -name 'libascendcl.so*' -o -name 'libacl_dvpp.so*' -o -name 'libacl_op_compiler.so*' -o -name 'libge_runner.so*' -o -name 'acl.h' -o -name 'acl_dvpp.h' \) 2>/dev/null
```

## Target Binary Linkage

```bash
ldd <target-binary-or-so>
readelf -d <target-binary-or-so>
```

If the project uses `dlopen`, also run:

```bash
rg -n 'dlopen|RTLD_|libascendcl|libacl_dvpp|ASCEND_HOME_PATH|LD_LIBRARY_PATH' .
```

## Exported Symbols

```bash
nm -D <ascend-shared-object> | grep -E 'aclInit|aclFinalize|aclrt|aclmdl|acldvpp'
readelf -Ws <ascend-shared-object> | grep -E 'aclInit|aclFinalize|aclrt|aclmdl|acldvpp'
```

Use `libascendcl.so` for ACL runtime and model APIs. Use the DVPP-related shared object that the installed CANN package actually provides for DVPP symbol checks.

## Project Search

Run from the project root:

```bash
rg -n 'ascend|CANN|ASCEND|acl/acl|aclrt|aclmdl|acldvpp|dvpp|aipp|atc|\\.om|aclrtMemcpy|aclrtSynchronizeStream|find_library|target_link_libraries|include_directories|dlopen' .
```

## Model Artifact Evidence

Collect:

```bash
find . -maxdepth 6 \( -name '*.om' -o -name '*aipp*.cfg' -o -name '*atc*.log' -o -name '*.onnx' \) 2>/dev/null
```

If available, paste:

- The ATC command used to generate the `.om`.
- Conversion logs.
- Input shape and dynamic shape policy.
- AIPP config file.

## Container Deployments

On the host:

```bash
npu-smi info
ls -l /dev/davinci* /dev/davinci_manager /dev/devmm_svm /dev/hisi_hdc 2>/dev/null
docker inspect <container> 2>/dev/null | grep -Ei 'davinci|ascend|device|mount|LD_LIBRARY_PATH' -C 3 || true
```

Inside the container, repeat the CANN tools, library, and linkage checks. Host and container evidence must be reviewed together.
