# AIPP Configuration Reference

AIPP (AI Preprocessing) moves image preprocessing into the Ascend model pipeline at inference time,
avoiding CPU-side color conversion, resize, crop, and normalization.

## How It Works

AIPP is configured at **model conversion time** via a config file passed to `--insert_op_conf`.
The preprocessing steps are fused into the OM model graph as an `AIPP` operator.

Two modes:

| Mode | Parameters Set | ATC Flags | Runtime API |
|---|---|---|---|
| **Static** | At conversion, fixed | `--insert_op_conf` with `aipp_mode: static` | None |
| **Dynamic** | At conversion (max bounds), fine-tuned at runtime | `--insert_op_conf` with `aipp_mode: dynamic` | `aclmdlSetInputAIPP()` |

## Configuration File Template

```yaml
aipp_op {
    # ===== Mode =====
    aipp_mode: static              # "static" or "dynamic"

    # ===== Input info =====
    input_format: YUV420SP_U8      # Input pixel format
    src_image_size_w: 1920         # Source image width
    src_image_size_h: 1080         # Source image height

    # ===== Crop =====
    crop: false                    # Enable crop
    crop_size_w: 224               # Crop output width
    crop_size_h: 224               # Crop output height
    crop_start_pos_w: 0            # Crop start X
    crop_start_pos_h: 0            # Crop start Y
    crop_use_mid_point: false      # true: start pos = center - size/2

    # ===== Resize (scf) =====
    scf_switch: false              # Enable resize before model
    scf_input_size_w: 224          # Input W of resize
    scf_input_size_h: 224          # Input H of resize
    scf_output_size_w: 256         # Output W of resize
    scf_output_size_h: 256         # Output H of resize

    # ===== Color Space Conversion (CSC) =====
    csc_switch: false              # Enable CSC (YUV↔RGB)
    matrix_r0c0: 256               # CSC 3×4 matrix, row 0 col 0 (Q9 format)
    matrix_r0c1: 0                 # row 0 col 1
    matrix_r0c2: 359               # row 0 col 2
    matrix_r1c0: 256               # row 1 col 0
    matrix_r1c1: -88               # row 1 col 1
    matrix_r1c2: -183              # row 1 col 2
    matrix_r2c0: 256               # row 2 col 0
    matrix_r2c1: 455               # row 2 col 1
    matrix_r2c2: 0                 # row 2 col 2
    output_bias_0: 0               # Bias for channel 0
    output_bias_1: 128             # Bias for channel 1
    output_bias_2: 128             # Bias for channel 2

    # ===== Channel Operations =====
    rbuv_swap_switch: false        # R/B or U/V channel swap
    ax_swap_switch: false          # Channel order swap (e.g., RGBA→ARGB)
    single_line_mode: false        # Single-line mode enable

    # ===== Normalization =====
    dtc_pixel_mean_chn_0: 0        # Mean value channel 0 (FP32)
    dtc_pixel_mean_chn_1: 0        # Mean value channel 1
    dtc_pixel_mean_chn_2: 0        # Mean value channel 2
    dtc_pixel_mean_chn_3: 0        # Mean value channel 3
    dtc_pixel_min_chn_0: 0         # Min value channel 0
    dtc_pixel_min_chn_1: 0         # Min value channel 1
    dtc_pixel_min_chn_2: 0         # Min value channel 2
    dtc_pixel_min_chn_3: 0         # Min value channel 3
    dtc_pixel_var_reci_chn_0: 1    # 1/variance channel 0 (FP32)
    dtc_pixel_var_reci_chn_1: 1    # 1/variance channel 1
    dtc_pixel_var_reci_chn_2: 1    # 1/variance channel 2
    dtc_pixel_var_reci_chn_3: 1    # 1/variance channel 3

    # ===== Padding =====
    padding: false                 # Enable padding
    padding_size_top: 0
    padding_size_bottom: 0
    padding_size_left: 0
    padding_size_right: 0
    padding_value: 0               # Padding pixel value (channel 0)
    padding_value_chr1: 0          # Padding pixel value (channel 1)
    padding_value_chr2: 0          # Padding pixel value (channel 2)
    padding_value_chr3: 0          # Padding pixel value (channel 3)

    # ===== Multiple input support =====
    # For multi-input models, add more aipp_op{} blocks
}
```

## Common CSC Matrix Values

### YUV→RGB (BT.601 Full Range)

```yaml
# YUV420SP → RGB (BT.601, full range)
matrix_r0c0: 256  matrix_r0c1: 0    matrix_r0c2: 359
matrix_r1c0: 256  matrix_r1c1: -88  matrix_r1c2: -183
matrix_r2c0: 256  matrix_r2c1: 455  matrix_r2c2: 0
output_bias_0: 0   output_bias_1: 128   output_bias_2: 128
```

### YUV→BGR (BT.601 Full Range)

```yaml
# YUV420SP → BGR (BT.601, full range)
matrix_r0c0: 256  matrix_r0c1: 455  matrix_r0c2: 0
matrix_r1c0: 256  matrix_r1c1: -88  matrix_r1c2: -183
matrix_r2c0: 256  matrix_r2c1: 0    matrix_r2c2: 359
output_bias_0: 128 output_bias_1: 128 output_bias_2: 0
```

## AIPP Processing Order

The hardware applies AIPP operations in this exact sequence:

```
1. Channel swap (rbuv_swap_switch)
2. Crop
3. Color space conversion (CSC)
4. Channel order swap (ax_swap_switch, after CSC)
5. Subtract mean (dtc_pixel_mean)
6. Subtract min (dtc_pixel_min)
7. Multiply by 1/variance (dtc_pixel_var_reci)
8. Padding
```

## Static AIPP Typical Usage

```bash
atc --model=model.onnx --framework=5 \
    --output=model_static_aipp.om \
    --soc_version=Ascend310P3 \
    --insert_op_conf=aipp_static.cfg
```

At runtime, no additional AIPP setup needed — preprocessing is embedded in the model.

## Dynamic AIPP Typical Usage

**Config file (`aipp_dynamic.cfg`):**
```yaml
aipp_op {
    aipp_mode: dynamic
    related_input_rank: 0
    max_src_image_size: 8294400      # max W * H
    support_out_size: true
}
```

**Conversion:**
```bash
atc --model=model.onnx --framework=5 \
    --output=model_dynamic_aipp.om \
    --soc_version=Ascend310P3 \
    --insert_op_conf=aipp_dynamic.cfg \
    --input_shape="data:1,3,224,224;AippData:1,4,66060288,1"  # AippData is auto-added
```

**Runtime (C code):**
```c
// Fill AIPP parameters
aclmdlAIPP aippParams;
aippParams.aippMode = 1;  // dynamic
aippParams.inputFormat = 4;  // YUV420SP_U8
aippParams.srcImageSizeW = 1920;
aippParams.srcImageSizeH = 1080;
aippParams.cropSwitch = 1;
aippParams.cropStartPosW = 0;
aippParams.cropStartPosH = 0;
aippParams.cropSizeW = 224;
aippParams.cropSizeH = 224;
// ... other params

aclmdlSetInputAIPP(modelId, inputDataset, 0, &aippParams);
```

## Key Constraints & Notes

- **Static AIPP**: `input_format` is **mandatory**; all other fields optional with defaults
- **Static AIPP** with `dynamic_batch_size`: `batchSize` in runtime AIPP API must equal max batch
- **Dynamic AIPP** with `dynamic_image_size`: `Crop`/`Padding` features disabled at runtime
- **Dynamic AIPP** with `input_shape`: AIPP output W/H must be within shape range
- AIPP cannot do **advanced** preprocessing (e.g., letterboxing with arbitrary background color,
  complex augmentations) — those belong on CPU
- AIPP works on **per-input** basis; multi-input models need multiple `aipp_op` blocks
- When both AIPP and CPU preprocessing exist, the CPU work is likely redundant — confirm and remove

## Comparison: AIPP vs CPU vs DVPP

| Aspect | CPU Preprocess | DVPP Preprocess | AIPP |
|---|---|---|---|
| Hardware | CPU cores | DVPP hardware (dedicated) | Inside model pipeline (NPU) |
| Operations | Anything (OpenCV) | Resize, crop, CSC, JPEG | Resize, crop, CSC, mean/var, padding |
| Copy cost | H2D after preproc | Device-resident handoff | Zero-copy (inside model) |
| Configuration | Code | Code | Conversion-time config / runtime params |
| Flexibility | Highest | Medium | Limited to config options |
| When to use | Complex augmentation | Heavy resize/decode | Standard normalization + CSC + crop |
