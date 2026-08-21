# ZLMediaKit C++ 二次开发指南

## EventPoller 与阻塞任务 (`#zlm-event-poller-block`)

ZLMediaKit 的 socket、协议会话和大量媒体分发回调绑定到 `EventPoller`。回调中执行数据库、磁盘、同步 HTTP、`avformat_open_input`、长时间算法推理或不可控等待，会阻塞同一个 poller 上的其他 I/O；具体影响范围取决于对象绑定的 poller，不应假设每个连接都有独立线程。

正确的处理方式是：

1. 在 poller 回调中只做短小的状态更新和引用转移。
2. 使用项目当前依赖版本的 `Thread/WorkThreadPool.h` 将阻塞任务提交到工作线程；任务必须有界、可取消，不能无限增长。
3. 任务完成后通过存活对象对应的 poller 回切网络/媒体状态。使用 `weak_ptr` 检查对象仍然存在，不能捕获已经可能析构的裸 `this`。
4. 关闭时先停止接受新任务，再唤醒/取消工作任务，最后移除 delegate、关闭 socket 和销毁对象。

当前 upstream 常见形式如下；包含路径和返回类型应以项目实际 vendored ZLToolKit 版本为准：

```cpp
#include "Thread/WorkThreadPool.h"

auto weak_source = std::weak_ptr<MediaSource>(source);
toolkit::WorkThreadPool::Instance().getPoller()->async(
    [weak_source, request = std::move(request)]() mutable {
        auto result = run_blocking_work(request);
        if (auto source = weak_source.lock()) {
            if (auto poller = source->getOwnerPoller()) {
                poller->async([weak_source, result = std::move(result)]() mutable {
                    if (auto source = weak_source.lock()) {
                        apply_result_on_owner_poller(*source, result);
                    }
                });
            }
        }
    });
```

`async` 只解决线程归属，不解决队列无界、任务取消、结果过期或对象生命周期。需要为队列设置容量、超时和 shutdown 行为。

## 当前帧分发 API (`#zlm-track-dispatch`)

当前 ZLMediaKit upstream 的常见路径是先从 `MediaSource::getTracks(true)` 获取已经 ready 的 track，再对具体 `Track` 使用 `FrameDispatcher::addDelegate`。不要使用未经版本证明的 `MediaSource::addTrackListener`：不同 fork 可能有同名封装，但当前 upstream 的接口和 `Track` 生命周期应以头文件为准。

```cpp
auto tracks = source->getTracks(true);
for (const auto &track : tracks) {
    auto *delegate = track->addDelegate(
        [weak_sink](const Frame::Ptr &frame) -> bool {
            auto sink = weak_sink.lock();
            if (!sink) return false;
            return sink->inputFrame(frame);
        });
    delegates.emplace_back(track, delegate); // teardown 时按原 track 删除
}
```

`addDelegate` 返回的指针必须保存，并在 sink 销毁前调用对应 `track->delDelegate(delegate)`。回调收到的是 `Frame::Ptr`，如果要跨线程排队，应保存 shared ownership 或复制数据；不得只保存 `frame->data()` 裸地址。算法或 FFmpeg 解码耗时较长时，回调只负责把 frame 放入有界队列，并明确满队列时可丢弃的帧类型。

Track 可能在流初始化、重连或协议转换时发生变化。注册监听后还要处理新 track、track ready 状态和 source 注销，不要只在启动时假设永远只有一个视频 track。

## Socket 与回调

ZLMediaKit 的发送接口通常是异步 socket 写入；不能把每次 `send` 都描述成必然死锁，也不能把它当成阻塞 I/O 的安全替代。关注发送缓存、背压、回调线程和关闭竞态：

- 不在 poller 回调中执行同步网络请求或等待发送完成。
- 不在持有 ZLM 内部锁时调用外部回调。
- 处理写缓存增长、下游断开和 stop 顺序；必要时丢弃可丢弃帧或断开过慢消费者。
- 外部对象回调使用弱引用，避免 source/socket 先销毁后回调仍访问 `this`。
