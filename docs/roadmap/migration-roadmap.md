# Iluvatar AI Notebook 内核迁移路线图

> 基于《Iluvatar AI Notebook 是否应该复用 Jupyter 的库？》分析报告，制定从手写 KernelManager 到分层复用 Jupyter 生态的详细迁移路线图。

---

## 1. 总体目标

将当前 `core/kernel.py` 中基于 `multiprocessing.Queue` + `exec()` 的手写内核，替换为 **jupyter_client + ipykernel + 自定义 IluvatarProvisioner** 的三层解耦架构，同时保持 Flask 后端和 Vanilla JS 前端不变，保留 AI Copilot、GPU 遥测等差异化能力。

| 维度 | 当前状态 | 目标状态 |
|------|---------|---------|
| 执行引擎 | `exec()` 裸执行 | ipykernel（IPython 完整能力） |
| 通信机制 | `multiprocessing.Queue` 双向队列 | ZMQ 五通道（shell/iopub/control/stdin/hb） |
| 输出方式 | 阻塞式一次性返回 | SSE 流式推送 |
| 中断机制 | `os.kill(SIGINT)` | control 通道消息中断 + Iluvatar GPU 专用中断 |
| 代码补全 | 静态 AST lint | IPython jedi 运行时补全 |
| 富媒体 | 仅 matplotlib + HTML | MIME 协议（widgets/Plotly/LaTeX/进度条等） |
| GPU 集成 | 无 | 自定义 IluvatarProvisioner |

---

## 2. 里程碑总览

```
Week 0        Week 1-2        Week 2-3        Week 3-4        Week 4-5
   |              |               |               |               |
  P0             P1              P2              P3              P4+P5
概念验证     核心执行替换     前端流式适配    补全/内省/富媒体   GPU Prov. + 灰度
```

| 里程碑 | 名称 | 工期 | 交付物 | 准入标准 |
|--------|------|------|--------|---------|
| M0 | 概念验证 | 2-3 天 | POC 原型 | Flask 中启动 ipykernel 并通过 SSE 推送流式输出，`/api/run_cell_stream` 可用 |
| M1 | 核心执行替换 | 5-7 天 | 新版 `kernel_routes.py` | 替换 `exec()` 为 ipykernel，保持现有 API 兼容，流式输出可用 |
| M2 | 前端流式适配 | 5-7 天 | 新版前端 JS | 前端 SSE 接收流式输出，display_data 消息处理，status 状态同步 |
| M3 | 补全与内省 | 3-4 天 | 补全 API | Tab 补全、`?`/`??` 内省、`%` Magics 全部可用 |
| M4 | GPU 集成与富媒体 | 8-12 天 | IluvatarProvisioner + 富媒体渲染 | GPU 资源分配/中断正常，ipywidgets/tqdm/Plotly 可使用 |
| M5 | 灰度发布与稳定 | 持续 | 生产就绪版本 | 双轨运行 1 周无 P0 问题，用户反馈正向 |

**总工期：约 3-5 周核心迁移 + 1-2 周灰度发布。**

---

## 3. 详细阶段计划

### 3.1 P0：概念验证（2-3 天）

**目标**：验证 jupyter_client + ipykernel 在 Flask 环境中的可行性，确认流式输出体验。

**工作项**：

| 任务 | 预估工时 | 责任人 | 描述 |
|------|---------|--------|------|
| 环境搭建 | 2h | 后端 | 在开发环境安装 `jupyter_client`、`ipykernel`、`pyzmq` |
| 内核启动 | 4h | 后端 | 在 Flask 中调用 `jupyter_client.start_new_kernel()` 启动 ipykernel |
| SSE 端点 | 6h | 后端 | 实现 `/api/run_cell_stream`，通过 IOPub 通道迭代消息，SSE 推送到前端 |
| 简单前端测试 | 4h | 前端 | 创建最小化测试页面，验证流式输出效果 |
| 中断测试 | 2h | 后端 | 验证 control 通道中断是否能中断长时间运行的代码 |

**交付物**：
- 可运行的 POC 分支
- `/api/run_cell_stream` SSE 端点
- 流式输出效果录屏

**准入标准**：
- `print()` 输出实时流式推送（非阻塞等待）
- `time.sleep()` 循环中输出可见逐行出现
- 中断功能可终止 `while True` 循环

---

### 3.2 P1：核心执行替换（5-7 天）

**目标**：将 `kernel_worker` 中的 `exec()` 替换为 ipykernel，保持现有 API 兼容。

**工作项**：

| 任务 | 预估工时 | 责任人 | 描述 |
|------|---------|--------|------|
| KernelManager 重构 | 8h | 后端 | 重写 `core/kernel.py`，用 `jupyter_client.KernelManager` 替换 `multiprocessing.Process` |
| 执行路由改造 | 8h | 后端 | 改造 `core/routes/kernel_routes.py`，`/api/run_cell` 改为 SSE 流式 |
| 中断路由改造 | 4h | 后端 | `/api/interrupt_kernel` 改用 `km.interrupt_kernel()` |
| 变量查看改造 | 4h | 后端 | `/api/get_variables` 改用 `kc.execute("%who")` 或 `inspect_request` |
| 状态查询改造 | 2h | 后端 | `/api/kernel_status` 改用 `kc.is_alive()` |
| 兼容性适配 | 8h | 后端 | 确保现有 API 响应格式不变，前端无需改动即可工作 |
| 单元测试 | 8h | 后端 | 覆盖 execute/interrupt/status/variables 核心路径 |
| 回归测试 | 4h | QA | 确保现有功能不受影响 |

**交付物**：
- 新版 `core/kernel.py`（封装 jupyter_client）
- 新版 `core/routes/kernel_routes.py`（SSE 流式）
- 兼容性适配层（保持旧 API 格式）
- 单元测试套件

**准入标准**：
- 所有现有 API 端点行为不变（向后兼容）
- 流式输出端点新增且可用
- 中断可靠性高于旧实现
- 单元测试覆盖率 > 80%

---

### 3.3 P2：前端流式适配（5-7 天）

**目标**：前端 API 层适配流式输出，处理 Jupyter 消息协议中的富媒体内容。

**工作项**：

| 任务 | 预估工时 | 责任人 | 描述 |
|------|---------|--------|------|
| SSE 客户端 | 4h | 前端 | 实现 `EventSource` 或 `fetch` + `ReadableStream` 接收流式输出 |
| 流式渲染 | 6h | 前端 | 输出区域逐行追加，支持 `\r` 进度条刷新（tqdm） |
| display_data 处理 | 8h | 前端 | 处理 MIME 类型优先级的富媒体渲染（image/png > text/html > text/plain） |
| 状态同步 | 4h | 前端 | 根据 `status` 消息（busy/idle）更新 UI 状态指示器 |
| 错误展示 | 4h | 前端 | 解析 `error` 消息中的 traceback，美化展示 |
| execute_result 处理 | 2h | 前端 | 展示 `Out[N]` 执行结果 |
| 兼容模式 | 4h | 前端 | 保留旧 API 调用方式作为 fallback |
| 前端测试 | 4h | 前端 | 手动测试各消息类型渲染效果 |

**交付物**：
- 新版前端 JS（SSE 适配层）
- 富媒体渲染组件（MIME 类型处理）
- 状态指示器组件

**准入标准**：
- 流式输出在 UI 中实时可见
- PNG 图片内联展示
- DataFrame HTML 表格正确渲染
- busy/idle 状态正确指示
- 错误 traceback 格式清晰

---

### 3.4 P3：补全、内省与富媒体（3-4 天）

**目标**：接入 IPython 的补全和内省能力，处理更多 MIME 类型。

**工作项**：

| 任务 | 预估工时 | 责任人 | 描述 |
|------|---------|--------|------|
| 补全端点 | 6h | 后端 | 实现 `/api/complete`，调用 `kc.complete(code, cursor_pos)` |
| 内省端点 | 4h | 后端 | 实现 `/api/inspect`，调用 `kc.inspect(code, cursor_pos, detail_level)` |
| 前端 Tab 补全 | 6h | 前端 | 前端补全弹窗，支持键盘选择 |
| 前端 ? 查看 | 4h | 前端 | 快捷键触发 `?variable` 文档查看 |
| Magics 适配 | 4h | 前后端 | 确保 `%timeit`、`%pip`、`%debug` 等正常工作 |
| 额外 MIME 类型 | 4h | 前端 | 支持 text/markdown、text/latex、application/javascript 等 |

**交付物**：
- `/api/complete` 端点文档
- `/api/inspect` 端点文档
- 前端补全弹窗组件

**准入标准**：
- `df.` 后按 Tab 显示 DataFrame 方法列表
- `?pd.DataFrame` 显示文档
- `%timeit` 在 Notebook 中正常工作
- `%pip install` 在 Notebook 中正常工作

---

### 3.5 P4：Iluvatar GPU Provisioner（3-5 天）

**目标**：创建自定义 KernelProvisioner，深度整合天数智芯 GPU 资源管理。

**工作项**：

| 任务 | 预估工时 | 责任人 | 描述 |
|------|---------|--------|------|
| IluvatarProvisioner 实现 | 8h | 后端 | 继承 `KernelProvisionerBase`，实现 pre_launch/launch_kernel/send_signal |
| GPU 环境注入 | 4h | 后端 | 设置 `IXUCA_VISIBLE_DEVICES`、`ILUVATAR_KERNEL_TYPE` 等环境变量 |
| GPU 中断 | 6h | 后端 | 实现 Iluvatar GPU 专用中断：先尝试 IXUDA 中断，再 fallback SIGINT |
| GPU 资源分配 | 8h | 后端 | 多 Notebook 核间的 GPU 分配与隔离策略 |
| kernel.json 配置 | 2h | 后端 | 编写 Iluvatar 专用内核描述文件 |
| 集成测试 | 4h | QA | 在 Iluvatar 硬件上验证 GPU 内核启动、执行、中断全流程 |

**交付物**：
- `core/iluvatar_provisioner.py`
- `kernel.json` 配置文件
- GPU 中断测试报告

**准入标准**：
- 内核启动时自动注入 Iluvatar SDK 环境变量
- `torch-iluvatar` 正常调用 GPU
- GPU 计算中的中断可在 3 秒内生效
- 多 Notebook 场景 GPU 资源不冲突

---

### 3.6 P5：灰度发布与稳定（持续）

**目标**：双轨运行新旧内核，逐步切换用户，收集反馈，修复问题。

**工作项**：

| 任务 | 预估工时 | 责任人 | 描述 |
|------|---------|--------|------|
| 双轨运行架构 | 4h | 后端 | 通过配置开关控制使用新旧内核 |
| 监控埋点 | 6h | 后端 | 添加内核启动时间、执行时间、中断延迟、错误率等指标 |
| 内部灰度 | 2 天 | 全团队 | 开发团队内部使用新内核，收集问题 |
| 小范围灰度 | 1 周 | 运维 | 5% 用户切换到新内核 |
| 全量切换 | 1 天 | 运维 | 切换所有用户到新内核 |
| 旧代码清理 | 2h | 后端 | 删除手写 `kernel_worker` 代码 |

**交付物**：
- 配置开关实现
- 监控仪表板
- 灰度发布报告

**准入标准**：
- 新内核错误率低于旧内核
- 中断成功率 > 99%
- 用户无感知切换
- 无 P0/P1 问题持续 1 周

---

## 4. 资源需求

| 角色 | 人数 | 投入时间 | 职责 |
|------|------|---------|------|
| 后端 Python 开发 | 1-2 人 | 全职 3-5 周 | 内核重构、Provisioner 开发、API 改造 |
| 前端 JS 开发 | 1 人 | 全职 2-3 周 | SSE 适配、富媒体渲染、补全 UI |
| QA / 测试 | 1 人（或开发兼任） | 兼职 | 集成测试、回归测试、GPU 硬件测试 |
| DevOps（可选） | 0.5 人 | 按需 | 依赖管理、Docker 环境、灰度发布 |

---

## 5. 风险与缓解

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| ipykernel Tornado 异步与 Flask 同步模型冲突 | 中 | 高 | 使用线程池隔离，或在 Flask 中运行 asyncio 事件循环 |
| 国产芯片 SDK 与 pyzmq 编译/运行兼容性 | 低 | 高 | P0 阶段验证，提前与天数智芯团队沟通 |
| 前端适配工作量超预期 | 中 | 中 | 优先保证流式输出核心体验，富媒体分阶段上线 |
| 性能回退（IPython 启动较慢） | 低 | 低 | 预热机制已有，可进一步优化 |

---

## 6. 关键决策点

| 决策点 | 时机 | 决策依据 |
|--------|------|---------|
| 是否继续迁移 | P0 完成后 | POC 流式输出体验是否满足预期 |
| 是否全量切换 | P4 完成后 | 灰度 1 周数据是否达标 |
| 是否自研 wrapper kernel | P1 完成后 | ipykernel 是否满足全部需求，是否需要更轻量级的 wrapper |

---

**文档版本**: v1.0  
**最后更新**: 2026-07-08  
**负责人**: 待指定