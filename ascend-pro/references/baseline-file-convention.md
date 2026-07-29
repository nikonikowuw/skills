# Baseline File Convention

## Purpose

Keep parser output separate from reviewed project knowledge. Generated evidence is a draft; it must
never replace annotations, verification history, or decisions made by a human reviewer.

## Layout

```text
.agent/ascend-pro/
  drafts/
    <context-id>.generated.md
  context/
    <context-id>.md
```

- `drafts/` contains replaceable parser output.
- `context/` contains reviewed context created from [context-template.md](context-template.md).
- `<context-id>` is a filename-safe composite identifier described in
  [device-scoped-context.md](device-scoped-context.md). It never contains a raw machine ID or serial.

Add `.agent/ascend-pro/context-key` and raw evidence bundles to `.gitignore` if a local workflow creates
them. Do not commit raw host identifiers or unreviewed diagnostic output.

## Workflow

1. Collect and sanitize evidence with `scripts/collect-ascend-debug.sh`.
2. Inspect the bundle before transferring or pasting it. Remove any project-specific value that should
   not leave the deployment environment.
3. Generate a draft:

   ```bash
   python3 /path/to/render-project-baseline.py ascend-evidence/ascend-evidence.txt --write-draft
   ```

4. Review it with [baseline-review-checklist.md](baseline-review-checklist.md).
5. Create or update `.agent/ascend-pro/context/<context-id>.md` using
   [context-template.md](context-template.md). Copy only verified facts from the draft.
6. Record source, date, target, and unresolved facts.
7. On later sessions, revalidate the identity and version fingerprint before reusing the reviewed file.

## Write Semantics

`render-project-baseline.py` follows these rules:

- `--write-draft` writes only under `.agent/ascend-pro/drafts/`.
- Missing safe identity data is an error for `--write-draft`; it never creates `unknown.md`.
- Existing output is an error. Pass `--force` only when intentionally replacing a generated draft.
- `-o <name>.generated.md` is available for explicit draft paths and has the same no-overwrite default.
- The renderer refuses evidence containing a raw machine ID. Sanitize first.
- Generated files use owner-only permissions; the renderer refuses symlink targets and reviewed-context paths.

Never point the renderer at `.agent/ascend-pro/context/`. Reviewed context is updated through deliberate
review, not parser overwrite.

## Cache Validation

File existence does not establish validity. Before using reviewed context, compare at least:

- pseudonymous host token and selected NPU serial token or device index;
- device model and host/container boundary;
- driver, firmware, CANN root/version, and loaded runtime libraries;
- header source and target binary linkage;
- OM artifact checksum or provenance when model behavior matters;
- `Last verified` date and any invalidation event.

Create a new context ID or mark the old context stale after a card replacement, device-index reassignment,
driver/CANN update, container image change, runtime path change, or OM regeneration.
