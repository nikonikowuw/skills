# Version Audit

## Purpose

Use this reference when the board behavior does not match the code, especially after SDK upgrades, library replacement, copying binaries from another Rockchip image, or mixing evidence from multiple board models.

## Why This Matters

Rockchip's own RGA FAQ states that released SDKs usually keep HAL and driver matched, and explicitly warns that updating `librga` separately can require a matching driver update. It also documents a compatibility mode when the driver is older than the library.

The practical consequence is simple:

- If you swap user-space libraries without auditing kernel-side versions, you can get partial success, silent fallback, or confusing `Invalid parameters` style failures.
- If you reuse one board's `librga`, RKNN runtime, MPP library, headers, or `.rknn` artifact as context for another board, you can build a pipeline that compiles but fails, falls back, or benchmarks the wrong stack.

## Minimum Audit Set

Record these before debugging performance or correctness:

- Board model from device tree
- Kernel version
- BSP or image provenance if known
- `librga` version string
- RGA driver version
- `RKNN Runtime` library version
- Whether the code uses vendor-shipped `MPP` or a separately built one

Record the full set separately for every target board or SoC. Do not create one combined "Rockchip libraries" list when the project supports multiple RK3568, RK3576, RK3588, or container targets.

## Device-Scoped Version Matrix

For multi-board projects, maintain a matrix with one row per context:

| Context ID | Board/SoC | Kernel/BSP | RGA driver | `librga.so` | `librknnrt.so` | MPP lib | Headers | RKNN artifact | Linkage |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `RK3568-EVB1-bookworm-video-infer` | RK3568 EVB1 / RK3568 | observed or unknown | observed or unknown | observed path | observed path | observed path | observed path | model path | ldd/readelf facts |

Use this matrix when handing context to another agent. The active row is the only row that should drive implementation unless the task is explicitly multi-board compatibility work.

## RGA Audit Procedure

1. Read RGA driver version from:
   - `/sys/kernel/debug/rkrga/driver_version`
   - `/proc/rkrga/driver_version`
2. Read `librga` version using:
   - `strings librga.so | grep rga_api | grep version`
3. If logs show compatibility mode, treat it as a risk even if the pipeline still runs.
4. If `imcheck()` or `IMStrError()` reports parameter issues after a library swap, suspect version mismatch before suspecting business logic.

## RKNN Audit Procedure

1. Confirm that the target board really deploys via `RKNN Runtime`, not a stale legacy package.
2. Record the toolkit version used to generate the `.rknn` file.
3. Record the board runtime version and release package source.
4. Do not infer support from historical `rknpu2` changelogs unless the installed runtime release matches.

## Historical RKNN Signals Worth Knowing

The legacy `rknpu2` release log is still useful for feature archaeology:

- `1.0` mentions more zero-copy functions and improved `rknn_inputs_set()` performance.
- `1.1.0` mentions cache flushing for fd-pointed internal tensor memory allocated by users.
- `1.2.0` mentions improved zero-copy interface implementation.
- `1.3.0` mentions `rknn_tensor_attr` support for `w_stride` and `h_stride`.
- `1.5.2` notes `RK3568/RK3588` maximum input resolution up to `8192`.

Use those items as prompts for what to verify on the board, not as guaranteed capability statements.

## MPP Audit Procedure

1. Confirm whether decode uses pure internal, half internal, or pure external buffer mode.
2. If the project claims zero-copy after decode, trace the returned `MppBuffer` fd, size, layout,
   synchronization, and lifetime. Pure external mode is required only when the application must
   supply the pool; internal allocation can still provide an importable DMA-BUF on supported stacks.
3. If memory pressure is unstable, inspect whether the decoder is still in a mode that allocates too freely.

## Escalation Rules

- If RGA library and driver versions do not look aligned, stop major optimization work and fix the stack first.
- If the runtime or BSP provenance is unknown, state that performance conclusions are provisional.
- If the code relies on a runtime feature that only appears in release logs, add an explicit environment check or feature gate.
- If multiple device contexts exist and the active context is not selected, ask which board or SoC is targeted before changing code.

## Sources

- Rockchip librga FAQ: https://github.com/airockchip/librga/blob/master/docs/Rockchip_FAQ_RGA_EN.md
- Rockchip RKNN Toolkit2 README: https://github.com/airockchip/rknn-toolkit2
- Rockchip legacy rknpu2 README and release log: https://github.com/airockchip/rknpu2
