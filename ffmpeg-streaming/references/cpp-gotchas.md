# C++ 开发中的 FFmpeg 流媒体坑点

<a id="ffmpeg-eof-flush"></a>
## FFmpeg EOF flush

解码器和编码器的 drain 操作不同，不能混用：

- **解码器读到 EOF**：停止读取新 packet，调用一次 `avcodec_send_packet(codec_ctx, nullptr)`，然后循环 `avcodec_receive_frame`，直到 `AVERROR_EOF`。`EAGAIN` 表示当前 drain 需要更多输入或调用顺序不对，不能当作成功结束。
- **编码器输入结束**：调用一次 `avcodec_send_frame(codec_ctx, nullptr)`，然后循环 `avcodec_receive_packet`，直到 `AVERROR_EOF`。
- **seek 或重置到新流**：`avcodec_flush_buffers` 是丢弃内部缓存并重新开始，不是 EOF drain。重置后还要重置 packet/frame 时间戳状态。

正常循环中，`send` 返回成功后要持续 `receive`，直到 `EAGAIN` 或 `EOF`，再送下一个输入。不要在尚未排空输出时不断发送新 packet/frame。

<a id="ffmpeg-memory-leak"></a>
## AVPacket/AVFrame 所有权

区分“释放内部引用”和“释放对象本身”：

- 循环复用的 `AVPacket`/`AVFrame` 在本轮处理完成后调用 `av_packet_unref`/`av_frame_unref`。
- 由 `av_packet_alloc`/`av_frame_alloc` 创建的指针最终调用 `av_packet_free`/`av_frame_free`。
- 将 packet/frame 放入异步队列或回调后，不能只保存裸指针。使用 `av_packet_ref`、`av_frame_ref` 或明确转移拥有权，并让消费者在完成后释放。
- `av_read_frame` 成功返回的 packet 必须在所有分支中 unref；发送给解码器不会自动替调用者释放 packet。
- RAII 自定义 deleter 只解决对象终点释放，不能代替循环中的 `unref`，也不能修复异步消费者保存的悬空裸指针。

示例的拥有对象可以这样封装：

```cpp
struct AVPacketDeleter {
    void operator()(AVPacket *pkt) const { av_packet_free(&pkt); }
};
using AVPacketPtr = std::unique_ptr<AVPacket, AVPacketDeleter>;
```

栈对象或由调用方拥有的 packet/frame 不应套用 `av_packet_free`/`av_frame_free`；按照创建 API 的所有权契约处理。

<a id="avformat-block"></a>
## FFmpeg 网络拉流阻塞

URL timeout 和 C API 的取消回调解决不同问题：

- 根据当前 FFmpeg 构建支持的 protocol/demuxer 选项设置 I/O timeout；不要固定复制旧版 `-stimeout`。
- 在调用 `avformat_open_input` 前设置 `AVFormatContext::interrupt_callback`。回调应读取原子停止标志或截止时间，满足条件时返回非零；不抛出 C++ 异常。
- `opaque` 指向的对象必须在 `avformat_open_input`、`av_read_frame`、seek 和关闭路径完成前保持有效。回调中只做无锁或短时操作，避免再次调用 FFmpeg。
- 任何 `av_read_frame` 错误都要区分 EOF、取消、网络 timeout 和损坏数据；收到取消后按固定顺序停止生产、唤醒消费者、join 线程、最后关闭 FFmpeg 上下文。

<a id="pts-dts-calc"></a>
## 时间戳、time base 与 `AV_NOPTS_VALUE`

- 每个 stream、codec 和 muxer 都可能有不同的 `time_base`。写 packet 前使用真实来源的 time base 调用 `av_packet_rescale_ts`，不要直接把整数 tick 当成毫秒。
- 处理 `AV_NOPTS_VALUE` 前先定义策略：保留无效值并让上层处理、从可靠的输入时钟重建，或拒绝该 packet。不要把这个哨兵值直接送给 muxer。
- 不要用固定 FPS 猜测可变帧率或多设备混流的 timestamp。对于独立音频/视频设备，应明确主时钟、初始 offset、漂移补偿和重采样策略。
- `PTS` 表示显示顺序，`DTS` 表示解码顺序；B 帧会让两者不同。muxer 通常要求 DTS 按其 time base 单调，具体约束以目标封装格式为准。
- `-use_wallclock_as_timestamps 1` 是输入侧的 wallclock timestamp 策略，不是通用音视频同步开关；`-fflags +genpts` 主要补生成缺失 PTS，也不能校准两个独立时钟。
- 负 timestamp、`start_time` 和跨 stream offset 需要在同一个时钟模型中处理。修复后用 packet 级输出验证，不要只看播放器是否暂时能播放。

<a id="async-frame-ownership"></a>
## 异步帧管道所有权

跨线程传递 FFmpeg 对象或 ZLMediaKit `Frame::Ptr` 时，使用有界队列并明确三件事：生产者何时停止、队列满时丢什么、消费者何时释放引用。停止流程必须先阻止新回调，再唤醒队列消费者，最后销毁 codec/context；不能让回调捕获已经析构的 `this`。
