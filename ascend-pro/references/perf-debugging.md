# Performance Debugging

## Principle

Do not ask "why is the NPU slow" until you have broken the pipeline into stages. On Ascend deployments, end-to-end regressions are often outside the model execution call itself.

## Stage Breakdown

Time these separately:

- Capture, decode, image load, or request parsing.
- CPU preprocess.
- DVPP preprocess.
- AIPP or model input staging.
- Host-to-device copies.
- Model execution.
- Device-to-host output copies.
- Postprocess.
- Display, encode, database write, or response serialization.
- Queue wait and stream synchronization time.

If stage timing is unavailable, add it before changing architecture.

## Symptom To Hypothesis Map

### High CPU, moderate throughput, low NPU utilization

Suspect:

- CPU image conversion or resize.
- Full-frame host-to-device copies.
- CPU-heavy postprocess.
- Per-frame device allocation and free.
- Descriptor or channel setup churn.
- Logging or debug image dumps in the hot path.

### Low frame rate, low CPU, low NPU utilization, high wait time

Suspect:

- Blocking queue or stream synchronization.
- Too few buffers in the pipeline.
- Producer and consumer cadence mismatch.
- Synchronous model execution where safe pipelining is possible.
- Output retrieval or postprocess backpressure.

### Good model execution time, poor end-to-end latency

Suspect:

- Preprocess copy chain.
- Format conversion costs.
- Host/device transfer before and after inference.
- Postprocess on CPU.
- Serialization between stages that should overlap.

### DVPP failures or intermittent slowness

Suspect:

- Unsupported device or CANN feature combination.
- Format, stride, alignment, or dimension mistakes.
- Wrong memory type.
- Channel or descriptor lifecycle overhead.
- Version mismatch between headers, runtime, and driver.

### Model loads but results or performance are wrong

Suspect:

- OM artifact generated with wrong target device, shape, precision, or AIPP config.
- Preprocessing differs from training or validation.
- Dynamic shape mismatch.
- Multiple model artifacts and the wrong file is deployed.
- Runtime package differs from conversion environment.

## Device Inspection Checklist

- Check `npu-smi info` and utilization.
- Check thermal, power, and clock-related output when available.
- Check process CPU usage per major thread.
- Check memory usage and allocation churn.
- Check dmesg for driver reset, permission, or memory errors.
- Check whether benchmark and product workloads use the same input resolution, batch, and preprocessing.

## Minimal Measurement Standard

For each experiment, record:

- Device model and NPU count.
- Driver, firmware, and CANN versions.
- Input resolution, format, shape, batch, and model artifact name.
- Per-stage average and percentile latency.
- CPU usage per major thread if possible.
- NPU utilization if available.
- Whether measurements include warmup.

## Fast Triage Order

1. Validate versions with [version-audit.md](version-audit.md).
2. Check whether the alleged device-resident path still maps or copies full buffers on CPU.
3. Check allocation and descriptor churn in hot loops.
4. Check stream synchronization and queue depth.
5. Check whether postprocess, not model execution, owns the wall time.
6. Check whether conversion or AIPP assumptions differ from runtime input.
