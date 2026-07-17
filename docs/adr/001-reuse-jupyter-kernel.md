# ADR-001: 复用 Jupyter 内核生态库

> **架构决策记录（Architecture Decision Record）**
>
> 格式参考 Michael Nygard 的 ADR 模板。

---

## 元数据

| 字段 | 值 |
|------|-----|
| **ADR 编号** | 001 |
| **标题** | 复用 Jupyter 内核生态库（jupyter_client + ipykernel）替代手写 KernelManager |
| **状态** | 已实施（Implemented） |
| **日期** | 2026-07-08 |
| **决策者** | Iluvatar AI Notebook 核心团队 |
| **影响范围** | `core/kernel.py`、`core/routes/kernel_routes.py`、前端 API 层、依赖管理 |

---

## 1. 背景与问题陈述

### 1.1 当前状态

Iluvatar AI Notebook 当前使用手写的 `KernelManager`（`core/kernel.py`，约 250 行），基于 `multiprocessing.Queue` 进行 IPC 通信，通过裸 `exec()` 执行 Python 代码。该实现在原型阶段足够简洁，但随着项目向 AI-First 方向演进，暴露出多个架构层面的问题：

1. **输出是阻塞式的**：代码执行完毕才一次性返回 stdout/stderr/plots，无法实现 AI 训练过程的实时输出流；
2. **中断机制不可靠**：`os.kill(SIGINT)` 在子进程执行 C 扩展（如 GPU 算子）时无法生效；
3. **没有运行时代码补全**：仅具备静态 AST lint，无法提供 `df.` 后按 Tab 的方法列表；
4. **富媒体支持极其有限**：仅支持 matplotlib 图片和 `_repr_html_`，不支持 ipywidgets、Plotly、tqdm 进度条等；
5. **缺少 stdin 通道、Magics 支持、Debugger 协议、执行状态机**；
6. **继续手写意味着在重复发明一个 Jupyter 生态已解决 10 年的问题**。

### 1.2 决策触发因素

随着 AI Copilot 功能深入开发，需要内核提供：
- 实时流式输出（AI 代码生成后的执行反馈）
- 可靠的 GPU 计算中断（训练任务取消）
- 运行时补全和内省（AI 辅助编程）
- 富媒体展示（AI 生成的可视化组件）

这些需求在手写内核上实现成本极高，且难以达到 Jupyter 生态的成熟度。

---

## 2. 决策

**采用"三层解耦"策略，复用 Jupyter 核心库，但保持差异化层独立：**

- **执行层**：用 `ipykernel` 替代裸 `exec()`，获得 IPython 的完整能力（补全、内省、Magics、富媒体、调试）；
- **管理层**：用 `jupyter_client.KernelManager` 替代 `multiprocessing.Queue` 通信，获得 ZMQ 五通道协议（shell/iopub/control/stdin/hb）；
- **差异化层**：保留 Flask 后端 + Vanilla JS 前端 + AI Copilot + GPU 遥测，通过自定义 `KernelProvisioner` 深度整合天数智芯 Iluvatar 芯片资源管理。

**不复用**：`jupyter_server`（Tornado 依赖）、`jupyterlab` 前端（需保留 AI-First UX）。

### 2.1 新增依赖

| 依赖 | 大小 | 必要性 |
|------|------|--------|
| jupyter_client | ~400KB | 必须：内核管理与通信 |
| ipykernel | ~500KB | 必须：Python 内核执行引擎 |
| ipython | ~5MB | 必须：ipykernel 依赖 |
| pyzmq | ~3MB | 必须：jupyter_client 依赖 |
| tornado | ~1.5MB | 必须：ipykernel 依赖 |
| nbformat | ~200KB | 推荐：.ipynb 格式读写 |

**合计约 12-15 MB 新增依赖，对现有 GPU 计算栈（数百 MB）影响可忽略。**

---

## 3. 备选方案

### 3.1 方案 A：继续手写（不复用）

**描述**：在现有 `kernel_worker` 基础上逐个叠加功能（流式输出、中断、补全、富媒体等）。

**优点**：
- 无外部依赖引入
- 完全控制内核行为
- 代码量小，调试简单

**缺点**：
- 每个功能都需要从零实现，开发成本高，时间线长
- 质量难以达到 Jupyter 10 年打磨的成熟度
- 流式输出、GI 中断、复杂补全等功能的正确实现极其困难
- 每个功能都是"重新发明轮子"，且轮子质量不如现有轮子

### 3.2 方案 B：全面迁移到 Jupyter 生态

**描述**：将整个后端替换为 `jupyter_server`，前端使用 `jupyterlab` 或 `notebook v7`。

**优点**：
- 获得 Jupyter 生态的全部能力
- 维护成本最低（社区维护）

**缺点**：
- 失去产品差异化——AI Copilot、GPU 仪表板、Vanilla JS 前端需要重写
- 强依赖 Tornado 框架，与现有 Flask 架构冲突
- 产品身份丢失——"只是另一个 JupyterLab 定制版"
- 违背项目"颠覆性 AI-First Notebook"的定位

### 3.3 方案 C：分层复用（选定方案）

**描述**：仅复用执行层和管理层，保留差异化层。

**优点**：
- 获得 IPython 全部能力（补全、内省、Magics、富媒体、调试）
- 获得可靠的 ZMQ 通信协议（流式输出、正确中断、stdin 通道）
- 通过 KernelProvisioner 扩展点实现 GPU 定制
- 保留 Flask 架构和 AI Copilot 差异化
- 迁移成本可控（3-5 周核心迁移）
- 向后兼容现有 API

**缺点**：
- 引入约 12-15 MB 新依赖
- 团队需要学习 Jupyter 内核协议
- ipykernel 启动比裸 exec 慢约 1-2 秒（可通过预热解决）

---

## 4. 方案对比

| 维度 | 方案 A：继续手写 | 方案 B：全面迁移 | 方案 C：分层复用（选定） |
|------|-----------------|-----------------|------------------------|
| 流式输出 | 需自研，复杂度高 | 天然支持 | 天然支持 |
| 代码补全 | 需自研，难以达到 IPython 水平 | 天然支持 | 天然支持 |
| 中断可靠性 | SIGINT 在 GPU 场景不可靠 | 可靠，但无 GPU 定制 | 可靠 + Iluvatar GPU 专用中断 |
| 富媒体 | 逐一实现 MIME 类型 | 天然支持 | 天然支持 |
| AI Copilot 集成 | 自由度高 | 需适配 Jupyter 扩展 API | 自由度高（通过自定义扩展） |
| GPU 集成 | 自由度高 | 需适配 | 自由度高（Provisioner） |
| 产品差异化 | 完全保留 | 大幅折损 | 完全保留 |
| 开发成本 | 高（持续投入） | 中（前端重写） | 中（3-5 周核心迁移） |
| 维护成本 | 高（自研所有功能） | 低（社区维护） | 中（维护封装层 + Provisioner） |
| 生态兼容性 | 无 | 完全兼容 | 完全兼容（内核协议层面） |
| 架构复杂度 | 低（250 行） | 高（Tornado + Jupyter Server） | 中（新增封装层） |

---

## 5. 预期后果

### 5.1 正面后果

1. **即时获得 IPython 全部能力**：补全、内省（`?`/`??`）、Magics（`%timeit`、`%pip`、`%debug`）、富媒体（MIME 协议）、调试器（DAP）；
2. **流式输出体验**：SSE 推送实时 stdout/stderr，AI 训练过程可见；
3. **可靠的中断机制**：control 通道独立于 shell 通道，即使 GPU 计算阻塞 shell 也不影响中断；
4. **生态兼容性**：tqdm、ipywidgets、Plotly、Bokeh 等所有 Jupyter 生态库直接可用；
5. **GPU 深度整合**：通过自定义 Provisioner 实现 GPU 资源分配、环境注入、专用中断；
6. **向后兼容**：现有 API 响应格式不变，前端渐进适配。

### 5.2 负面后果

1. **新增约 12-15 MB 依赖**：对部署包大小有轻微影响，但相对于 GPU 计算栈可忽略；
2. **学习曲线**：团队需要理解 Jupyter 消息协议和 ZMQ 通信模型；
3. **启动时间增加**：ipykernel 启动比裸 exec 慢约 1-2 秒（可通过 warm_start 预热缓解）；
4. **抽象泄漏风险**：如果未来需要做 Jupyter 协议不支持的自定义操作，可能需要绕过封装层；
5. **版本兼容性**：需要跟踪 jupyter_client 和 ipykernel 的大版本更新，确保 Provisioner API 兼容。

### 5.3 中性后果

- 代码库中 `core/kernel.py` 从 250 行增加到约 400 行（封装层），但删除了手写的 `kernel_worker` 和 IPC 逻辑；
- 前端需要适配 SSE 流式输出，但获得了更好的用户体验。

---

## 6. 风险缓解

| 风险 | 缓解措施 |
|------|---------|
| jupyter_client 大版本 API 变更 | 封装在 `KernelManager` 类内部，仅暴露稳定接口；关注 Changelog |
| ipykernel 与 Iluvatar SDK 兼容性 | P0 阶段在 Iluvatar 硬件上验证；自定义 Provisioner 处理环境差异 |
| 团队对 ZMQ 协议不熟悉 | 编写内部文档 + 知识分享；KernelManager 封装层隔离 ZMQ 细节 |
| 性能回退 | 设置性能基准测试；预热机制 + 连接池优化 |
| "被 Jupyter 绑定"的担忧 | jupyter_client 是稳定的纯库（10 年+ 历史），仅依赖 KernelManager/KernelClient 两个核心类，耦合度极低 |

---

## 7. 迁移策略

采用**渐近式迁移**，而非"大爆炸式"重写：

1. **P0（2-3 天）**：概念验证 — Flask 中启动 ipykernel，实现 SSE 流式输出端点；
2. **P1（5-7 天）**：核心替换 — 改造 `kernel_routes.py`，保持 API 兼容；
3. **P2（5-7 天）**：前端适配 — SSE 流式接收 + 富媒体渲染；
4. **P3（3-4 天）**：补全和内省 — `/api/complete` + `/api/inspect` 端点；
5. **P4（3-5 天）**：Iluvatar Provisioner — GPU 资源管理 + 专用中断；
6. **P5（持续）**：灰度发布 — Feature Flag 控制，双轨运行，逐步切换。

**总工期：3-5 周核心迁移 + 1-2 周灰度发布。** 详细路线图见 [migration-roadmap.md](../roadmap/migration-roadmap.md)。

---

## 8. 参考资料

- [Jupyter Messaging Protocol v5.5](https://jupyter-client.readthedocs.io/en/stable/messaging.html) — ZMQ 消息协议规范
- [Jupyter Kernel Provisioning](https://jupyter-client.readthedocs.io/en/stable/provisioning.html) — Provisioner API 文档
- [Iluvatar-AI-Notebook](https://github.com/PaddySeahorse/Iluvatar-AI-Notebook) — 项目源码
- [天数智芯天垓 150 GPU 软硬件生态](https://ai.gitee.com/docs/compute/clusters_gpu/iluvatar/iluvatar_BI-V150_gpu) — Iluvatar SDK 文档
- [核心分析报告](../../iluvatar-kernel-analysis.html) — 完整技术分析

---

## 9. 变更历史

| 日期 | 版本 | 变更 | 作者 |
|------|------|------|------|
| 2026-07-08 | v1.0 | 初始版本（Proposed） | 待指定 |
| 2026-07-17 | v1.1 | P0–P4 实施完成，状态更新为 Implemented | AtomCode |

---

**ADR 状态流转**：提议中（Proposed）→ 已接受（Accepted）→ 已实施（Implemented）→ 已废弃（Deprecated）→ 已替代（Superseded）