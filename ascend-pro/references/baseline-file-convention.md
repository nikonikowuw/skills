# Baseline File Convention

## Purpose

Use a stable in-repo location for the reviewed Ascend baseline so future turns can treat it as project context instead of reconstructing from chat history. The file must preserve device-scoped sections when the project supports multiple devices.

## Recommended Paths

Prefer these locations in order:

1. `.agents/ascend-context.md` (new standard — combined device baseline + API context)
2. `.agent-context/ascend-baseline.md` (legacy, kept for existing projects)
3. `docs/ascend-baseline.md` (fallback when only `docs/` exists)

`.agents/ascend-context.md` is a **combined context file** that includes:
- Device baseline (hardware, CANN, .so, symbols, model artifacts)
- Active device context selection
- Key API signatures relevant to the project
- Memory alignment rules (stride, buffer size formulas)
- Pointers to official docs via `ctx_search`

## Rule

Do not treat the generated file as final until it has passed the review steps in [baseline-review-checklist.md](baseline-review-checklist.md).

## Agent Workflow

1. Collect device evidence (user runs detection scripts, or paste from target device).
2. Generate a baseline draft from pasted device evidence using `scripts/render-project-baseline.py`.
3. Append API context (key signatures, alignment rules, active AIPP configs, ctx_search pointers).
4. Review and correct the combined context manually.
5. If multiple devices, select one active device context ID.
6. Write the final context to `.agents/ascend-context.md`.
7. Read this file first in every future session before making code changes.

## Script Support

`scripts/render-project-baseline.py` supports:

- `-o .agents/ascend-context.md`
  - Writes to the standard combined context path.
- `--write-default`
  - Writes to `.agents/ascend-context.md` if `.agents/` exists, otherwise `.agent-context/ascend-baseline.md`, then `docs/ascend-baseline.md`.
- `-o <path>`
  - Writes to an explicit path.

## Suggested Usage

From the project root:

```bash
python3 /path/to/render-project-baseline.py pasted-device-evidence.txt -o .agents/ascend-context.md
```

Or with pasted stdin:

```bash
cat pasted-device-evidence.txt | python3 /path/to/render-project-baseline.py --write-default
```

After generating the baseline portion, manually append API context following the guide in SKILL.md.
