---
toolkit2_version: v2.3.2
last_validated: 2026-07-26
---

# RK3588, RK3576 and RK3568 Matrix

## Scope

- **Primary Skill Scope**: `RK3588 + Linux`, `RK3576 + Linux`, `RK3568 + Linux`. The skill assumes native userspace work in C or C++, with Python limited to model conversion, environment checks, and benchmark support.
- **Recognized but limited guidance**: `RK3562`, `RV1103/RV1106`, `RV1126B`, `RK2118`
- **Out of scope**: `RK1808`, `RV1109`, `RV1126`, `RK3399Pro`

## RKLLM Note

RKNN handles Vision/Media workloads (CNNs, ViTs). If the user mentions LLM or RKLLM on RK3588/RK3576, they should refer to the separate RKLLM SDK. RKLLM is outside the scope of this RKNN-focused skill.

## Verified Platform Facts

- `RKNN-Toolkit2` states that its supported platforms include `RK3588 Series`, `RK3576 Series`, and `RK3566/RK3568 Series`.
- The older standalone `rknpu2` repository is marked as no longer maintained and points developers to `rknn-toolkit2/tree/master/rknpu2`.
- Rockchip MPP documentation in the `rockchip-linux/mpp` repository states that MPP supports `RK3588` and `RK3566/RK3568` among supported chipsets.
- The same MPP documentation describes `MppBuffer` as encapsulating buffer implementations including Linux `dma-buf`.

## Source Confidence

Use this confidence scale when reading the matrix below:

- `Primary`: Linux kernel docs or Rockchip-maintained repositories
- `Secondary`: credible third-party reporting that cites Rockchip material, but is not itself the vendor source

For `RK3576`, public primary-source material is still thinner than for RK3568 and RK3588, so some SoC-capability rows below are intentionally marked `Secondary`. RK3588 is well-documented with a large community.

## Capability Snapshot

| Area | RK3568 | RK3576 | RK3588 | RV1106 / RV1103 | Confidence |
| --- | --- | --- | --- | --- | --- |
| RKNN Toolkit2 platform support | Listed as `RK3566/RK3568 Series` | Listed as `RK3576 Series` | Listed as `RK3588 Series` | `RV1106/RV1103 Series` (rknn-toolkit2-lite) | Primary |
| Linux media path used by this skill | `V4L2 + MPP + RGA + RKNN Runtime` | `V4L2 + RGA + RKNN Runtime`, with media and BSP details to verify per board | `V4L2 + MPP + RGA3 + RKNN Runtime` | `V4L2 + RGA + RKNN Runtime` (IPC micro-stack, tight DDR/SRAM limits) | Primary |
| CPU class | Cortex-A55 generation device family | 4x Cortex-A72 + 4x Cortex-A53 | 4x Cortex-A76 + 4x Cortex-A55 | Single ARM Cortex-A7 + RISC-V MCU | Secondary |
| NPU headline | Board-specific docs still needed; 1 TOPS (INT8) | 6 TOPS headline from Rockchip material | 3-core, 6 TOPS (INT8), supports INT4/INT8/INT16/FP16 | 0.5 TOPS (INT8) | Secondary |
| Common graph precision documented by current SDK material | INT8 and FP16 paths | INT8/FP16 plus release-specific modes | INT4/INT8/INT16/FP16 capabilities vary by operation and release | INT8/FP16 plus release-specific INT16 support | Primary, but verify per operator/release |
| Target Use-Case | General Edge Vision & Gateway | Medium Edge AI Vision / IPC | High-Performance Multi-Channel Vision & AI | Ultra-Low Power IPC & Smart Camera | Secondary |
| **LLM Support (RKLLM)** | Not Supported | Not Supported | Supported via `RKLLM` C++ Runtime (Qwen/Llama) | Not Supported | Primary |


## Practical Matrix For Skill Behavior

| Topic | RK3568 default assumption | RK3576 default assumption | RK3588 default assumption |
| --- | --- | --- | --- |
| BSP maturity | Expect older and broader field usage. More legacy examples may exist, but they may still be tied to older kernels or vendor drops. | Expect less stable public guidance and more board-specific variance. Demand stronger board inspection before assuming feature parity. | Most mature among Rockchip Linux SDK, large community. Broadest deployment in modern boards. |
| Zero-copy decode path | MPP decode plus external-buffer mode is a realistic first hypothesis. Audit whether the project actually uses it. | Treat zero-copy decode feasibility as board-SDK dependent until the media stack on that board is confirmed. | High confidence. MPP decode + external-buffer mode is standard practice and well documented. |
| NPU deployment | Toolkit and runtime support are confirmed at the platform level, but runtime feature level still needs board verification. | Same rule, but be stricter about runtime feature verification because public examples are newer and thinner. | Toolkit and runtime support are highly mature. Fully utilizes multi-core NPU scheduling (`RKNN_NPU_CORE_0_1_2`, etc.). |
| RGA usage | Reasonable to expect `dma_fd`-based RGA paths on vendor SDKs. Still audit driver and `librga` match. | Same, but do not infer exact supported combinations from RK3568 experience alone. | Features RGA3 (higher throughput, supports more formats). `dma_fd`-based paths are well-tested. |
| Performance tuning bias | Expect CPU postprocess, buffer-mode choice, and hidden copies to dominate more often than raw NPU limits. | Expect board-image maturity and version mismatch risk to be a larger share of failures. | Expect NPU multi-core utilization and memory bandwidth to be key optimization targets. Ensure proper NPU core masks. |

## Recommended Software Stack Shape

Treat the stack as these layers:

- Kernel and board BSP
- Media stack: `V4L2`, `MPP`, `DRM`, vendor display stack
- Image preprocess stack: `librga`
- Inference stack: `RKNN-Toolkit2` for model conversion, `RKNN Runtime` for C or C++ deployment

Do not hard-code exact package versions into project changes unless they are confirmed from the target board. Rockchip board images and BSP drops often pin userspace libraries and drivers together.

## What To Confirm On The Board

Confirm these on every target board before making strong claims:

- Kernel version and board BSP origin
- `librga` version
- RGA driver version from `/sys/kernel/debug/rkrga/driver_version` or `/proc/rkrga/driver_version` when present
- Whether the media path uses mainline-style V4L2 nodes, vendor MPP wrappers, or both
- Installed RKNN runtime package version and headers
- Whether the repository builds against vendor SDK libraries, locally installed shared objects, or containerized toolchains

## Known Version-Sensitivity Areas

### RGA

The Rockchip RGA FAQ documents that:

- `librga` and the kernel driver have version correspondence requirements.
- If userspace is updated separately from the driver, compatibility mode or outright parameter failures may occur.
- Debug nodes may appear under `/sys/kernel/debug/rkrga` or `/proc/rkrga`, depending on kernel configuration and driver generation.

### RKNN

The Rockchip RKNN material documents that:

- `RKNN-Toolkit2` is the model-conversion tool used on the PC side.
- Runtime deployment on the board uses `RKNN Runtime` for C or C++ or `Toolkit-Lite2` for Python.
- The supported platform list includes RK3588, RK3576 and RK3568-family devices, but operator support and runtime features vary by release.
- On RK3588, you can target specific NPU cores using core masks (`RKNN_NPU_CORE_AUTO`, `RKNN_NPU_CORE_0`, `RKNN_NPU_CORE_1`, `RKNN_NPU_CORE_2`, `RKNN_NPU_CORE_0_1`, `RKNN_NPU_CORE_0_1_2`). RK3588 has 3 NPU cores, RK3576 has 2 NPU cores, and RK3568 has 1 NPU core. ALWAYS consult `rknn_api.h` for exact core mask enum values.
- Do not infer NPU graph precision from ONNX dtype or Runtime I/O dtype. `RKNN_TENSOR_FLOAT32` is a
  valid host tensor type; confirm actual graph precision from the version-matched conversion report.

Do not infer exact operator support from platform support alone. Check the runtime release notes or the board SDK when the model is nontrivial.

### Linux SDK and BSP Direction

Historically, Rockchip planned Linux 6.1 SDK or BSP releases with Debian 12 support for RK3568 and several other SoCs, with RK3576 appearing as a newer processor. Use that only as historical context, not as proof of what any given board image actually ships. The RK3588 BSP is currently the most mature and widely supported.

### MPP

The MPP documentation describes three decoder memory modes:

- Pure internal mode
- Half internal mode
- Pure external mode

It describes pure external mode as efficient for its zero-copy display workflow, but that does not
make it mandatory for every downstream accelerator: an internally allocated `MppBuffer` may expose
an importable DMA-BUF fd. Choose the mode from pool ownership and interoperability requirements.

## Practical Default Assumptions

If the recommendation depends on NPU topology, format support, allocator behavior, or performance
and the SoC cannot be inferred from project or device evidence, ask for it or state the assumption.
Do not block source-only safety work that is independent of the target SoC.

Use these defaults unless the board proves otherwise:

- `DMA-BUF` is the preferred interchange object between subsystems.
- `RGA` is the right place for crop, resize, rotate, and colorspace conversion when the next stage cannot directly consume the source layout.
- `RKNN Runtime` should be treated as the deployment boundary, not the model-authoring boundary.
- Any unexplained CPU spike in a “zero-copy” path deserves suspicion of virtual-address fallback, cache sync overhead, or forced format conversion.

## What To Do Differently Per SoC

### On RK3588

- Start by leveraging the mature BSP and community for established zero-copy patterns.
- Utilize multi-core NPU masks (`RKNN_NPU_CORE_AUTO`, `RKNN_NPU_CORE_0_1_2`) to maximize inference performance.
- Rely on RGA3 for higher throughput and broader format support during pre/post-processing.

### On RK3568

- Start by assuming the required building blocks exist and focus quickly on buffer ownership, MPP memory mode, and RGA import or alignment problems.
- Expect legacy codebases to carry older BSP assumptions. Audit versions before trusting existing examples.

### On RK3576

- Start by confirming the actual board image, kernel base, and installed Rockchip runtime packages before modeling the optimization plan.
- Treat SoC capability headlines as useful but insufficient. Require board evidence for the exact media and inference path you intend to optimize.

## Sources

- Linux kernel V4L2 DMA-BUF importer API: https://docs.kernel.org/userspace-api/media/v4l/dmabuf.html
- Linux kernel dma-buf overview: https://docs.kernel.org/driver-api/dma-buf.html
- Rockchip RKNN Toolkit2 README: https://github.com/airockchip/rknn-toolkit2
- Rockchip legacy rknpu2 README: https://github.com/airockchip/rknpu2
- Rockchip MPP readme: https://github.com/rockchip-linux/mpp/blob/develop/readme.txt
- Rockchip librga FAQ: https://github.com/airockchip/librga/blob/master/docs/Rockchip_FAQ_RGA_EN.md
- CNX Software, November 2, 2023, Rockchip roadmap and Linux 6.1 SDK coverage: https://www.cnx-software.com/2023/11/02/rockchip-roadmap-reveals-rk3576-and-rk3506-iot-processors-linux-6-1-sdk/
