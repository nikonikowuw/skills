# Ascend-Pro Skill Evals

Use these prompts for description-isolation and route tests. The expected result is routing behavior, not a
specific technical answer. Run them on each target harness/model after changing the description or router.

## Should Trigger

| Prompt | Expected route |
|---|---|
| `Atlas 200I A2 上的 DVPP resize 偶发 100000 错误，帮我诊断 stride 和 buffer。` | DVPP/media, Evidence Gate 2 |
| `把这个 ONNX 用 CANN 8.0 的 ATC 转成 Ascend310P3 OM，并验证精度。` | ONNX to OM, Evidence Gate 1/2 |
| `Review this AscendCL async inference loop for hidden copies and synchronization.` | Zero-copy/async, evidence proportional to claims |
| `容器升级后 libascendcl.so symbol not found，排查 Atlas 部署。` | Runtime/environment diagnosis, Evidence Gate 2 |
| `优化 Ascend 910B 推理吞吐，已有各 stage latency。` | Performance regression/tuning, Evidence Gate 2 |

## Should Not Trigger

| Prompt | Expected router |
|---|---|
| `Convert this PyTorch model to generic ONNX for browser inference.` | Generic framework/ONNX tooling |
| `Optimize an RK3588 RKNN pipeline with RGA and MPP.` | Rockchip/RKNN skill |
| `TensorRT CUDA graph inference is slower after upgrading the NVIDIA driver.` | CUDA/TensorRT skill or generic diagnosis |
| `Use OpenVINO to deploy this model on Intel NPU.` | OpenVINO/Intel tooling |
| `Design a vendor-neutral NPU abstraction.` | Generic architecture unless Huawei is an explicit target |

## Edge Cases

| Prompt | Expected behavior |
|---|---|
| `What is AIPP?` | Trigger; explain without demanding a device baseline |
| `Review ascend-pro/SKILL.md.` | Trigger as explicit skill meta-work; Gate 0 |
| `Our app supports RKNN and Ascend. Fix the Ascend backend only.` | Trigger and isolate the Ascend context |
| `Atlas is a map visualization product name in this repository.` | Do not trigger based only on the word Atlas |
| `No device access yet; inspect this AscendCL cleanup code.` | Continue source-only review; label version-dependent claims |

## Mechanical Validation

Run from the skill root:

```bash
python3 -m unittest discover -s tests -v
bash -n scripts/*.sh
python3 -m py_compile scripts/*.py tests/*.py
git diff --check -- .
```

After any routing change, run at least three should-trigger, three should-not-trigger, and two edge-case
prompts through the target harness. A multi-model/harness trigger comparison remains a manual acceptance
step because this repository cannot simulate discovery routing reliably.
