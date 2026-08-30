# Changelog

## 启动开关自动化（2026-08）

- **天数设备自动检测** — 新增 `core/startup_flags.py`（`core.state` import 时执行）：按 `ixuca-smi` → `ixsmi` 优先级探测天数 GPU（与 `core/iluvatar_provisioner` 同款 CLI 优先级），自动固化 `USE_ILUVATAR_PROVISIONER` 并把结果持久化到 `~/.Iluvatar-AI-Notebook/setting.json`（0600）
- **OpenAI SDK 强制启用** — 启动时 `USE_OPENAI_SDK` 自动置 `1`（openai 已是硬依赖），显式设 `0` 保留 requests 逃生门；`configure_logging` 提前至 `core.state` import 前，保证检测日志可见
- **测试** — 新增 `tests/unit/test_startup_flags.py`（探测优先级/回退/超时/落盘/逃生门）

## 设置面板 · 高级模式直编 LiteLLM 配置（2026-08）

- **单一配置真相源** — `~/.Iluvatar-AI-Notebook/litellm_config.yaml` 成为 LLM 配置唯一持久化文件；高级模式（CodeMirror）逐字编辑，文件缺失时展示按环境三件套生成的预览；`config.yaml` 用户配置快照退役（`core/user_config.py` 薄化为配置目录助手），`/api/get_config` 改从 `model_list` 首条目读取并回退环境种子
- **带回滚重启校验** — 高级模式保存 = 轻量 YAML 校验 → 逐字写入（0600）→ 重启代理 → 健康检查；失败自动恢复旧配置、重启还原路由，并把 `litellm_proxy.log` 尾部（ANSI 剥离，最后 40 行）作为错误摘要返回
- **手动接管** — 高级模式保存成功后创建标记 `litellm_config.manual`；接管中基础模式表单保存返回 409 `CONFIG_MANAGED_MANUALLY` 并引导至高级模式（前端自动切换视图），系统状态零影响
- **测试** — `test_litellm_manager.py` 扩展（回滚/首条目/标记）、`test_ai_config.py`、`test_config_file_routes.py` 重写，`test_user_config.py` 薄化

## 测试修复（2026-08）

- **图表捕获修复** — 内核启动时自动注入 `MPLBACKEND=module://matplotlib_inline.backend_inline`，避免无头环境下回退到 Agg 后端导致 `plt.show()` 不产生 `display_data`、仪表板图表捕获失效；`kernels/iluvatar_python/kernel.json` 同步内置该变量
- **文档补全** — 快速开始新增「天数智芯 GPU 环境」安装步骤（`pip install -e .` + kernelspec 安装），运行测试章节补充 `-m iluvatar` 硬件用例说明

## ReAct Agent 与结构化上下文（2026-08）

- **ReAct Agent** — AI Chat 升级为轻量 ReAct 代理，新增 `core/agent.py`（循环/双协议）、`core/tools.py`（6 个工具注册表）与 `/api/agent_call` SSE 端点；自动探测 LLM 是否支持 function calling，不支持时降级为文本 JSON 协议
- **OpenAI SDK 传输层** — LLM 传输层拆分至 `core/llm.py`：通过官方 `openai` SDK 调用 LiteLLM Proxy（base_url 归一化、超时/重试、错误分类），未安装则透明降级为原生 `requests`；`USE_OPENAI_SDK=0/1` 可强制开关
- **结构化上下文** — 新增 `core/context.py` 与 `/api/context`，将"全量灌入 Notebook 代码"替换为内核快照（变量表 + 最近 Out + 最近错误栈）；内核错误摘要由 `core/kernel.py` 记录
- **智能工具** — Agent 可执行代码单元（`run_cell`）、查变量表（`get_variables`）、列/读 Notebook（`list_files`/`read_nb`）、查 GPU（`gpu_status`）与内核状态（`kernel_status`）；前端 `main.js` 渲染工具调用过程
- **测试** — 新增 `tests/unit/test_agent.py`、`test_context.py`、`test_tools.py` 与 `tests/js/agent-stream.test.mjs`

## 里程碑 · P0–P4：内核迁移（2026-07）

- **P0 概念验证** — 在 Flask 中启动 ipykernel，实现 SSE 流式输出端点 `/api/run_cell_stream`，验证 ZMQ 五通道协议可行性
- **P1 核心执行替换** — 基于 jupyter_client + ipykernel 重写 `core/kernel.py`，替换旧 `exec()` + `multiprocessing.Queue` 实现；新增 watchdog 自动重启机制；后端 API 保持向后兼容
- **P2 前端流式适配** — 新增 `sse-client.js`（SSE 流式执行客户端）、`output-renderer.js`（Jupyter MIME 富媒体渲染）、`kernel-indicator.js`（内核状态指示器）；实现 tqdm `\r` 进度条刷新
- **P3 补全与内省** — 后端新增 `/api/complete` 和 `/api/inspect` 端点；前端新增 `completion.js`（Tab 补全弹窗）和 `inspect.js`（`?`/`??` 内省面板）；新增 E2E 测试套件
- **P4 Iluvatar GPU Provisioner** — 继承 `KernelProvisionerBase` 实现 `IluvatarProvisioner`，自动注入 IXUCA SDK 环境变量、GPU 设备分配、`ixuca-smi --kill-compute` 专用中断；`kernels/iluvatar_python/kernel.json` 内核描述文件；`pyproject.toml` entry point 注册

## 历史更新

- **无障碍优化** — 添加 ARIA 标签和无障碍属性，提升屏幕阅读器兼容性
- **CodeMirror 修复** — 修复焦点事件处理问题
- **完全本地化** — 移除所有 CDN 依赖，所有资源本地化部署
- **模块化重构** — 前端代码拆分为 API、State、Renderer 服务层
- **文件管理增强** — 支持 .ipynb 导入导出、执行历史跟踪、撤销删除
- **AI 集成** — 支持 LLM 流式响应和 AI 代码建议 UI

## 架构演进

- **ISSUE-007** — 后端模块化重构，引入 Blueprint 架构
- **ISSUE-009** — 结构化 JSON 错误处理
- **ISSUE-010** — 内核看门狗自动重启机制
