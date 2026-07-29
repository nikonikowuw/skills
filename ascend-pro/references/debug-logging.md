# Debugging And Measurement

Use the project's existing logging, metrics, tracing, and error-propagation conventions. Do not add spdlog,
replace an established logger, or create a second telemetry format solely because this reference contains
an adapter example. Diagnostics must be controllable and cheap when disabled.

## Minimum Diagnostic Contract

Instrument only the boundaries needed for the current diagnosis:

| Boundary | Stable fields | Add timing when relevant |
|---|---|---|
| ACL/device initialization | device index, return code, selected context | initialization |
| Model load and I/O discovery | model artifact ID, tensor index/name, dtype, shape, bytes | model load |
| Allocation and binding | allocator/domain, requested bytes, pool slot | allocation outside hot path |
| DVPP/AIPP transition | format, dimensions, actual strides, descriptor size | submit and completion |
| Inference | model/buffer slot/stream, submit result | completion latency |
| Copy and synchronization | direction, bytes, reason, stream/event | copy/wait duration |
| Error path | API, numeric code, local context, source location | no |

Do not log credentials, raw frames/tensors, unredacted identifiers, entire environment values, or stable
memory addresses in normal production logs. Sample or throttle per-frame logs.

## Error Handling

Ascend APIs do not all share one return convention. Some return `aclError`; factory functions can return a
pointer; query APIs may return a value directly. Check the selected CANN headers before wrapping a call.

For a function that returns `aclError`, adapt this pattern to the project's error type:

```cpp
#define ACL_RETURN_IF_ERROR(logger, expr)                                      \
    do {                                                                       \
        const aclError acl_status_ = (expr);                                   \
        if (acl_status_ != ACL_SUCCESS) {                                      \
            const char *acl_message_ = aclGetRecentErrMsg();                   \
            (logger)->error("{} failed: code={} detail={} at {}:{}",         \
                            #expr, static_cast<int>(acl_status_),               \
                            acl_message_ ? acl_message_ : "unavailable",     \
                            __FILE__, __LINE__);                                \
            return acl_status_;                                                \
        }                                                                      \
    } while (0)
```

Use `aclGetRecentErrMsg()` only if it is declared by the selected headers. Read it immediately after the
failed call and before another Ascend call. For pointer-returning factories, check for `nullptr`, retrieve
recent detail if supported, clean up prior resources, and return the project's normal error representation.
Never use a single macro blindly in constructors, callbacks, `void` functions, or functions returning a
different error type.

## Optional Spdlog Adapter

Only use this when the project already uses spdlog or explicitly selects it. The actual upstream factory
names are `stderr_color_mt` and `stderr_color_st`; choose multithreaded or single-threaded deliberately.

```cpp
#include <cstdlib>
#include <cstring>
#include <spdlog/sinks/stdout_color_sinks.h>
#include <spdlog/spdlog.h>

auto make_ascend_logger() {
    auto logger = spdlog::stderr_color_mt("ascend");
    logger->set_pattern("[%H:%M:%S] [%^%l%$] [ASCEND] %v");
    const char *level = std::getenv("ASCEND_LOG_LEVEL");
    logger->set_level(level && std::strcmp(level, "DEBUG") == 0
                          ? spdlog::level::debug
                          : spdlog::level::info);
    return logger;
}
```

`SPDLOG_ACTIVE_LEVEL` strips only calls made through macros such as `SPDLOG_LOGGER_DEBUG`; direct calls
such as `logger->debug()` are runtime-filtered, not compiled out. Define the macro consistently in the
build before all spdlog headers, then use macro calls where compile-time stripping is required:

```cpp
SPDLOG_LOGGER_DEBUG(logger, "pool slot={} bytes={}", slot, bytes);
```

## Stage Measurement

- Use a monotonic clock.
- Distinguish enqueue time from device completion time. Async submit duration is not kernel duration.
- Use events or the least disruptive completion mechanism available in the selected CANN version. If a
  stream synchronization is required for measurement, record that the measurement includes the wait.
- Warm up before measuring and keep model, shapes, input data, queue depth, power mode, and logging level
  constant across comparisons.
- Record count, mean, p50, p95, and max; retain raw data for regression comparison.

The bundled `scripts/summarize-stage-latency.py` accepts either strict CSV
`stage,elapsed_us,frame,extra` or legacy `stage=5.2ms` lines. If the project already emits metrics or traces,
analyze those rather than introducing another file format.

## ATC Logs

Capture stdout/stderr and the exact command without losing ATC's exit status:

```bash
set -o pipefail
atc <verified-arguments> --log=debug 2>&1 | tee "atc-conversion-$(date +%Y%m%d-%H%M%S).log"
```

Archive the log with the source-model checksum, ATC version, target SoC, command, AIPP config, generated OM
checksum, and accuracy result. Check the installed `atc --help` before assuming a log flag exists.

## Verification Checklist

- [ ] Existing project diagnostics reused or the new dependency was explicitly justified.
- [ ] Each wrapped function's return convention matches the selected CANN header.
- [ ] Errors retain numeric code, API, local context, and source location.
- [ ] Logs contain no raw identifiers, frames/tensors, secrets, or unbounded per-frame output.
- [ ] Async timing measures completion, not only submission.
- [ ] Baseline and comparison use the same workload and runtime context.
- [ ] ATC failures remain visible through the pipeline exit status.
