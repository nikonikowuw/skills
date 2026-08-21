# H.264 / H.265（HEVC）编解码器

## H.264 软件编码

以下示例仅适用于当前 FFmpeg 构建包含 `libx264` encoder 的情况；先用 `ffmpeg -encoders` 检查。`libx264` 的 profile、preset、tune 和 GOP 是编码器参数，不是所有播放器/协议的硬性保证：

```bash
ffmpeg -i "$INPUT" -c:v libx264 -preset veryfast \
  -tune zerolatency -profile:v baseline \
  -b:v 2M -maxrate 2.5M -bufsize 4M "$OUTPUT"
```

`constrained_baseline`/`baseline` 通常更利于旧设备和部分 WebRTC 客户端；Main/High 是否可用要看浏览器、`profile-level-id`、packetization mode 和解码器。现代客户端通常支持更多 profile，不要把 High 一概判定为不兼容。

`veryfast`/`superfast` 是 CPU、码率和质量之间的取舍。`zerolatency` 只在目标编码器支持并且确实需要低延迟时使用；它通常会减少 lookahead/B 帧，但不能自动消除网络、播放器或 ZLMediaKit 缓冲。

## H.265 / HEVC

H.265 的协议和客户端支持更依赖目标链路。RTSP、HLS、HTTP-FLV、WebRTC 和 RTMP 的兼容性不能混为一谈；Enhanced RTMP、浏览器 HEVC 解码能力和 ZLMediaKit 配置都需要单独确认。转协议前先用 probe 和实际播放验证，不要只看 codec 名称。

## 硬件加速

硬件加速不是无条件优于软件，也不是“启用后自动回退”。先检查当前构建和设备：

```bash
ffmpeg -hide_banner -hwaccels
ffmpeg -hide_banner -decoders
ffmpeg -hide_banner -encoders
ffmpeg -hide_banner -buildconf
```

解码器、编码器和硬件帧格式要分别验证。以下只是常见方向，具体名称以本机输出为准：

- NVIDIA：通常使用 CUDA/NVDEC 解码和 `h264_nvenc`/`hevc_nvenc` 编码；`h264_cuvid`/`hevc_cuvid` 是否存在取决于构建。
- Intel：QSV/VAAPI 需要驱动、设备节点和正确的 hwframes 配置；`h264_qsv` 可能同时涉及解码或编码，不能只复制一个 `-c:v` 参数。
- macOS：通常用 `-hwaccel videotoolbox` 解码、`h264_videotoolbox`/`hevc_videotoolbox` 编码。
- Rockchip：`rkmpp` 一般需要厂商或平台特定 FFmpeg 构建、MPP/RGA 驱动和匹配的像素格式。

硬件路径失败时，记录失败原因并显式切换到已验证的软件路径；同时检查硬件帧是否在滤镜、下载到 CPU 或重新上传时产生额外拷贝。

## 关键帧与 GOP

GOP 目标取决于协议和业务：快速首屏、HLS 切片对齐、带宽和编码质量的要求不同。以 30 fps、约 2 秒 GOP 为例：

```bash
-g 60
```

`-keyint_min 60` 表示最小关键帧间隔，不等同于“每 60 帧必有一个 IDR”；场景切换、编码器设置和强制关键帧策略仍可能改变结果。用 `ffprobe -show_packets` 检查实际关键帧间隔，并确保 HLS segment 或 WebRTC 首帧目标与 GOP 策略一致。
