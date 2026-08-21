---
name: linux-sys-pro
description: >
  Load when the user asks to implement, debug, or review embedded Linux media
  and video pipelines (V4L2, DRM/KMS, NPU) involving dma-buf, sync_file,
  dma-fence, cache coherency, fd lifetime, worker shutdown, or systemd watchdog.
  Do not use for desktop multimedia, frontend UI, or generic userspace C/C++
  unrelated to Linux media and kernel subsystem boundaries.
---

# Linux Embedded Media & System Pro

Guide for building, debugging, and reviewing Linux embedded media pipelines (V4L2, DRM/KMS, NPU) and systemd-supervised services.

## Always Read
- [references/dmabuf_sync_file.md](references/dmabuf_sync_file.md) (CPU cache sync & sync_file / fence explicit synchronization)
- [references/v4l2_drm_zero_copy.md](references/v4l2_drm_zero_copy.md) (Multi-planar V4L2 and DRM zero-copy buffer sharing)
- [references/thread_shutdown_patterns.md](references/thread_shutdown_patterns.md) (Cooperative worker wakeup and teardown sequence)

## Task Routing

| Task | Workflow |
|---|---|
| Zero-copy pipeline / DMABUF export & import | Check [references/v4l2_drm_zero_copy.md](references/v4l2_drm_zero_copy.md) → configure strides/offsets/modifiers |
| CPU access / Cache coherency / Fences | Follow [references/dmabuf_sync_file.md](references/dmabuf_sync_file.md) → bracket `DMA_BUF_IOCTL_SYNC` / export sync_file |
| Worker thread exit / Hang on shutdown | Follow [references/thread_shutdown_patterns.md](references/thread_shutdown_patterns.md) → use `eventfd` + teardown order |
| systemd watchdog & service health | Check §Systemd Watchdog & Recovery below → verify pipeline heartbeat |
| Code Review / Bug Investigation | Scan §Core Invariants and run §Review Checklist |

---

## Core Invariants

### 1. dma-buf CPU Access & Cache Coherency
- **Bracket CPU Access:** `mmap()` creates page mappings but does not flush/invalidate caches. Every CPU read/write cycle must be bracketed: `DMA_BUF_SYNC_START` → CPU access → `DMA_BUF_SYNC_END`.
- **Restart on Interruption:** Re-try `DMA_BUF_IOCTL_SYNC` on `-EINTR` and `-EAGAIN`.
- **Cache vs Concurrency:** The sync ioctl provides CPU cache coherency only; it does not block other threads or devices from accessing memory concurrently. Use `sync_file` or explicit locks for mutual exclusion.
- Reference: [references/dmabuf_sync_file.md](references/dmabuf_sync_file.md)

### 2. Explicit Synchronization (Sync File & DRM Fences)
- **Zero-Stall Pipelines:** Export fences from producers via `DMA_BUF_IOCTL_EXPORT_SYNC_FILE` and pass the resulting `sync_file fd` to DRM planes (`IN_FENCE_FD`).
- **Scanout Completion:** Capture `OUT_FENCE_PTR` from DRM CRTC and forward to upstream producers to release write locks.
- **FD Ownership:** Always `close()` sync_file descriptors immediately after handing them over to driver ioctls or after `poll()` returns.

### 3. fd Ownership & Safe Lifecycle
- **Ownership Transfer:** Choose one ownership model per fd: unique transfer, `dup()`/`dup3()`, or reference-counted wrapper.
- **Close Safety:** Do not retry `close()` after an error on Linux; descriptors are released even on error.
- **Close-on-Exec:** Always create and duplicate descriptors with `O_CLOEXEC` / `FD_CLOEXEC` to prevent leaking dma-buf memory across `execve()`.
- **Mapping Lifetime:** Keep dma-buf fds open as long as CPU cache sync ioctls are required, even if the memory is already mapped.

### 4. Worker Shutdown & Non-Blocking Wakeup
- **Explicit Wakeup:** Flags and condition variables do not wake threads blocked in `epoll_wait()`, `poll()`, or `VIDIOC_DQBUF`. Wake them via an `eventfd` or pipe.
- **Teardown Order:** Signal stop → wake blocking waits → `VIDIOC_STREAMOFF` / stop device queues → `pthread_join()` → `munmap()` → `close()` fds.
- **No Async Cancellation:** Never use `PTHREAD_CANCEL_ASYNCHRONOUS`.
- Reference: [references/thread_shutdown_patterns.md](references/thread_shutdown_patterns.md)

### 5. Memory Mapping (mmap & munmap)
- Check `mmap()` return value against `MAP_FAILED`, never `NULL`.
- Store the original `map_base` and allocated `map_length`. Pass the exact base and length to `munmap()`; never unmap using an offset pointer.

### 6. Systemd Watchdog & Recovery
- **Pipeline Heartbeat:** Send `sd_notify(0, "WATCHDOG=1")` only when actual frame processing progresses, not from an independent timer thread.
- **Supervision Scope:** `WatchdogSec=` supervises the user-space daemon; it cannot automatically recover locked kernel hardware without driver-level reset hooks.

---

## Known Gotchas

- **V4L2 Single vs Multi-planar mismatch:** Multi-planar (`_MPLANE`) uses array of plane descriptors with individual plane fds and `data_offset` → [references/v4l2_drm_zero_copy.md#1-single-planar-vs-multi-planar-formats](references/v4l2_drm_zero_copy.md#1-single-planar-vs-multi-planar-formats)
- **DMA_BUF_IOCTL_SYNC restart:** Kernel ioctl may return `EINTR` on POSIX signals or `EAGAIN` during lock contention → [references/dmabuf_sync_file.md#1-cpu-access--cache-coherency-dma_buf_ioctl_sync](references/dmabuf_sync_file.md#1-cpu-access--cache-coherency-dma_buf_ioctl_sync)
- **Buffer free while fd held open:** `VIDIOC_REQBUFS(0)` invalidates queue state immediately even if dma-buf fds are held alive by downstream modules → [references/v4l2_drm_zero_copy.md#2-exporter-workflow-v4l2-mmap---export-dmabuf](references/v4l2_drm_zero_copy.md#2-exporter-workflow-v4l2-mmap---export-dmabuf)
- **Hang on thread exit:** Blocked `VIDIOC_DQBUF` cannot be stopped by setting a bool flag without `STREAMOFF` or `eventfd` wake → [references/thread_shutdown_patterns.md#1-safe-wakeup-mechanisms-for-blocking-loops](references/thread_shutdown_patterns.md#1-safe-wakeup-mechanisms-for-blocking-loops)

---

## Review Checklist

- [ ] Explicit synchronization: `sync_file` / fences or implicit poll properly coordinated before buffer access.
- [ ] Every CPU access bracketed with symmetrical `DMA_BUF_SYNC_START` / `END` and `EINTR`/`EAGAIN` retry loop.
- [ ] Multi-planar strides, offsets, and DRM modifiers (`ADDFB2`) correctly configured.
- [ ] All file descriptors opened/exported with `O_CLOEXEC`.
- [ ] Shutdown sequence wakes blocked workers via `eventfd` and turns off streams before freeing buffers.
- [ ] `mmap()` validates `MAP_FAILED` and `munmap()` receives clean base and length.
- [ ] `sd_notify` watchdog ping hooked directly into frame pipeline progress.

---

## Safety Redlines

- **Never** call `munmap()` or `close(dmabuf_fd)` while hardware DMA operations or worker threads are actively accessing the buffer.
- **Never** retry `close()` on Linux after receiving an error.
- **Never** use asynchronous thread cancellation on media processing threads.

---

## Review Output Format

Report review findings in the standard format:

```text
Severity | location | failure path | evidence | minimal fix | validation
```
