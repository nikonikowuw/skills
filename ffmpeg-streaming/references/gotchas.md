# 流媒体常见坑点

## WebRTC 跨局域网拉流失败 (`#webrtc-nat-blackscreen`)

局域网正常、跨 NAT 黑屏或连接失败时，先检查 SDP/ICE 中客户端可见的地址，而不是只改播放器：

- ZLMediaKit 的 `rtc.externIP` 应填写客户端可达的公网地址；多出口场景按当前版本配置多个地址或指定 `interfaces`。
- NAT 映射必须同时考虑 `rtc.port`（UDP）和 `rtc.tcpPort`（TCP fallback），外部映射端口应与服务端配置一致。
- 如果启用 TURN，再检查 `icePort`/`iceTcpPort` 和独立的 TURN 分配端口池；不要把 TURN 端口池当成 RTC RTP 端口。
- 同时检查云安全组、主机防火墙、路由器映射和浏览器收集到的 ICE candidate。

## 时间戳跳变与播放卡顿 (`#timestamp-jumps`)

`rtp stamp abnormal reduced` 或画面倒退通常说明源 timestamp 回退、跨设备时钟漂移、RTP discontinuity 或 ZLMediaKit 的 timestamp policy 不匹配。先保存原始 packet/日志并确认 stream time base，再选择保留源时间戳、使用 ZLM 的平滑/相对 timestamp 模式，或在 FFmpeg 中重新建立时钟。

`-use_wallclock_as_timestamps 1`、`-fflags +genpts` 和 `-re` 都不是通用修复：前两者不能自动同步独立设备，`-re` 只适合文件模拟直播。修复后必须检查 PTS/DTS，而不是只看播放器暂时恢复。

## GB28181/RTP 丢包与解析失败 (`#gb28181-rtp-loss`)

除网络物理丢包外，还要检查内核 UDP 接收 buffer、ZLMediaKit 的 RTP 接收配置、MTU、CPU 调度和上游 I 帧 burst。可以在测试机临时调整 `net.core.rmem_max`/`net.core.rmem_default`，但这是主机级变更，需评估权限、上限和持久化配置；不要盲目写入生产系统。

ZLMediaKit 当前配置还包含 RTP proxy 的 UDP 接收 buffer 选项。先用丢包计数和抓包确认瓶颈，再调整单 socket buffer、协议端口范围或网络路径。

## 延迟与 B 帧 (`#latency-and-b-frames`)

B 帧、编码 lookahead、RTP reorder、服务器 ring buffer、协议缓存和播放器缓冲都可能增加延迟。编码器支持时可以测试 `-bf 0` 与低延迟 tune，但这会影响压缩效率，且只改变编码侧。

`ffplay -fflags nobuffer -flags low_delay -framedrop` 可能降低缓冲但会增加丢帧和花屏风险；它不能替代对 GOP、网络、ZLMediaKit 和播放器缓存的测量。

## UDP 花屏与伪影 (`#udp-smearing`)

RTP UDP 丢包可能损坏一个 slice、关键帧或后续参考帧。RTSP 切换 TCP 可作为诊断和可靠性基线，但 TCP 的队头阻塞会把丢包转化为延迟；它也不能修复损坏的源码流。比较 TCP/UDP 时同时记录 packet loss、延迟、jitter 和恢复时间。

## 缺失 SPS/PPS/VPS (`#sps-pps-missing`)

`non-existing PPS`、`missing picture in access unit` 等错误可能来自：SDP 缺少 `sprop-parameter-sets`、关键帧前没有参数集、AVCC 与 Annex B 格式不匹配，或中途加入流时没有等到配置帧。

确认封装和目标 muxer 后再使用 `h264_mp4toannexb`/`hevc_mp4toannexb`。这些 bitstream filter 主要处理 MP4 length-prefixed 到 Annex B 的转换；已经是 Annex B 的裸流不要盲目重复应用。优先让编码器周期性发送 SPS/PPS/VPS，并验证首个可解码 IDR。

## FFmpeg 拉流长时间阻塞 (`#ffmpeg-read-block`)

`avformat_open_input`、`avformat_find_stream_info` 或 `av_read_frame` 可能等待网络。命令行根据当前构建选择 RTSP `-timeout` 或通用 `-rw_timeout`；C++ 同时设置 `AVIOInterruptCB`，让 stop flag/deadline 能取消打开、读取和 seek。回调状态的生命周期必须覆盖 FFmpeg 可能访问它的整个阶段。

## `-re` 参数使用 (`#ffmpeg-re-misuse`)

`-re` 等价于按输入原生速率读取，主要用于读取静态文件模拟实时推流。对已经实时到达的 RTSP、摄像头或采集设备通常省略，避免额外限速和延迟；具体是否溢出、丢包要结合 demuxer 和设备实测，不要使用“绝对不要”的结论。

## 音视频不同步与合并推流 (`#av-sync-timestamp`)

独立音频/视频设备通常有不同的时钟。`-use_wallclock_as_timestamps` 只能改变输入侧 timestamp 来源；`-fflags +genpts` 只能补部分缺失 PTS；`-fps_mode cfr` 只控制视频帧率模式，不能单独同步音频。

先选择主时钟和初始 offset，再决定是否对音频重采样、对视频重定时、丢弃过期帧或重编码。旧版 `-async`/`-vsync` 参数要按 FFmpeg 版本确认，不能作为无条件处方。C++ 管道要在 packet 级别检查 time base、PTS/DTS 和 drift。

## CPU 使用率过高 (`#cpu-exhaustion`)

CPU 100% 可能来自解码、编码、像素格式转换、滤镜、拷贝、队列堆积或日志，不一定只能靠硬件加速解决。先用 `ffmpeg -hwaccels`、`-decoders`、`-encoders` 确认可用路径，测量每个阶段，再选择软件 preset、硬件 codec、零拷贝或降低分辨率/码率。硬件路径失败时保留经过验证的软件 fallback，详见 `references/h26x-codecs.md`。
