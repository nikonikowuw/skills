# V4L2 & DRM Zero-Copy Buffer Sharing Reference

## 1. Single-Planar vs Multi-Planar Formats

| Feature | Single-Planar (`_MPLANE` suffix absent) | Multi-Planar (`_MPLANE` suffix present) |
|---|---|---|
| Buffer Type | `V4L2_BUF_TYPE_VIDEO_CAPTURE` | `V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE` |
| Buffer Struct | `struct v4l2_buffer` | `struct v4l2_buffer` with `.m.planes` pointing to `struct v4l2_plane[]` |
| Memory Type | `V4L2_MEMORY_MMAP` or `V4L2_MEMORY_DMABUF` | `V4L2_MEMORY_MMAP` or `V4L2_MEMORY_DMABUF` |
| DMABUF FDs | One FD per buffer (via `v4l2_buffer.m.fd`) | One FD per plane (via `v4l2_plane.m.fd`) |

---

## 2. Exporter Workflow (V4L2 MMAP -> Export DMABUF)

```c
/* 1. Request buffers */
struct v4l2_requestbuffers req = {
    .count = 4,
    .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
    .memory = V4L2_MEMORY_MMAP,
};
ioctl(v4l2_fd, VIDIOC_REQBUFS, &req);

/* 2. Export dma-buf fd */
struct v4l2_exportbuffer exp = {
    .type = V4L2_BUF_TYPE_VIDEO_CAPTURE,
    .index = 0,
    .flags = O_CLOEXEC | O_RDWR,
};
ioctl(v4l2_fd, VIDIOC_EXPBUF, &exp);
int dmabuf_fd = exp.fd;
```

**Lifecycle Gotchas:**
- `VIDIOC_REQBUFS(count=0)` will attempt to free buffers. If other devices or userspace retain open `dmabuf_fd` references, the underlying memory is held alive until the last reference is dropped, but V4L2 queue state is invalidated.
- Always configure `O_CLOEXEC` on `VIDIOC_EXPBUF` to avoid leaking device memory fds across `execve()`.

---

## 3. Importer Workflow (V4L2 DMABUF)

When V4L2 acts as the consumer receiving buffers from an external allocator (e.g. DRM dumb buffer or ION/DMA-heap):

```c
struct v4l2_buffer buf = {
    .type = V4L2_BUF_TYPE_VIDEO_OUTPUT,
    .memory = V4L2_MEMORY_DMABUF,
    .index = 0,
    .m.fd = imported_dmabuf_fd,
};
ioctl(v4l2_fd, VIDIOC_QBUF, &buf);
```

---

## 4. Importing DMA-BUF into DRM / KMS (PRIME & ADDFB2)

When passing a DMA-BUF to DRM KMS for zero-copy scanout:

1. **Convert DMA-BUF FD to GEM Handle:**
   ```c
   struct drm_prime_handle prime_req = {
       .fd = dmabuf_fd,
       .flags = 0,
   };
   ioctl(drm_fd, DRM_IOCTL_PRIME_FD_TO_HANDLE, &prime_req);
   uint32_t gem_handle = prime_req.handle;
   ```

2. **Add Framebuffer with Modifiers (`DRM_IOCTL_MODE_ADDFB2`):**
   ```c
   struct drm_mode_fb_cmd2 fb_cmd = {
       .width = width,
       .height = height,
       .pixel_format = DRM_FORMAT_NV12,
       .handles = { gem_handle, gem_handle, 0, 0 },
       .pitches = { stride_y, stride_uv, 0, 0 },
       .offsets = { offset_y, offset_uv, 0, 0 },
       .modifier = { modifier, modifier, 0, 0 },
       .flags = (modifier != DRM_FORMAT_MOD_LINEAR) ? DRM_MODE_FB_MODIFIERS : 0,
   };
   ioctl(drm_fd, DRM_IOCTL_MODE_ADDFB2, &fb_cmd);
   uint32_t fb_id = fb_cmd.fb_id;
   ```

3. **Cleanup:**
   Close the GEM handle using `DRM_IOCTL_GEM_CLOSE` after creating `fb_id` (the DRM FB maintains its own reference to the GEM buffer).
