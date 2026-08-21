# FFmpeg C++ API 规范

## 解码循环

`avcodec_send_packet`/`avcodec_receive_frame` 是一组有状态 API。一个 packet 可能产生零个、一个或多个 frame；每次发送后都要持续接收，直到 `EAGAIN` 或 `EOF`。

```cpp
// drain_decoder() calls receive_frame until EAGAIN or EOF and unrefs the
// reusable frame after consume_frame() returns.
auto drain_decoder = [&]() -> int {
    for (;;) {
        int ret = avcodec_receive_frame(codec_ctx, frame);
        if (ret == AVERROR(EAGAIN)) return 0;
        if (ret == AVERROR_EOF) return AVERROR_EOF;
        if (ret < 0) return ret;
        consume_frame(frame);            // ref/copy before async hand-off
        av_frame_unref(frame);
    }
};

for (;;) {
    int ret = av_read_frame(fmt_ctx, pkt);
    if (ret == AVERROR_EOF) {
        // Decoder flush: send NULL once, then drain until AVERROR_EOF.
        ret = avcodec_send_packet(codec_ctx, nullptr);
        if (ret < 0 && ret != AVERROR_EOF) return ret;
        do {
            ret = avcodec_receive_frame(codec_ctx, frame);
            if (ret == AVERROR_EOF) break;
            if (ret == AVERROR(EAGAIN)) return AVERROR(EINVAL);
            if (ret < 0) return ret;
            consume_frame(frame);
            av_frame_unref(frame);
        } while (true);
        break;
    }
    if (ret < 0) return ret;

    for (;;) {
        ret = avcodec_send_packet(codec_ctx, pkt);
        if (ret != AVERROR(EAGAIN)) break;
        // The decoder still has output. Drain it, then retry the same packet.
        ret = drain_decoder();
        if (ret < 0) return ret;
    }
    av_packet_unref(pkt);                // no longer needed after send
    if (ret < 0) return ret;
    ret = drain_decoder();
    if (ret < 0) return ret;
}
```

上面 `EAGAIN` 分支只是表示控制流必须设计成“保留输入并先排空输出”；生产代码不要像示例那样直接丢 packet。更清晰的实现是把“发送一个输入”和“排空输出”封装成可重试的函数，并确保 `av_packet_unref` 只发生在 packet 不再需要之后。

`avcodec_send_packet` 返回成功后，FFmpeg 会持有所需的引用；调用方仍负责在自己的复用周期结束时 unref packet。`receive_frame` 成功后，若异步保存 frame，先 `av_frame_ref` 或复制数据，再 unref 可复用的 frame。

## 编码循环

编码器的 EOF 操作使用 `avcodec_send_frame(codec_ctx, nullptr)`，然后循环 `avcodec_receive_packet`。不要用 decoder 的 `send_packet(nullptr)` 代替。每次复用输出 packet 前调用 `av_packet_unref`，写入 muxer 前确认 packet 的 time base 和所有权。

## 返回值约定

- `EAGAIN` 表示当前方向需要继续驱动另一方向，不是“丢帧”或普通成功。
- `AVERROR_EOF` 表示当前 codec 已经 drain 完毕；收到它后不要继续发送同一方向的新输入，除非重新初始化/flush。
- 其他负值保留错误码并记录上下文；不要把所有负值统一当作网络断开。
- `avcodec_flush_buffers` 用于 seek/重置状态，不用于读取到 EOF 时提取最后几帧。

## 可取消的输入上下文

`interrupt_callback` 必须在打开输入前配置，并且回调所引用的状态对象要活到 FFmpeg 不再访问它为止：

```cpp
struct ReadState {
    std::atomic_bool stop{false};
    std::chrono::steady_clock::time_point deadline;
};

static int interrupt_cb(void *opaque) noexcept {
    auto *state = static_cast<ReadState *>(opaque);
    return state->stop.load(std::memory_order_relaxed) ||
           std::chrono::steady_clock::now() >= state->deadline;
}

AVFormatContext *fmt_ctx = avformat_alloc_context();
ReadState state{false, std::chrono::steady_clock::now() + std::chrono::seconds(5)};
fmt_ctx->interrupt_callback = AVIOInterruptCB{interrupt_cb, &state};

AVDictionary *options = nullptr;
// Set only options supported by this FFmpeg build.
int ret = avformat_open_input(&fmt_ctx, url, nullptr, &options);
av_dict_free(&options);
if (ret < 0) {
    // Keep state alive until the failed call has returned.
    return ret;
}
```

实际项目应使用可编译的 `std::chrono` 字面量或显式 `seconds`，并在 `avformat_open_input`、`avformat_find_stream_info`、`av_read_frame`、seek 和关闭路径测试取消。回调中不得抛异常、阻塞或调用会再次进入同一 FFmpeg context 的函数。

## 上下文生命周期与 time base

- 成功打开的 `AVFormatContext` 用 `avformat_close_input(&fmt_ctx)` 关闭；未成功打开或由其他 API 分配的 context 按该 API 的所有权契约释放。
- `AVCodecContext` 用 `avcodec_free_context(&codec_ctx)`。
- `AVPacket`/`AVFrame` 指针对象用对应 `*_free`，循环内部引用用对应 `*_unref`。
- `AVDictionary` 用 `av_dict_free`，`AVBufferRef` 用 `av_buffer_unref`。
- packet 写入 muxer 前，根据 packet 当前的来源 time base 调用 `av_packet_rescale_ts(pkt, src_tb, stream_tb)`；先处理 `AV_NOPTS_VALUE`，不要把无效 timestamp 直接送入 muxer。

建议用 RAII 包装拥有对象，但保留清晰的 unref 边界和错误路径；RAII 不能代替协议/线程停止设计。
