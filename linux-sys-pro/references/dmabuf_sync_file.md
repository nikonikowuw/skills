# DMA-BUF Synchronization and Sync File Reference

## 1. CPU Access & Cache Coherency (DMA_BUF_IOCTL_SYNC)

`mmap()` sets up page table entries but does not handle CPU cache invalidation or write-back. Every CPU read/write must be bracketed by `DMA_BUF_IOCTL_SYNC`.

```c
#include <linux/dma-buf.h>
#include <sys/ioctl.h>
#include <errno.h>

int dmabuf_sync_cpu(int fd, uint64_t start_or_end, uint64_t read_or_write) {
    struct dma_buf_sync sync = {
        .flags = start_or_end | read_or_write,
    };
    int ret;
    do {
        ret = ioctl(fd, DMA_BUF_IOCTL_SYNC, &sync);
    } while (ret == -1 && (errno == EINTR || errno == EAGAIN));
    return ret;
}
```

### Critical Rules
- **Flag Symmetry:** Use identical access flags (`DMA_BUF_SYNC_READ`, `DMA_BUF_SYNC_WRITE`, or `DMA_BUF_SYNC_RW`) for `DMA_BUF_SYNC_START` and `DMA_BUF_SYNC_END`.
- **Restart Condition:** According to Linux kernel documentation, `DMA_BUF_IOCTL_SYNC` can return `-EINTR` (signal interrupt) or `-EAGAIN` (temporary resource contention). Userspace **must** restart the ioctl on these errors.
- **Cache Only:** This ioctl only flushes/invalidates caches. It does not provide inter-thread mutual exclusion or wait for pending device DMA operations.

---

## 2. Implicit Synchronization (Poll on DMA-BUF)

When drivers manage fences implicitly via `dma_resv`:
- `poll()` / `epoll()` on `dmabuf_fd` for `POLLIN` waits for write operations (shared/exclusive write fences) to complete (buffer ready to read).
- `poll()` / `epoll()` on `dmabuf_fd` for `POLLOUT` waits for all current read and write operations to complete (buffer ready to overwrite).
- Note: Polling signals device completion, not cache coherency. CPU access still requires `DMA_BUF_IOCTL_SYNC`.

---

## 3. Explicit Synchronization (Sync File & DRM Fences)

Modern pipelines (DRM Atomic KMS, Wayland, NPU drivers) pass standalone sync file file descriptors (`sync_file fd`) to coordinate cross-device execution without CPU pipeline stalls.

### Exporting / Importing Fences via DMA-BUF UAPI (Linux 5.20 / 6.0+)
`<linux/dma-buf.h>` provides ioctls to convert between `dma_fence` objects attached to dma-buf and userspace `sync_file` fds:

```c
#include <linux/dma-buf.h>

/* Export pending read or write fence from dma-buf as a sync_file fd */
int export_sync_file(int dmabuf_fd, uint32_t flags /* DMA_BUF_SYNC_READ or WRITE */) {
    struct dma_buf_export_sync_file exp = {
        .flags = flags,
        .fd = -1,
    };
    if (ioctl(dmabuf_fd, DMA_BUF_IOCTL_EXPORT_SYNC_FILE, &exp) < 0) {
        return -1;
    }
    return exp.fd; /* Caller owns this fd, must close(fd) when done */
}

/* Import a sync_file fd into dma-buf reservation object */
int import_sync_file(int dmabuf_fd, uint32_t flags /* DMA_BUF_SYNC_READ or WRITE */, int sync_file_fd) {
    struct dma_buf_import_sync_file imp = {
        .flags = flags,
        .fd = sync_file_fd,
    };
    return ioctl(dmabuf_fd, DMA_BUF_IOCTL_IMPORT_SYNC_FILE, &imp);
}
```

### DRM Atomic Commit with In/Out Fences
- **`IN_FENCE_FD` property on plane:** Pass the `sync_file_fd` from producer (e.g. V4L2 or GPU/NPU) to DRM plane. DRM will delay displaying the buffer until the fence signals.
- **`OUT_FENCE_PTR` property on CRTC:** DRM writes a `sync_file_fd` to userspace. Userspace passes this out-fence to downstream consumers or back to the producer to signal scanout completion.
- Always close sync_file fds as soon as they are handed over or after `poll()` returns.
