# Baseline Review Checklist

The renderer is a parser, not an authority. Complete this before using a generated draft as runtime context.

## Privacy And Provenance

- [ ] No raw machine ID, board/chip serial, credential, full environment, or unrelated diagnostic remains.
- [ ] Evidence date, collection boundary, selected device index, and safe identity tokens are recorded.
- [ ] Host and container evidence are separate and traceable to their commands.

## Identity And Stack

- [ ] Device model/count came from runtime evidence rather than file names, OM names, or ATC flags.
- [ ] Driver, firmware, CANN/tool versions, and deployment boundary are present or explicitly unknown.
- [ ] Card/index changes, container image changes, and cloned-host identity risks were considered.
- [ ] Multiple targets have separate context IDs; one active context is selected.

## Build And Runtime

- [ ] Discovery paths are distinguished from actual loaded libraries.
- [ ] Target linkage or `dlopen` resolution proves the libraries used at runtime.
- [ ] Compile-time headers and loaded libraries belong to the intended package family.
- [ ] Required API symbols are checked in the actual deployed shared objects.

## Model And Pipeline

- [ ] OM provenance/checksum, ATC version/command, target SoC, shapes, precision, and AIPP are recorded as needed.
- [ ] Formats, dimensions, strides, allocation APIs, memory owners, copies, and synchronization are explicit.
- [ ] Device-specific limits cite exact device/CANN documentation or installed headers and a verification date.

## Acceptance Gate

A reviewed context states what is known, how each important fact was verified, what remains unknown, which
unknowns can invalidate the current task, and what event makes the context stale. Transfer verified facts
into [context-template.md](context-template.md); do not rename a generated draft into the reviewed directory.
