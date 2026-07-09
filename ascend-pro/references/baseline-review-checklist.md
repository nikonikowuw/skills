# Baseline Review Checklist

## Purpose

Use this checklist after `scripts/render-project-baseline.py` creates an Ascend baseline draft. The parser is a helper, not an authority.

## Review Items

- Confirm the device model and NPU visibility were detected from real command output, not from a file path or project name.
- Confirm there is a separate baseline section for each device model when multiple devices appear.
- Confirm the active device context is named before any implementation recommendation.
- Confirm driver and firmware versions are present or explicitly unknown.
- Confirm CANN roots and runtime libraries correspond to the project runtime, not just an unused toolkit install.
- Confirm `.so`, header, symbol, Python package, and OM facts are not merged across device models.
- Confirm the headers and libraries appear to come from the same CANN package family.
- Confirm the target binary linkage or `dlopen` behavior is represented.
- Confirm OM artifact provenance is captured or marked unknown.
- Confirm container host and container facts are not mixed without explanation.
- Confirm open risks are actionable and not generic filler.

## Corrections To Make Manually

- Remove false library paths that came from docs or comments.
- Split host-side and container-side evidence when both appear.
- Split multi-device evidence into separate device context blocks.
- Add exact target binary names when known.
- Add exact model artifact names and conversion commands when known.
- Mark unsupported claims as unknown instead of inferred.

## Acceptance Gate

Only treat the baseline as development context after it states:

- What is known.
- What remains unknown.
- Which unknowns can invalidate the planned code change.
