# 流健康检查与回归验证

## 1. 记录环境

先记录工具和服务版本，避免把一个构建的选项套到另一个构建：

```bash
ffmpeg -hide_banner -version
ffmpeg -hide_banner -h demuxer=rtsp
ffmpeg -hide_banner -protocols
```

同时记录 ZLMediaKit 的 release/commit、实际加载的 `config.ini`、输入协议和输出协议。不要把真实密码、`secret` 或带鉴权的 URL 放进日志或工单。

## 2. Probe 输入

将 URL 放入受保护的环境变量或 secret store，并始终引用 shell 变量。以下命令只使用占位符：

```bash
STREAM_URL='rtsp://user:password@example.invalid/live/test'

ffprobe -v error \
  -select_streams v:0 \
  -show_entries stream=codec_name,profile,width,height,avg_frame_rate,time_base \
  -of default=noprint_wrappers=1 \
  "$STREAM_URL"
```

对 RTSP 添加 timeout 时，先看 `ffmpeg -h demuxer=rtsp`：

- 当前 demuxer 提供 `-timeout` 时，使用 `-rtsp_transport tcp -timeout 5000000 -i "$STREAM_URL"`。
- 只有当前构建明确提供其他 RTSP timeout 名称时才使用它。
- `-rw_timeout 5000000` 是通用协议 I/O timeout，可作为构建支持时的补充；不要盲目复制旧版本的 `-stimeout`。

这些输入选项必须位于对应的 `-i` 之前。TCP 适合先建立稳定基线；如果部署要求 UDP，再单独验证 UDP 丢包和重排序行为。

## 3. 实际解码

Probe 成功不等于能够连续解码。使用与第 2 步相同的输入 timeout，运行至少 30 秒：

```bash
ffmpeg -hide_banner -loglevel warning \
  -rtsp_transport tcp -timeout 5000000 \
  -i "$STREAM_URL" -t 30 \
  -map 0:v:0 -f null -
```

如果当前构建不支持 `-timeout`，替换为该构建在 RTSP demuxer/protocol 帮助中列出的等价选项。记录退出码以及 `RTP: missed packets`、解码 concealment、`non-monotonous DTS`、SPS/PPS 和 I/O timeout 等日志。

## 4. 时间戳与关键帧

对短窗口检查 packet 时间戳，不要仅凭播放器表现判断：

```bash
ffprobe -v error -select_streams v:0 \
  -read_intervals '%+10' -show_packets \
  -show_entries packet=pts_time,dts_time,flags \
  -of csv=p=0 "$STREAM_URL"
```

检查项：DTS 是否在 muxer 要求的 time base 下单调、是否出现无效时间戳、关键帧间隔是否符合业务目标。不要用固定帧率猜测 VFR 或跨设备时钟；需要重建时间戳时先定义每个 stream 的 clock policy。

## 5. ZLMediaKit 验证

确认实际加载的配置包含正确的 `rtc.externIP`、`rtc.port`、`rtc.tcpPort` 和必要的 TURN 端口范围。检查 UDP 与 TCP 的映射是否一致；不要把 RTC 端口和 TURN 分配端口混为一谈。

通过受保护的管理方式检查媒体是否注册，再分别验证 RTSP、HTTP-FLV/HLS 和 WebRTC 播放。API 示例中的 `secret` 只能使用占位符，并避免将真实查询 URL 写入访问日志。

## 6. C++ 回归

涉及 native 代码时，至少完成：

- 现有单元测试/集成测试和编译器警告检查。
- ASan/UBSan：覆盖 packet/frame 生命周期、失败初始化和 EOF flush。
- TSan 或等价并发检查：覆盖回调、bounded queue、取消和销毁顺序。
- 重复执行“源断开、超时、请求停止、线程 join、对象销毁”流程，确认不会挂死、use-after-free 或丢失退出信号。

## 验收标准

只有同时满足输入 probe、实际解码、时间戳/丢包检查、目标协议播放和 C++ 生命周期/停止测试，才报告流问题已修复。单次播放器成功打开只能算启动验证。最多修复三轮；仍失败时保留第一条错误和完整版本信息。
