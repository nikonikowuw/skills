# RTSP 与 RTP 操作

## RTSP 拉流

先把 TCP 作为诊断基线，再根据部署要求验证 UDP。输入 URL 使用占位符并引用 shell 变量，不要把真实密码提交到日志：

```bash
ffmpeg -rtsp_transport tcp -timeout 5000000 \
  -i "$STREAM_URL" -map 0:v:0 -f null -
```

`-timeout` 是否可用取决于当前 RTSP demuxer；先运行 `ffmpeg -hide_banner -h demuxer=rtsp`。如果该构建没有这个选项，使用它列出的 RTSP timeout，或在 protocol 支持时使用 `-rw_timeout 5000000`。不要假设旧版 `-stimeout` 在所有版本都存在。输入选项放在 `-i` 之前。

TCP 能减少 RTP UDP 丢包变量，但不能修复源端时间戳、编码参数集或服务器鉴权问题。UDP 场景还应检查 `min_port`/`max_port`、防火墙、NAT、接收 buffer 和 packet reorder。

## RTSP 推流与中转

从本地文件模拟直播时才需要按文件帧率读取：

```bash
ffmpeg -re -i input.mp4 -c:v copy -f rtsp \
  -rtsp_transport tcp 'rtsp://127.0.0.1:554/live/test'
```

从真实实时源中转时通常省略 `-re`：

```bash
ffmpeg -i "$SOURCE_URL" -c:v copy -f rtsp \
  -rtsp_transport tcp 'rtsp://127.0.0.1:554/live/test'
```

`-re` 的含义是按输入原生速率读取。它主要用于文件模拟直播；对已经实时到达的网络/采集输入再限速，可能增加读取延迟或使输入缓冲堆积，但是否丢包取决于 demuxer、设备和管道，不应写成绝对规律。

## 时间戳重写

多路设备合并时先确认每个输入的 time base、起始时间和主时钟。`-use_wallclock_as_timestamps 1` 是输入侧 wallclock 策略，`-fflags +genpts` 主要用于补生成缺失 PTS；两者都不能自动校准独立音频/视频时钟，也不能保证 DTS 单调。C++ 代码应在明确 clock policy 后重建或 rescale timestamp，并用 packet 级输出验证。

`Non-monotonous DTS` 的修复顺序应是：确认源 timestamp 是否回退、检查 stream/codec time base、处理 discontinuity/offset，再决定是否重编码或丢弃无法修复的 packet。不要用固定 FPS 猜测 VFR 输入。

## RTP / SDP

纯 RTP 组播/单播没有 RTSP 的 DESCRIBE/SETUP 协商时，需要 SDP 描述 payload type、clock rate、编码参数和传输地址：

```bash
ffmpeg -protocol_whitelist file,rtp,udp \
  -i stream.sdp -f null -
```

只允许实际需要的 protocol；如果 SDP 使用其他嵌套协议，按当前输入补充白名单。动态 payload type 不固定为 96，必须以发送端 SDP 和接收端配置一致为准。

H.264/H.265 的 SPS/PPS/VPS 可能来自 SDP，也可能随关键帧发送。出现 `non-existing PPS` 或 `missing picture in access unit` 时，先确认 SDP、Annex B/AVCC 格式、关键帧前的参数集和 bitstream filter 是否匹配，不要盲目重复套用 filter。
