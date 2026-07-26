# Rockchip Project Crash-Risk Audit

Use this procedure when the user asks for a comprehensive review of code that could crash an
algorithm process, a long-running system service, or the Linux kernel on a Rockchip RKNN target.

The audit covers RKNN, RGA, MPP, DMA-BUF, allocators, model postprocessing, C/C++ memory safety,
resource exhaustion, concurrency, error cleanup, and build/runtime compatibility. It is broader
than a zero-copy or performance review.

## Contents

- [Meaning of Comprehensive](#meaning-of-comprehensive)
- [Evidence Hierarchy](#evidence-hierarchy)
- [Severity and Confidence](#severity-and-confidence)
- [Audit Workflow](#audit-workflow)
- [Risk Domains](#risk-domains)
- [Static and Build Analysis](#static-and-build-analysis)
- [Board Validation](#board-validation)
- [Completion Gate](#completion-gate)
- [Report Format](#report-format)

## Meaning of Comprehensive

A comprehensive audit is a coverage claim, not a promise that static analysis can prove the
absence of every defect. Before reporting results, state:

- production source roots inspected;
- languages and build systems covered;
- target SoCs, BSPs, sysroots, algorithm packages, and build variants covered;
- generated, vendored, test, example, and build directories excluded;
- static analyzers, compilers, tests, and board evidence actually used;
- components that could not be built or exercised;
- residual risks that require target-board or vendor-driver evidence.

Do not say "no memory-safety problems" when only grep-like candidate scanning was performed. Say
"no confirmed defect in the inspected paths" and list the remaining coverage gaps.

## Evidence Hierarchy

Use evidence in this order:

1. The exact headers, libraries, kernel, driver, allocator, and `.rknn` artifact deployed on the
   selected board.
2. Rockchip official headers, manuals, FAQ documents, samples, changelogs, and maintained source.
3. Linux kernel documentation for DMA-BUF, dma-fence, V4L2, DRM, and allocator behavior.
4. Rockchip official GitHub issue trackers and maintainer replies for matching versions.
5. Community reports as reproduction clues only. Do not turn an unconfirmed issue author's theory
   into an API requirement.

When the exact log text is available, search it verbatim and record the matching software versions.
Read [known-crash-patterns.md](known-crash-patterns.md) before assigning Rockchip-specific severity.

## Severity and Confidence

Record severity and confidence separately.

| Severity | Meaning |
|---|---|
| **S0 Critical** | Credible path to kernel panic, reboot, cross-process corruption, or persistent service outage through a driver-facing buffer/allocator defect. |
| **S1 High** | Credible process crash, heap/stack corruption, use-after-free, double free, uncontrolled OOM, or repeatable hardware-service failure. |
| **S2 Medium** | Latent bounds, cleanup, synchronization, ABI, or exhaustion defect requiring a rare error, reconfigure, concurrency, or long-run condition. |
| **S3 Low** | Defensive validation, observability, or maintainability gap that makes a future failure harder to contain or diagnose. |

| Confidence | Required evidence |
|---|---|
| **Confirmed** | Source-level path plus proof: calculation, build diagnostic, sanitizer, test, core dump, or matching board log. |
| **Probable** | Complete source path and violated documented invariant, but not reproduced on the selected board. |
| **Candidate** | Automated match or suspicious local pattern that still needs call-path and data-flow review. |
| **Environment-dependent** | Depends on allocator, address range, driver, BSP, cacheability, or hardware core not yet verified. |

Automated scanner results begin as **Candidate**. Promote them only after manual tracing.

## Audit Workflow

### Phase 0: Freeze Scope

1. Identify all production source roots and binaries/shared objects delivered to the board.
2. Enumerate every Rockchip algorithm package, not only the package named in the bug report.
3. Build a target matrix: SoC, sysroot, RKNN header/runtime, librga/driver, MPP, allocator, model.
4. Record excluded directories. Exclude build trees and third-party source from application findings,
   but audit the selected vendor header/library versions as environment inputs.
5. If `.codegraph/` exists, use CodeGraph first. Scope queries to production paths and exact symbols;
   broad names such as `resize`, `set`, or `reset` are too noisy.

Source-only work may start without board access. Do not make board-specific compatibility or kernel
crash claims until the device context is selected and verified.

### Phase 1: Generate Complete Inventories

Run the bundled scanner from the project root:

```bash
python3 /path/to/rknn-pro/scripts/audit-rockchip-memory-safety.py . \
  --output rockchip-crash-risk-candidates.md
```

The scanner inventories sensitive APIs and produces review candidates. Preserve its coverage
summary in the final report. Re-run with `--include-third-party` only when the project owns or
modifies vendor code. Re-run with `--include-tests-examples` as a separate pass when test harnesses,
samples, conversion tools, or diagnostic binaries are shipped or privileged.

Also inventory:

- all algorithm-specific `CMakeLists.txt` and toolchain files;
- every `rknn_init/query/create_mem/create_mem_from_fd/set_io_mem/run/destroy` call;
- every RGA import/wrap/operation/release call;
- every MPP group/buffer/frame/packet create, reference, info-change, and release call;
- every `malloc/calloc/realloc/new/mmap/memcpy/memmove/read/fread` and unchecked C string call;
- all worker queues, detached threads, async callbacks, reload/reset/shutdown paths;
- every model output parser, ROI calculation, detection-count loop, and tensor index computation.

### Phase 2: Trace Allocation Contracts End to End

For every buffer crossing RKNN, RGA, MPP, V4L2, DRM, or CPU code, create one ledger row:

| Field | Required evidence |
|---|---|
| Owner and allocator | RKNN, MPP, dma-heap, DRM, V4L2, malloc, application pool |
| Address form | DMA-BUF fd, virtual address, physical address, handle |
| Logical geometry | width, height, planes, tensor dimensions |
| Physical layout | format, bytes/sample, w_stride, h_stride, plane offsets |
| Minimum bytes | checked formula using the physical layout |
| Allocated/imported bytes | authoritative allocator or fd size |
| Cacheability/sync | who writes, who reads, required begin/end or mem sync |
| Lifetime | create/import/map/ref and matching destroy/release/unmap/put |
| In-flight protection | fence, blocking API, reference, mutex, shutdown join |

Trace the value origin for every dimension and size. Model metadata, camera metadata, decoded frame
info, user configuration, ROI coordinates, and network input are untrusted until range-checked.

The same layout must be used for size calculation, allocation/import, RGA wrapping, RKNN binding,
CPU indexing, and cleanup. A large allocation does not fix a wrong stride or plane offset.

### Phase 3: Review Normal and Failure Paths

For each sensitive API call, verify:

1. all inputs are validated before the call;
2. size arithmetic cannot wrap before conversion to `size_t`;
3. the return value and returned pointer/fd/handle are checked;
4. partial initialization unwinds only resources actually acquired;
5. the cleanup order is the reverse of acquisition;
6. repeated cleanup is idempotent or state is nulled/invalidated;
7. no resource is destroyed while hardware, callbacks, or worker threads may still use it;
8. retry paths do not reuse poisoned state or double-import the same fd;
9. reload, dynamic shape, resolution change, and decoder info-change rebuild dependent buffers;
10. fatal vendor errors are contained and surfaced instead of continuing with invalid memory.

Audit constructors, destructors, `Reset`, `Stop`, error labels, early returns, exceptions, signal
handling, plugin unload, model replacement, stream reconnect, and service shutdown.

### Phase 4: Trace Cross-File Call Paths

Use CodeGraph or exact symbol searches to connect:

`external dimensions -> size calculation -> allocation/import -> RGA wrap/operation -> RKNN bind/run -> CPU postprocess -> release/reload`

Repeat for every duplicated package. Similar filenames do not prove identical behavior. Maintain a
matrix showing which packages share helpers and which contain forked copies.

### Phase 5: Build and Analyze

Read [Static and Build Analysis](#static-and-build-analysis). Run every available low-risk check,
then inspect diagnostics rather than reporting command success alone.

### Phase 6: Controlled Runtime Validation

Exercise CPU-only code with sanitizers where possible. Run board tests only after static high-risk
findings are fixed or contained. See [Board Validation](#board-validation).

### Phase 7: Correlate Logs and Reassess

Use exact error signatures from `dmesg`, journald, pstore, core dumps, RKNN logs, RGA logs, and MPP
logs. A driver error may be a consequence of a userspace size/lifetime defect, an environment
mismatch, or a vendor defect. Keep those hypotheses separate until evidence distinguishes them.

## Risk Domains

### 1. Integer and Size Arithmetic

Check every multiplication, addition, alignment, cast, and plane offset used for allocation or
copying:

- promote operands to `size_t` before multiplication;
- use checked multiply/add/align helpers;
- reject zero, negative, implausibly large, and unsupported dimensions;
- check fractional formats without floating point (`pixels * 3 / 2` after overflow checks);
- ensure `offset + length <= allocated_size` without wrapping;
- avoid storing byte counts in signed `int` or 32-bit fields unless the API requires it and the
  range was checked first;
- validate `n_dims`, each dimension, `n_elems`, detection counts, class counts, and output offsets.

Treat `ALIGN_UP(value, align)` implemented as `value + align - 1` as overflow-prone unless guarded.

### 2. Layout, Format, Stride, and Plane Bounds

Verify logical dimensions separately from physical strides. Check:

- `w_stride >= x_offset + width` and `h_stride >= y_offset + height`;
- format-specific width/height/offset alignment;
- bytes per pixel or per plane for the actual wrapped format;
- NV12/NV21/YUV plane sizes and even geometry;
- FBC/AFBC mode only for matching data;
- allocation/import size covers padded rows and all planes;
- RKNN `size_with_stride`, RGA target stride, and `rknn_set_io_mem` agree;
- source and destination may have different strides and allocation formulas.

### 3. RKNN Memory and Tensor Safety

- Feature-detect header fields and APIs against the exact target header.
- Allocate at least the maximum supported tensor-size fields; for RGA-written inputs also cover the
  format/stride-derived byte count and allocator alignment.
- Check `rknn_create_mem*` pointers and every RKNN return code.
- Do not bind memory smaller than the selected tensor layout.
- Reallocate after dynamic shape or model changes; do not reuse old output parsing assumptions.
- Pair every created/imported tensor memory with `rknn_destroy_mem` before destroying its context,
  after all runs and users have stopped.
- Audit duplicated/shared contexts and model reload for concurrent use-after-destroy.
- Respect cache flags. If automatic input flush/output invalidate is disabled, use the matching
  `rknn_mem_sync` direction before device or CPU access.
- Validate output index calculations against the actual queried output shape and byte size.

### 4. RGA Driver-Facing Safety

- Prefer fd/handle paths whose actual size can be verified; validate fd lifetime and ownership.
- Pass explicit source and destination strides.
- Run `imcheck` with the real rectangles before submitting work.
- Verify import size matches the later wrapped format and strides.
- Pair every `importbuffer_*` with exactly one `releasebuffer_handle` after work completes.
- Do not free/unmap/close backing memory while an asynchronous RGA task can access it.
- Treat virtual-address paths as higher risk: verify mapping length, allocator compatibility,
  page-table availability, cache sync, and lifetime.
- Verify RGA core addressability, including DMA32/below-4G requirements where applicable.
- Treat `Bad address`, map/PTE/MMU failures, buffer-size mismatch, IRQ errors, and timeouts as memory
  or lifetime incidents until disproved.

Do not enable the RGA driver's destructive `check` mode on a production board. Rockchip's FAQ says
the mode checks memory/alignment and that an over-threshold access can crash the kernel.

### 5. MPP Buffer and Reconfiguration Safety

- Handle decoder info-change before continuing; allocate from returned strides and signal
  `MPP_DEC_SET_INFO_CHANGE_READY` only after the new group is ready.
- Use the documented decode allocation formula and required buffer count for the selected codec.
- Pair buffer refs/gets/imports, frames, packets, and groups with the correct put/deinit operation.
- Do not close the decoder while frames remain held by downstream consumers.
- Limit group size/count and all application queues to prevent service-wide OOM.
- Use cache sync helpers around CPU access to cacheable MPP buffers.
- Verify external `MppBufferInfo.size`, fd, pointer, flags, DMA32, contiguity, and kmap requirements.

### 6. DMA-BUF, fd, Mapping, and Synchronization Safety

- Set `O_CLOEXEC` atomically where allocation APIs support it; fd leaks across exec are both a
  resource and security issue.
- Discover/verify DMA-BUF size when the exporter permits it; never trust only a caller-supplied size.
- Define fd ownership: borrowed, duplicated, or transferred. Close only the owning reference.
- Pair `mmap/munmap`, begin/end CPU access, cache sync, imports, and fence lifetimes.
- Wait for producer completion before a consumer reads/writes; wait for consumers before reuse or
  destruction.
- Audit error and timeout paths for double-close, stale fd reuse, and reuse while in flight.

### 7. Generic C/C++ Memory Safety

Review all raw copies, C strings, pointer arithmetic, array indexing, casts, and manual ownership:

- destination capacity for every `memcpy/memmove/read/fread`;
- destination capacity for every `memset` and fill operation;
- source capacity and overlap assumptions;
- `strcpy/strcat/sprintf/scanf` family usage;
- vector/data pointer invalidation after resize or reallocation;
- signed/unsigned comparisons and negative values converted to large `size_t`;
- stack allocation from runtime dimensions;
- exception and `goto` cleanup consistency;
- RAII coverage for fd, mmap, RKNN memory, RGA handles, MPP objects, threads, and locks.

### 8. Concurrency, Shutdown, and Resource Exhaustion

- Bound frame, result, event, and retry queues.
- Join workers before releasing contexts, models, buffers, callbacks, and plugin code.
- Do not detach threads that capture object pointers or vendor handles without a lifetime owner.
- Serialize non-thread-safe context access or prove the runtime version supports the pattern.
- Audit cancellation during RGA/RKNN/MPP work and partial service startup.
- Stress repeated create/start/stop/reload/reconnect; monitor fd count, RSS, DMA heaps, MPP usage,
  RGA handles, and NPU memory.

### 9. Build, ABI, and Deployment Mismatch

- Prove compile headers and linked runtime libraries belong to the selected BSP/runtime family.
- Reject silent fallback to host headers or a different sysroot.
- Feature-detect optional fields/APIs; clear CMake cache when switching sysroots.
- Compare model toolkit version, runtime API version, driver/firmware, target platform, and SoC.
- Audit `dlopen/dlsym` signatures and absent-symbol fallbacks.
- Treat `RKNN_ERR_DEVICE_UNMATCH`, incompatible model errors, RGA compatibility mode, and unexplained
  `failed to submit` errors as environment incidents until versions are proven compatible.

## Static and Build Analysis

Use the project's existing toolchain first. Useful checks include:

```bash
# Inventory/candidate scan
python3 /path/to/rknn-pro/scripts/audit-rockchip-memory-safety.py . \
  --output rockchip-crash-risk-candidates.md

# Existing build with stronger diagnostics where supported
cmake -S . -B build-audit -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
cmake --build build-audit --parallel

# Apply only flags accepted by the selected compiler/toolchain
-Wall -Wextra -Wpedantic -Wconversion -Wsign-conversion
-Warray-bounds -Wstringop-overflow -Wformat=2 -Werror=return-type
```

When available, run `clang-tidy`, `cppcheck`, GCC `-fanalyzer`, and the project's tests. Use
AddressSanitizer and UndefinedBehaviorSanitizer for CPU-side code and mockable wrappers. Vendor
device libraries or cross-built board binaries may not support sanitizers; document that gap.

Compile every algorithm package and SoC variant that can select a different header, macro, source
copy, pixel format, or allocator. One successful package does not validate its siblings.

Run the scanner's default production pass first, then run a separate
`--include-tests-examples` pass when diagnostic tools, converters, benchmarks, test binaries, or
examples are deployed to a board, run as root, or exercise the same driver-facing code.

For macro-heavy C/C++, add `--preprocess` and every project include root with repeated
`--preprocess-include DIR`. The scanner filters included-header bodies and maps expanded calls back
to the owning source line. Review the reported preprocessing success/fallback counts; a raw-source
fallback can miss sensitive APIs hidden entirely behind macros.

## Board Validation

Start with the read-only collector:

```bash
bash /path/to/rknn-pro/scripts/collect-rockchip-crash-evidence.sh [service-pid]
```

Before stress testing, ensure remote recovery, serial console or equivalent logs, a watchdog policy,
and a way to restore the service. Use a non-production board or maintenance window.

Test at least:

- minimum, nominal, maximum, odd, padded, and rejected dimensions;
- every supported pixel format and conversion path;
- dynamic resolution/info-change and model reload;
- repeated start/stop/reconnect and injected allocation/API failures;
- concurrent streams and shutdown while work is queued;
- long-run fd/RSS/DMA/RGA/MPP/NPU memory stability;
- invalid ROI/count/metadata inputs at application boundaries.

Monitor `dmesg`, journald, pstore, service core dumps, fd count, RSS, DMA heaps, RGA debug status,
MPP usage, and RKNN error codes. Do not use debugfs/procfs writes, fault injection, overclocking,
or a test likely to panic the kernel without explicit user approval and recovery controls.

## Completion Gate

Do not close a comprehensive audit until all applicable items are complete:

- [ ] Coverage table lists source roots, packages, targets, languages, exclusions, and tools.
- [ ] Sensitive API inventory is complete and each high-risk site is manually classified.
- [ ] Buffer ledger covers every hardware boundary.
- [ ] Size/layout formulas use checked arithmetic and authoritative strides/formats.
- [ ] Return values, partial initialization, cleanup, and repeated cleanup are reviewed.
- [ ] Allocation/import/release/ref/fd/mmap pairings are reviewed across files and callbacks.
- [ ] Dynamic shape, info-change, reload, reconnect, shutdown, and concurrency are reviewed.
- [ ] Build/header/library/driver/model compatibility is evidenced for each selected target.
- [ ] Static diagnostics and available tests were run, or their absence is reported.
- [ ] Board validation was run safely, or board-dependent risks remain explicitly unverified.
- [ ] Each S0/S1 issue has a concrete fix and regression test or containment plan.

## Report Format

Lead with findings, ordered by severity. For every finding include:

```text
ID / Severity / Confidence
Location and affected targets/packages
Failure path
 violated invariant and authoritative source
Impact: process crash, kernel crash, corruption, leak, OOM, hang, or wrong result
Evidence
Fix
Regression verification
Residual board/version assumptions
```

Then include:

1. Coverage and exclusions
2. Buffer ownership/layout ledger
3. Resource pairing summary
4. Build/static/runtime validation performed
5. Known environment mismatches
6. Unverified risks and next evidence required

If no confirmed issue is found, say so clearly, but retain candidate counts, coverage gaps, and
residual risk. Absence of a reproduced crash is not proof that driver-facing memory is correct.
