# ZLMediaKit 集成指南

## 概述

ZLMediaKit 是 C++ 流媒体服务器，支持 RTSP、RTMP、HLS、HTTP-FLV、WebRTC、SRT 等协议。实际协议转换和端口以当前加载的 `config.ini`、版本和编译功能为准。

## App、Stream 与协议转换

媒体 URL 通常包含 `app` 和 `stream`：

```text
rtsp://127.0.0.1/live/test
```

这里 `app=live`、`stream=test`。推入一个协议后，ZLMediaKit 是否生成 RTMP、HLS、HTTP-FLV、WebRTC 等输出，取决于 `protocol.enable_*`、按需生成开关、track 类型和客户端/协议兼容性；不能笼统承诺“所有协议自动可用”。

当前 sample config 的协议端口通常包括：

- RTSP `554`
- RTMP `1935`
- HTTP `80`，HTTPS `443`
- RTC UDP `rtc.port=8000`
- RTC TCP fallback `rtc.tcpPort=8000`

部署必须以实际配置为准，并确认端口没有被其他进程占用。RTSP server 的随机 RTP 端口范围和 RTC 端口不是同一个概念。

## 鉴权与 REST API

- REST API 的 `secret` 位于 `[api]`，不是一个无条件存在的全局配置。敏感 API 访问应使用受保护的凭据管理方式。
- `[hook]` 的 `on_play`、`on_publish`、`on_rtsp_auth` 等是不同鉴权入口；是否启用由 `[hook] enable` 和对应 URL 决定。
- 常见 API 包括 `/index/api/getMediaList` 和 `/index/api/close_stream`，但应按当前版本 API 文档确认参数和权限。
- 不要把真实 `secret`、用户名或密码写进源码、shell history、进程参数、截图或普通访问日志。示例只使用 `REDACTED`。

## WebRTC (`#webrtc`)

跨 NAT 部署至少核对：

- `rtc.externIP`：填客户端可达的公网地址；多出口或弹性公网 IP 场景同时核对 `rtc.interfaces`。
- `rtc.port` 和 `rtc.tcpPort`：分别是 RTC UDP 和 TCP fallback 监听端口。服务位于 NAT 后时，外部映射端口应与服务端配置一致。
- `rtc.icePort`/`iceTcpPort` 以及 `enableTurn`：这是 STUN/TURN 服务面；启用 TURN 时，`rtc.port_range` 是独立的 TURN 分配端口池。
- 浏览器实际收集到的 ICE candidate、云安全组、主机防火墙和路由器端口映射。

H.264 profile 不应写成“必须 Baseline/Main”。兼容性还取决于客户端协商的 `profile-level-id`、`packetization-mode`、level、浏览器版本和设备解码能力。以目标浏览器实测为准，必要时选择更保守的 profile 或转码。

## 时间戳策略

`[protocol] modify_stamp` 的模式需要结合源流和输出协议选择：保留源绝对 timestamp、使用 ZLMediaKit 接收时钟，或使用相对 timestamp 并做跳变修正。它们会改变延迟、连续性和跨协议表现；修改后要用 packet 级 PTS/DTS 与实际播放验证。

不要把 ZLM 的 timestamp 修正和 FFmpeg 的 `-use_wallclock_as_timestamps`/`+genpts` 当成同一层的开关。跨设备合流仍需明确主时钟、offset 和 drift 处理。

## C++ 扩展边界

- 不直接改底层 TCP socket 来获取媒体帧；使用当前版本的 `MediaSource::getTracks()`、`Track::addDelegate()` 或项目明确提供的媒体 sink 接口。
- 不在 EventPoller 中执行阻塞 FFmpeg、同步数据库、磁盘或外部 HTTP；见 `references/zlm-api.md`。
- 在 source 注销、重连和 track 变化时移除 delegate，保证 `Frame::Ptr`、队列和对象所有权顺序明确。
