# First Response Template

Use this only when the selected task requires Evidence Gate 1 or 2 and the needed facts cannot be obtained
from the repository or target environment. Do not use it for explanations, meta-work, or source-only review.

Adapt the request to the task. Ask for the smallest evidence set that can support the next decision:

```text
This change depends on the selected Ascend runtime. I can continue with version-independent work now, but
before choosing device-specific APIs or claiming compatibility I need: <exact missing facts>.

Please run the ascend-pro sanitized collector on the target runtime:

  bash scripts/collect-ascend-debug.sh \
    --output ascend-evidence \
    --deployment <host-or-container> \
    --device-index <index> \
    --target-binary <application-or-so>

Inspect every generated file before sharing it. The collector omits common high-risk diagnostics and
redacts common identifiers, but automated redaction is not a confidentiality guarantee. Do not paste raw
/etc/machine-id, raw board serials, credentials, full environment output, or full container metadata.
After inspection, `ascend-evidence/ascend-evidence.txt` is the combined renderer input.
```

For ATC-only work, request only target SoC, installed `atc --version`, model input contract, and the exact
conversion command/log. For DVPP, add formats, dimensions, actual strides, and device/CANN version. For
performance work, add a reproducible workload and stage timings.

Use [device-command-checklist.md](device-command-checklist.md) when the helper cannot be run. Render the
sanitized evidence as a generated draft, review it, and deliberately create a reviewed context following
[baseline-file-convention.md](baseline-file-convention.md).
