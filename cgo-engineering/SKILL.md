---
name: cgo-engineering
description: >
  当用户要求设计、实现、迁移、调试、优化或 Review Go 通过 cgo/CGO 调用 C/C++ 时加载，
  包括 wrapper、C++ shim、native callback、ABI、CMake/pkg-config、链接、sanitizer、
  崩溃、数据竞争、泄漏和交叉编译。不要用于纯 Go 并发、独立 C/C++ 项目，或不涉及
  Go/native 边界的普通构建问题。
---

# CGO Engineering

## 目标

把 CGO 当作一个需要显式契约的 FFI 边界，而不是“在 Go 文件里写几行 C”。每次工作都要能回答：

- 谁拥有每一块内存，何时创建、转移和释放？
- 哪些线程可以调用哪一侧，回调如何进入 Go，阻塞和锁如何处理？
- 两侧的类型、布局、调用约定、编译器和运行时是否兼容？
- 错误、NULL、长度、字符串编码、异常和取消如何跨边界传播？
- 测试是否覆盖了失败路径、重复释放、并发和实际链接/运行环境？

默认原则是**先分析后修改**：先确认事实和契约，再选择最小、可测试、可回滚的改动。需求明确且风险可控时可以直接实现，但仍须完成探测、边界设计和验证。

## Always Read

- 目标包的 `go.mod`、构建脚本、CI、测试和仓库规范；不要凭空假定 native 库、版本或路径。
- 目标 C/C++ 库当前版本的头文件和官方 ABI/生命周期文档；仓库代码与官方文档冲突时，记录差异并以实际支持矩阵为准。
- 本文件中与任务匹配的“最高风险坑点”和验证门槛；不要只读开发步骤而跳过边界规则。

## 工作路由

| 用户请求 | 先做什么 | 必须覆盖 |
|---|---|---|
| 开发或迁移 wrapper | 探测仓库和 native API，写边界契约，再实现窄 shim | 所有权、错误、关闭、ABI、测试 |
| C/C++ 回调或异步 API | 画出线程、回调上下文和关闭时序 | Go 指针、`cgo.Handle`、重入、注销、join |
| 崩溃、死锁、数据竞争、泄漏 | 保存最小复现，先分类编译/加载/内存/并发问题 | Go 栈与 native 栈、sanitizer、原始复现 |
| 编译或链接失败 | 检查实际 compiler、flags、符号、架构和加载路径 | 预处理、编译、链接、动态加载分别验证 |
| Review CGO diff | 先按契约、内存、并发、异常、ABI、错误、测试排序 | 只报告有场景和后果的 finding |

## 最高风险坑点

这些是优先检查的真实故障模式。发现一项时，先确认事实和生命周期，再写代码或给出结论。

1. **把 cgo 指针规则当成类型规则。** Go 指针是否能跨界取决于它指向的内存及其可达对象，不是看参数写成 `unsafe.Pointer` 就安全。默认不要把 Go 指针交给 C 保存；传入 Go 内存时只能在当前 Go 版本允许的规则内短期借用。传 `&b[0]` 前先检查 `len(b) > 0`，不要把 slice header、map、interface、channel、function 或含 Go 指针的 struct 当作 C buffer。
2. **把 `runtime.KeepAlive` 当成所有权工具。** 它只保证对象在指定点前仍可达、避免 finalizer 过早运行，不能绕过指针规则、不能让 C 异步保存 Go 指针，也不能替代 C 侧拷贝。若项目版本支持 `runtime.Pinner`，C 保留 pinned 指针期间必须让 `Pinner` 本身保持可达，并在 C 释放后调用 `Unpin`；若 pinned 对象还包含 Go 指针，相关对象也要分别满足 pinning 规则。默认仍优先复制到 C-owned 内存。
3. **忘记转换函数的分配语义。** `C.CString` 和 `C.CBytes` 在 C 堆分配，必须由明确的 C allocator/free 配对释放；`C.GoString`、`C.GoStringN` 和 `C.GoBytes` 会复制到 Go，调用者仍须按原 owner 规则处理源 C 指针，但不应对返回的 Go 值调用 `C.free`。二进制数据总是传指针加长度，不要依赖 NUL。
4. **异步回调提前释放上下文。** C 线程可能在 `Close` 返回后仍执行回调。正确顺序通常是停止生产、注销回调、等待/join 所有 worker，最后 `cgo.Handle.Delete` 和释放 C context；只写 `defer Delete` 或只设置一个 closed flag 不够。
5. **错误地把 `cgo.Handle` 当成指针。** `cgo.Handle` 是可在 C 中传递的整数句柄，不要把它强转成 `unsafe.Pointer`。句柄在 C 不再持有其数值后才能 `Delete`，且 `Value`/重复 `Delete` 可能 panic；把删除放在可证明的单一释放路径。
6. **把回调参数的瞬时地址交给 goroutine。** C 传入的字符串、buffer、event struct 通常只在回调期间有效；回调返回后异步使用必须复制到 Go-owned 或 C-owned 的存储，并明确长度、编码和释放方。
7. **在回调中持有 native 锁或等待 native。** C 回调进入 Go 后长期阻塞、再次调用会等待当前回调完成的 API，或与 `Close` 形成反向锁序，都会死锁。回调只做校验和复制，通常投递到 Go 队列；锁顺序和重入协议要写进契约。
8. **让异常穿过边界。** C++ shim 的每个导出入口捕获 `...`，把异常转换成稳定的错误码/错误 buffer；C++ exception、STL、引用、类对象和析构细节不能穿过 C ABI 进入 Go。Go 导出回调也不能把 panic 当成 C 可处理的返回值；需要可恢复时在回调边界 `recover` 并转换。
9. **误读 `errno`。** cgo 调用可返回 `errno`，但成功调用也可能留下非零值。先判断主返回值是否表示失败，再读取错误；不要用“`err != nil`”单独判断 C API 是否失败。
10. **`//export` 的 preamble 放了定义。** 含 `//export` 的 Go 文件会把 preamble 复制到多个 C 输出文件；其中只放声明，所有函数和全局定义移到单独的 `.c/.cc` 文件，否则可能 duplicate symbol。C 函数指针和 C 变参也不能直接按 Go 直觉调用，用固定签名的 C bridge 包装。
11. **用错误的 ABI 类型“碰巧能跑”。** `long`、`size_t`、`enum`、`_Bool`、指针、packed/bit-field struct、对齐和 endianness 都可能随平台变化。优先传固定宽度整数、指针加长度和不透明句柄；用 shim 访问字段，并对 `sizeof`/对齐/版本加断言。
12. **把链接成功当成部署成功。** `undefined reference`、SONAME/符号版本不匹配、`RPATH`/`RUNPATH`、容器镜像和生产运行用户的搜索路径是不同阶段。必须在目标环境检查实际依赖和动态加载，不要只追加一个 `-L`。
13. **把 Go 的 `-race` 当成 native race 证明。** `go test -race` 只对执行到的路径提供 Go race 检测，且需要 cgo/compiler；它不自动证明任意第三方 C/C++ 内部无数据竞争。native 代码需要单独可行的 ThreadSanitizer 或专门的 native 并发测试，并记录工具兼容性。
14. **只给一层加 sanitizer flags。** ASan/UBSan 要让被测 C/C++ 编译，并确保最终链接步骤带上对应 runtime；使用编译器 driver 而不是直接调用 `ld`，保存符号化栈。sanitizer 报告优先修第一处内存破坏，不要用 suppression 掩盖自己的边界错误。
15. **随手添加 `#cgo noescape` 或 `nocallback`。** 这些是基于证明的优化提示；`noescape` 判断错会产生内存破坏，`nocallback` 判断错会在 C 回调 Go 时 panic。没有源码和调用图证明时不要使用。

## 1. 先探测事实

不要在没有检查仓库的情况下假定 CGO 的目录、库名或平台。先执行与任务匹配的只读检查：

1. 查看 `go.mod`、Go toolchain、`GOOS`/`GOARCH`、`CGO_ENABLED`、CI 配置和 Makefile。
2. 搜索 `import "C"`、`// #cgo`、`.h/.c/.cc/.cpp/.hpp`、`CMakeLists.txt`、`pkg-config`、`CGO_CFLAGS`、`CGO_LDFLAGS`、`dlopen`、`//export` 和 callback。
3. 确认 native 依赖来源、版本、头文件路径、静态/动态链接方式、运行时库搜索路径和许可证约束。
4. 读取目标包及其测试、构建脚本、CI 和项目规范；本仓库工作时同时遵守 `AGENTS.md` 与相关规范文件。
5. 记录平台矩阵：默认按项目声明的 Go、C/C++ 标准、系统库和架构检查；不要把“本机能编译”当成兼容性证明。
6. 先运行或复现用户给出的命令，区分源码错误、环境缺失、链接错误和运行时错误。保留完整命令，去除 secrets。

如果仓库没有现成 CGO 代码，先探测目标 native 库、API、平台和部署方式，再提出最小接入设计；不要凭空生成看似可用的库名、ABI 或 CMake 选项。目标不清且无法从仓库推断时，停在设计阶段并询问必要信息。

## 2. 设计边界契约

在动手改代码前，用简短的设计记录或计划明确以下内容。至少为每个跨界对象写清：

```text
对象：
分配方 / 当前 owner / 转移条件 / 释放函数：
借用还是异步保存：
有效期与关闭顺序：
是否可并发、是否可重入：
NULL、长度、编码、错误和取消语义：
支持的 Go/C/C++/OS/架构矩阵：
```

### 2.1 API 形状

- Go API 暴露领域语义，不把 `C.*` 类型、宏、裸指针或 native 错误码泄漏到上层。cgo 类型也不要跨 Go package 暴露，因为同名 C 类型在不同 Go package 中不是同一个导出类型。
- 用不透明句柄、整数 ID 或 Go 管理的 wrapper 表示 native 对象；wrapper 的零值、关闭状态和并发语义要明确。含 mutex、句柄或 finalizer 的 wrapper 避免值复制。
- 指针配对长度，长度使用与 C API 匹配的类型；从 Go `int` 转换前检查负值和溢出。空 buffer 用 `NULL, 0` 或项目约定表示，不取空 slice 的首地址。
- 字符串明确编码、所有权和是否允许嵌入 NUL；`C.CString`/`C.CBytes` 的 C 分配要有对应释放，`C.GoString`/`C.GoBytes` 的源指针仍按原 owner 管理。
- 将 native 错误码转换为稳定的 Go `error`，保留可诊断的上下文但不把内部地址、密钥或不可信内容直接写入日志。
- 对可取消、阻塞或耗时操作说明取消是否真正中断 native 调用；不要承诺 native 库无法提供的语义。

### 2.2 所有权与生命周期

默认优先级：**不把 Go 指针传给 C/C++；优先传 C 分配的内存、句柄、整数/长度，或显式拷贝后的 buffer**。短期借用只有在符合当前 Go 版本 cgo pointer rules、调用期间有效且 C 不保存该指针时才可接受。

每个跨边界对象必须标明：

- 分配方、释放方和唯一释放入口；`malloc/free`、`new/delete` 和库专用 destroy/free 不得混配，跨 CRT/allocator 时使用同一库提供的释放函数。
- 是否可复制、移动、关闭后使用，以及并发调用/关闭是否安全。
- C/C++ 是否会保存指针或异步使用 buffer；若会，复制到 native 所有的内存，或使用版本适配且精确管理的 pinning/lifetime 协议。使用 `runtime.Pinner` 时，`Unpin` 要发生在 C 不再访问对象之后，且 `Pinner` 自身要保持可达。
- Go wrapper 是否可能被复制；必要时使用指针接收者、`noCopy` 约定或内部状态检查。
- `runtime.KeepAlive` 只用于保证 Go 对象活到调用结束，不能绕过 cgo 指针规则，也不能替代 C 侧拷贝或所有权转移。
- finalizer 只作兜底，不作为确定性释放；提供幂等的 `Close`，并在关闭后拒绝操作。

### 2.3 C++ 异常与边界

**C++ 异常禁止穿过 CGO 边界进入 Go。** 在 C++ shim 中捕获 `...`，将异常转换为稳定的错误码/错误对象；错误消息需由明确的释放函数管理，或在 shim 内复制到调用方提供的 buffer。检查 `noexcept`、析构函数异常、异常导致的部分初始化和资源泄漏。

尽量让边界是带 `extern "C"` 的窄 C ABI：

- C++ 模板、重载、STL 对象、引用、类布局和异常停留在 shim 内。
- 头文件使用 C/C++ 兼容的 `extern "C"` guards；声明与实现、导出宏、调用约定保持一致。
- 不让 Go 依赖 C++ name mangling、编译器私有布局或跨编译器 STL ABI。
- 入口在异常路径也要返回可判定的状态，不能只写日志后继续使用未初始化的输出 buffer。

### 2.4 并发、线程和回调

先确认 native 库的线程安全级别，而不是看到 Go wrapper 就假设可并发：

- 每个句柄标明是否可并发调用、是否需要外部锁，避免在 C 回调、Go 回调和关闭路径之间形成锁顺序反转。
- C/C++ 工作线程异步回调 Go 时，使用受支持的 `//export`/C trampoline 和 `cgo.Handle` 或 C-owned context；不要把 Go 函数指针或 Go 指针保存到 C。
- 回调参数在回调返回后仍需使用时，必须复制到 C-owned/Go-owned 的明确存储；不要把瞬时指针直接交给异步 goroutine。
- 回调边界捕获并转换 Go panic，或明确记录“panic 将终止进程”的契约；不要指望 C++ `catch` 捕获 Go panic。
- 回调中避免长期阻塞、不可重入调用、持有 native 锁进入 Go，或在 Go 回调中再次调用会等待该回调完成的 native API。
- 明确停止、注销、等待工作线程和释放回调上下文的顺序；关闭后不得再触发回调。把这个顺序写成测试，而不是只依赖 flag。
- 只有目标 API 有线程亲和性或 per-thread state 时才使用 `runtime.LockOSThread`，并保证每次锁定都有对应解锁；不要用它掩盖错误的回调模型。

### 2.5 ABI、构建和部署

验证而不是猜测：

- 固定或记录支持的编译器、C/C++ 标准、架构、系统库和 ABI；检查 `sizeof`、对齐、整数宽度、枚举、布尔值、结构体布局和 endianness。
- 不跨边界传递手写的、布局假设不明的 struct；用 shim 函数访问字段，必要时加编译期/运行时断言。固定宽度整数优先于 `long` 等平台相关类型。
- `#cgo` flags、pkg-config、CMake targets、静态/动态库、`rpath`/`RUNPATH`、链接顺序和系统依赖必须可重复构建。包级 flags 放在 `#cgo`/构建系统，避免依赖开发机临时环境变量。
- 不把开发机绝对路径、未转义用户输入或未经审查的环境变量拼入编译/链接 flags；cgo 对 flags 有安全过滤，绕过过滤前先说明原因和风险。
- 检查 `CGO_ENABLED=0` 时的行为：明确不支持、提供 stub/build tags，或在文档中说明，而不是让包半可用。`import "C"` 文件只在 cgo enabled 时参与构建。
- 交叉编译需要对应 C 编译器、C++ 编译器、sysroot、目标库和 `PKG_CONFIG` 配置；`GOOS/GOARCH` 设置本身不等于 CGO 交叉编译完成。
- 动态库部署要验证加载路径、SONAME、符号版本、容器/生产镜像和运行用户可见的依赖；不要只看链接阶段通过。
- 构建脚本应避免隐式下载、未锁定版本和将 secrets 写入命令行/产物。

## 3. 按工作模式执行

### A. 开发或迁移

1. 写出边界契约和不变量：所有权、错误、线程、关闭、平台。
2. 优先新增窄 C shim，再写小而稳定的 Go wrapper；每层只负责一类转换。C++ 类、STL 和异常不要出现在 Go 头文件可见的 ABI 中。
3. 让 C/C++ 侧负责 native 对象的创建/销毁、异常捕获和必要的数据拷贝；让 Go 侧负责上下文、API 体验、错误包装和高层生命周期。
4. 对每个分支补测试：成功、NULL/空输入、长度边界、native 错误、分配失败（可注入时）、重复 `Close`、关闭中调用、回调停止和异常映射。
5. 修改构建配置和文档，使干净环境能复现构建；不要只依赖本机未记录的 `/usr/local` 状态。
6. 完成分层验证后再报告；若环境缺少 native 依赖，明确哪些验证未执行以及如何执行。

### B. Review

Review 按以下顺序检查，并把问题锚定到文件和行号。优先报告会导致崩溃、内存破坏、数据竞态、ABI 不兼容或不可恢复泄漏的问题。

1. **契约**：API 的所有权、关闭、线程安全、错误和平台假设是否可读且一致。
2. **内存**：分配/释放配对、slice/string 生命周期、指针规则、长度溢出、NULL、异步保存、finalizer 和 allocator。
3. **并发回调**：回调线程、上下文、重入、锁、关闭/注销顺序、竞态和 goroutine 生命周期。
4. **C++边界**：异常是否被捕获，STL/类/引用是否泄漏到 ABI，析构和部分构造是否安全。
5. **ABI/构建**：声明、布局、编译器、标准库、架构、链接和动态加载是否匹配；CI 是否覆盖支持矩阵。
6. **错误与数据**：错误是否丢失/误判，字符串和二进制长度是否正确，panic/异常是否跨界，日志是否泄露敏感数据。
7. **测试**：失败路径、并发、重复释放、sanitizer、真实库加载和跨平台构建是否被覆盖。

每个 Review finding 使用：

- **严重性**：`阻断` / `高` / `中` / `低`，按实际后果而非代码风格排序。
- **位置**：`path/to/file:line`，尽量指向引入问题的最小行。
- **场景**：给出具体输入、调用顺序、线程或平台条件。
- **问题**：说明违反的边界不变量和实际后果。
- **修复**：给出最小安全修复及需要补的测试。

不要把纯风格偏好伪装成安全问题。没有足够证据时标为待确认，并说明需要的实验或文档。若用户授权修复，先修高严重性问题，再重新检查完整 diff，避免只修表象。

### C. 构建与运行时调试

先把错误分类：预处理/编译、链接、动态加载、启动崩溃、运行时内存、数据竞争、死锁、逻辑错误。保留最小复现和完整命令（去除 secrets），然后逐层缩小范围：

- 编译/链接：检查实际 `CC`/`CXX`、flags、include/library 搜索路径、符号（如 `nm`/`readelf` 可用时）和目标架构；用 `go test -x` 或项目 verbose 模式核对实际命令，不要通过随意添加 `-L` 或禁用检查掩盖错误。
- 加载：检查 `readelf -d`、依赖树、SONAME、`RPATH`/`RUNPATH`、`LD_LIBRARY_PATH`、容器镜像和运行用户可见的路径；必要时用目标动态 loader 的诊断选项。
- 内存/并发：在最小测试上使用可用的 `go test -race`、AddressSanitizer/UndefinedBehaviorSanitizer、LeakSanitizer、valgrind 或 native 调试器；记录工具版本、编译范围和限制。Go race 通过不等于 C/C++ race 已排除。
- 崩溃：保留 native 栈和 Go 栈，核对崩溃线程、最近一次跨界调用、对象关闭时间和错误返回；不要只凭 Go panic 栈定位 C 内存错误。
- 每次只改变一个关键变量，修复后重跑原始复现、回归测试和构建矩阵中的相关项。

## 4. 分层验证门槛

按改动和环境可用性执行，报告每项结果，不把跳过写成通过：

1. **格式与静态检查**：`gofmt`、项目规定的 Go lint/vet、C/C++ formatter/linter（若项目配置）。
2. **Go 单元测试**：目标包测试，再按影响范围运行 `go test ./...`；CGO 场景确认测试实际启用 native 路径而不是误走 stub。
3. **构建/链接**：干净环境下的 `go build`/项目 Make target，以及 CMake/pkg-config/native 库构建；检查动态库实际加载，而不是只检查文件存在。
4. **指针与并发检查**：保留默认 `GODEBUG=cgocheck=1`；适用时用当前 Go 版本支持的更严格 cgo 检查、`go test -race` 和专门的 native 并发测试。记录 race 工具没有覆盖的 native 代码。
5. **内存检查**：按工具链运行 ASan/UBSan/LSan 或 valgrind；确保被测 C/C++ 被 instrument，并让最终链接包含对应 runtime。修复第一处真实报告后再运行下一轮。
6. **集成与平台**：验证真实 API 调用、回调、关闭顺序和目标平台；交叉编译至少验证 toolchain、sysroot、目标库和 pkg-config 配置。

命令失败时保存关键输出，区分代码失败与环境前置条件缺失。完成报告至少包括：修改内容、边界/风险结论、运行过的命令及结果、未执行项目及原因、后续建议。

## 5. 安全与操作边界

- 只处理用户授权的仓库、库和构建目标；不要下载或执行来源不明的二进制、脚本或远程构建命令。
- 不为绕过安全控制、窃取凭据、隐藏恶意行为或破坏第三方系统编写 native/CGO 代码。
- 在删除、替换 native 库、改动 ABI 或覆盖构建产物前，先检查目标并确认影响范围；优先使用可回滚的小改动。
- 不提交密钥、私有路径、未审查的生成物或依赖缓存。

## 输出要求

### 开发/迁移完成

```text
## 完成
- 实现：...
- 边界契约：所有权 ...；并发 ...；错误 ...；ABI ...

## 验证
- `command`：通过/失败（关键原因）

## 未执行与风险
- ...
```

### Review完成

先列 findings（阻断/高/中/低），每条包含位置、场景、后果和修复建议；再列“已修复项”和验证命令。若没有问题，说明检查范围、验证过的路径和仍未覆盖的假设，而不是只写“LGTM”。

## 参考资料

需要查具体规则时，优先读取与当前 Go/工具链版本对应的官方文档：

- [cmd/cgo](https://pkg.go.dev/cmd/cgo)：指针规则、`//export`、转换函数、`errno`、flags、交叉编译、`noescape`/`nocallback`。
- [runtime/cgo](https://pkg.go.dev/runtime/cgo)：`cgo.Handle` 的传递、有效期和显式 `Delete`。
- [runtime](https://pkg.go.dev/runtime)：`KeepAlive`、`Pinner`、`LockOSThread` 和 cgo 检查配置。
- [Go race detector](https://go.dev/doc/articles/race_detector)：`-race` 的使用、运行时限制和平台要求。
- [Clang AddressSanitizer](https://clang.llvm.org/docs/AddressSanitizer.html) 与 [UndefinedBehaviorSanitizer](https://clang.llvm.org/docs/UndefinedBehaviorSanitizer.html)：native 内存/未定义行为检查和最终链接要求。
- [Linux `ld.so`](https://man7.org/linux/man-pages/man8/ld.so.8.html)：运行时共享库搜索顺序、`RPATH`/`RUNPATH`、`LD_LIBRARY_PATH` 和 secure-execution。
- [CMake `FindPkgConfig`](https://cmake.org/cmake/help/latest/module/FindPkgConfig.html)：pkg-config 查询和 imported target。
- [Itanium C++ ABI exception handling](https://itanium-cxx-abi.github.io/cxx-abi/abi-eh.html)：C++ 异常展开和 ABI 边界背景。

不要用未经验证的博客示例替代项目实际 ABI、工具链和库文档。
