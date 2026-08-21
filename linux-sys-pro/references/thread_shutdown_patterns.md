# Thread Cancellation and Orderly Worker Shutdown

## 1. Safe Wakeup Mechanisms for Blocking Loops

Media worker threads typically block in `epoll_wait()`, `poll()`, `select()`, or blocking `ioctl(VIDIOC_DQBUF)`. Setting a boolean stop flag alone will **never** wake a blocked thread.

### Pattern: Non-blocking I/O with `epoll` + `eventfd`

```c
#include <sys/eventfd.h>
#include <sys/epoll.h>
#include <unistd.h>
#include <stdbool.h>

struct media_worker {
    int epoll_fd;
    int wake_efd;
    int v4l2_fd;
    pthread_t thread;
    volatile bool running;
};

void* worker_thread(void *arg) {
    struct media_worker *ctx = (struct media_worker *)arg;
    struct epoll_event events[4];

    while (ctx->running) {
        int nfds = epoll_wait(ctx->epoll_fd, events, 4, -1);
        if (nfds < 0) {
            if (errno == EINTR) continue;
            break;
        }

        for (int i = 0; i < nfds; ++i) {
            if (events[i].data.fd == ctx->wake_efd) {
                /* Drain eventfd and exit loop */
                uint64_t val;
                read(ctx->wake_efd, &val, sizeof(val));
                goto cleanup;
            } else if (events[i].data.fd == ctx->v4l2_fd) {
                /* Process available V4L2 frame */
            }
        }
    }

cleanup:
    return NULL;
}

void stop_and_join_worker(struct media_worker *ctx) {
    ctx->running = false;
    uint64_t wake_val = 1;
    write(ctx->wake_efd, &wake_val, sizeof(wake_val));
    pthread_join(ctx->thread, NULL);

    close(ctx->wake_efd);
    close(ctx->epoll_fd);
}
```

---

## 2. Orderly Teardown Sequence

To prevent kernel crashes, page faults, or deadlocks in multi-threaded media apps, always adhere to this teardown order:

1. **Signal Stop & Wake Blocked Workers:** Set `running = false`, write to `eventfd` / pipe.
2. **Stop Media Hardware Streaming:** Call `VIDIOC_STREAMOFF` or cancel pending DRM page flips so drivers cease DMA operations to buffers.
3. **Join Worker Threads:** Call `pthread_join()` to ensure no thread is executing loop callbacks or touching buffers.
4. **Release Memory Mappings:** Unmap CPU addresses using recorded `map_base` and `map_length` (`munmap(map_base, map_length)`).
5. **Close File Descriptors:** Close `dmabuf_fd`, `v4l2_fd`, `drm_fd`, and `sync_file_fd`.
6. **Free Buffers:** Call `VIDIOC_REQBUFS(count=0)` or destroy dumb/GEM buffers.

---

## 3. Why `pthread_cancel()` Should Be Avoided in Media Pipelines

- Asynchronous cancellation (`PTHREAD_CANCEL_ASYNCHRONOUS`) terminates the thread at arbitrary instruction boundaries, creating severe risk of leaking mutex locks, partial DMA sync states, and memory allocations.
- Deferred cancellation (`PTHREAD_CANCEL_DEFERRED`) only acts at cancellation points (e.g. `read`, `write`, `nanosleep`), but if driver ioctls are not designated cancellation points, the thread may still block indefinitely.
- **Rule:** Always prefer explicit cooperative shutdown (`running` flag + `eventfd` wake + `pthread_join()`).
