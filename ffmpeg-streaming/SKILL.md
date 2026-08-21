---
name: ffmpeg-streaming
description: >
  Load when the user asks to develop, integrate, debug, or review C++ native code
  using FFmpeg libav* or ZLMediaKit: AVPacket/AVFrame ownership,
  send/receive and flush, RTSP/RTP/GB28181, PTS/DTS, timeout/callback,
  asynchronous media pipelines, EventPoller, or frame dispatch. Include SDK
  integration, packet loss, timestamp jumps, decoder stalls, and native leaks.
  Do not use for ffmpeg/ffprobe command-only help, browser-only WebRTC,
  Python/OpenCV or Java media code, or generic playback questions.
---

# FFmpeg SDK 与 ZLMediaKit C++ 开发

## 适用范围

本 skill 面向 FFmpeg 版本相关的 C++ native code 和 ZLMediaKit 扩展。先确认项目的 FFmpeg 版本、编译特性和 ZLMediaKit commit；不要把某个发行版的命令行选项或内部 API 当成跨版本契约。

CLI-only 的 FFmpeg 命令、浏览器端 WebRTC、Python/OpenCV 或普通播放器配置不在本 skill 范围内。

## 必读与任务路由

| 任务 | 必读文件与检查项 |
|---|---|
| **C++ 解码/编码循环** | `references/ffmpeg-api.md`、`references/cpp-gotchas.md`。分别核对 send/receive、flush、错误返回、对象所有权和 time base。 |
| **内存、停止与网络阻塞** | `references/cpp-gotchas.md`、`references/ffmpeg-api.md`。核对 `unref/free`、`interrupt_callback` 生命周期、退出条件和线程 join。 |
| **RTSP/RTP/GB28181** | `references/rtsp-rtp.md`、`references/gotchas.md`。先检查本地 FFmpeg 支持的 timeout 选项，再判断 TCP/UDP、SDP、RTP 丢包和参数集。 |
| **H.264/H.265、低延迟和硬件** | `references/h26x-codecs.md`、`references/gotchas.md`。区分编码器、解码器、硬件设备和实际构建能力，不把 profile/GOP 参数当作协议保证。 |
| **ZLMediaKit 配置与协议转换** | `references/zlmediakit.md`、`references/zlm-api.md`。核对当前 `config.ini`、RTC UDP/TCP 端口、鉴权方式和按需转协议开关。 |
| **流健康检查与回归验证** | `references/validation.md`。同时做 probe、实际解码、时间戳/丢包检查；C++ 改动再运行 sanitizer 和停止流程测试。 |
| **其他 native 流管道问题** | 先读取 `references/cpp-gotchas.md`，再按问题类型读取上述 reference；明确输入协议、FFmpeg/ZLM 版本和线程模型。 |

## 执行规则

- 先记录 `ffmpeg -version`、`ffmpeg -hide_banner -h demuxer=rtsp` 和相关 ZLMediaKit commit/config；只使用当前构建实际列出的选项。
- 明确每个 `AVPacket`、`AVFrame`、`AVFormatContext` 和回调上下文的所有权、线程归属和销毁顺序。循环复用对象用 `unref`，拥有对象的终点用对应 `free/close`。
- `EventPoller`/socket 回调中不得执行不可控的磁盘、数据库、网络或 FFmpeg 阻塞调用。跨线程传递帧时使用有界队列、明确丢帧策略和停止协议。
- 示例中的 URL、密码、ZLMediaKit `secret` 和 webhook 凭据必须使用占位符并避免写入日志、进程列表或 shell history。

## 关键 Gotchas

- 解码器和编码器的 flush API 不同：见 `references/cpp-gotchas.md#ffmpeg-eof-flush`。
- `AVPacket`/`AVFrame` 的引用释放和对象释放不是一回事：见 `references/cpp-gotchas.md#ffmpeg-memory-leak`。
- `avformat_open_input`/`av_read_frame` 的退出必须同时有协议 timeout 和可取消的 `interrupt_callback`：见 `references/cpp-gotchas.md#avformat-block`。
- 任何跨 stream 的 PTS/DTS 处理都先确认 time base 和 clock policy：见 `references/cpp-gotchas.md#pts-dts-calc`。
- ZLMediaKit 当前帧监听路径是 `getTracks()` 后对 `Track` 使用 `addDelegate()`；见 `references/zlm-api.md#zlm-track-dispatch`。
- WebRTC NAT、RTC UDP/TCP 端口和 TURN 端口池是不同配置面：见 `references/gotchas.md#webrtc-nat-blackscreen` 和 `references/zlmediakit.md#webrtc`。

## 验证循环

1. 按 `references/validation.md` 记录版本、输入协议和构建能力。
2. 运行 probe 和 30 秒实际解码检查；命令失败时先修复第一条错误，不要只改播放器参数。
3. 对 C++ 改动运行项目测试以及 ASan/UBSan；涉及跨线程队列或停止流程时再运行 TSan/压力停止测试。
4. 最多迭代三轮；仍失败时报告已验证的事实、第一条未解决错误和所需的环境信息。

## 触发评测样例

应触发：

- “C++ 用 `avcodec_send_packet` 解码 RTSP，`receive_frame` 返回 EAGAIN，帮我修循环。”
- “ZLMediaKit 的 EventPoller 回调里调用 `avformat_open_input` 后所有连接卡住了。”
- “C++ 拉 GB28181 RTP 流出现 PTS 回退、UDP 丢包和退出时线程不返回。”

不应触发：

- “给我一条 FFmpeg 命令把 MP4 转成 HLS。”
- “用 JavaScript 实现浏览器 WebRTC 播放器。”
- “Python OpenCV 读取摄像头并保存图片。”
