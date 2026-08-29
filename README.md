# Iluvatar AI Notebook · 天数智芯智能笔记本

> 面向国产 AI 芯片（天数智芯 Iluvatar）的 AI 辅助 Notebook 开发环境，融合交互式编程与 AI Copilot 能力，在浏览器中即可完成 Python 开发、数据可视化和智能辅助编码。

---

## ✨ 功能特性

- **交互式 Notebook** — 支持 Python 代码单元和 Markdown 文本单元的添加、编辑与执行
- **文件管理** — 支持 Notebook 的多文件创建、打开、保存、重命名和删除（`.ipynb` 格式持久化至磁盘）
- **子进程 Python 内核** — 独立进程执行用户代码，持久化全局命名空间，支持 `!shell` 命令
- **实时代码检查** — 静态分析代码单元，检测语法错误和未定义变量
- **变量查看器** — 实时展示内核命名空间中所有用户定义的变量及类型信息
- **实时 GPU 遥测** — 顶部仪表板实时展示天数智芯 GPU 的使用率、显存、温度、功耗等关键指标（通过 pynvml 获取真实硬件数据）
- **AI Copilot** — 代码单元内嵌 AI 输入框，一键生成代码；运行错误时可一键 AI 诊断
- **AI Chat 助手** — 右侧对话面板支持流式输出，可选择携带 Notebook 全部上下文
- **ReAct Agent 助手** — AI Chat 升级为轻量 ReAct 代理：可调用工具执行内核代码单元、查询变量表与 GPU 状态、列出/读取 Notebook 文件，再基于工具结果作答；自动探测 LLM 是否支持 function calling，不支持时降级为文本 JSON 协议
- **结构化上下文** — 将"全量灌入 Notebook 代码"替换为紧凑的内核快照（活动变量表 + 最近 Out 结果 + 最近错误栈摘要），更省 token 且直指运行时状态
- **暗色/亮色主题** — 一键切换，适配不同使用场景
- **图表捕获** — 自动捕获 Matplotlib 生成的图表并以 Base64 形式内嵌展示
- **内核中断** — 通过 jupyter_client control 通道中断，即使 GPU 算子阻塞 shell 也能生效；天数智芯 GPU 还能用 `ixuca-smi --kill-compute` 专用中断
- **流式输出** — 代码执行过程通过 SSE 实时推送 stdout/stderr，AI 训练过程逐行可见，支持 tqdm `\r` 进度条刷新
- **富媒体渲染** — 按 MIME 优先级渲染 Jupyter display_data（PNG/HTML/SVG/Markdown/LaTeX/plain）
- **Tab 代码补全** — 基于 IPython jedi 的运行时补全，输入 `df.` 后按 Tab 弹出方法列表
- **对象内省** — `?` 查看文档、`??` 查看源码，通过 `/api/inspect` 端点实现
- **内核状态指示器** — 顶部实时显示 busy/idle/disconnected/error 状态
- **Iluvatar GPU Provisioner** — 自定义 KernelProvisioner，启动时自动注入 IXUCA SDK 环境变量并分配 GPU 设备

---

## 🛠️ 技术栈

| 层 | 技术 |
| :--- | :--- |
| **后端** | Python / Flask |
| **前端** | HTML5 + CSS3 + Vanilla JavaScript |
| **运行时** | jupyter_client + ipykernel（ZMQ 五通道协议，持久化全局命名空间） |
| **AI 集成** | OpenAI SDK → LiteLLM Proxy（OpenAI 兼容网关），requests 兜底 |
| **GPU 集成** | 天数智芯 IXUCA SDK + 自定义 KernelProvisioner |
| **图标** | Font Awesome |
| **字体** | Inter + Fira Code |

---

## 📁 项目结构

```
.
├── app.py                 # 兼容薄壳：python app.py / uvicorn app:app 仍可用（转发到 app_fastapi）
├── app_fastapi.py         # FastAPI (ASGI) 统一入口（方案三）：Notebook /api/* + Chainlit /agent
├── chainlit_app.py        # Chainlit 应用 target（mount_chainlit 加载），复用 core.agent / core.tools
├── core/                  # 后端核心逻辑（模块化，ISSUE-007 refactor）
│   ├── __init__.py
│   ├── errors.py          # 自定义异常层次（AppError / KernelError / FileStorageError / UpstreamAPIError）
│   ├── kernel.py          # KernelManager — 基于 jupyter_client + ipykernel 的内核管理（含 watchdog + 错误记录）
│   ├── state.py           # 共享运行时状态（kernel_manager / WORKSPACE_DIR / LLM 默认值），FastAPI 与 Chainlit 共用
│   ├── context.py         # 结构化上下文构建器（变量表 / 最近 Out / 最近错误栈）
│   ├── tools.py           # ReAct Agent 工具注册表与执行（run_cell / 变量 / 文件 / GPU / 内核状态）
│   ├── agent.py           # 轻量 ReAct 循环（function calling + 文本 JSON 双协议）
│   ├── llm.py             # LLM 传输层：OpenAI SDK / requests 固定请求本地 LiteLLM Proxy
│   ├── litellm_manager.py # 本地 LiteLLM Proxy 生命周期管理（自启动/配置路由/重启/停止）
│   ├── gpu.py             # 天数智芯 GPU 遥测（pynvml / IXUCA SDK）
│   ├── iluvatar_provisioner.py  # 自定义 KernelProvisioner，GPU 资源分配与专用中断
│   ├── utils.py           # 通用工具（is_safe_path 路径校验）
│   └── routes/            # FastAPI APIRouter 路由层
│       ├── __init__.py    # 路由与错误处理器注册（state / json_body 辅助）
│       ├── static_routes.py   # 静态资源与首页
│       ├── gpu_routes.py      # GPU 状态
│       ├── kernel_routes.py   # 代码执行 / 流式 SSE / 中断 / 补全 / 内省 / 变量
│       ├── ai_routes.py       # API 配置与 AI 代理调用（流式 + 非流式）
│       ├── agent_routes.py    # ReAct Agent 调用（/api/agent_call）与结构化上下文（/api/context）
│       ├── lint_routes.py     # 静态代码检查（AST 分析）
│       ├── file_routes.py     # Notebook 文件管理
│       ├── metrics_routes.py  # /api/metrics 与 Prometheus 文本格式
│       └── litellm_routes.py  # LiteLLM Proxy 反向代理（catch-all，独占末尾）
├── public/               # Chainlit 自定义样式与脚本（/agent 页嵌入 Notebook iframe）
├── .chainlit/            # Chainlit 运行时配置（config.toml）
├── chainlit.md           # Chainlit 欢迎页说明（/agent 主页文案）
├── kernels/
│   └── iluvatar_python/
│       └── kernel.json    # 天数智芯专用内核描述文件
├── static/
│   ├── index.html         # 前端主页面
│   ├── style.css          # 样式表
│   ├── js/
│   │   ├── api.js         # API 通信层
│   │   ├── state.js       # 状态管理
│   │   ├── renderer.js    # UI 渲染逻辑
│   │   ├── main.js        # 主入口与事件绑定
│   │   ├── sse-client.js  # SSE 流式执行客户端
│   │   ├── output-renderer.js  # Jupyter MIME 富媒体渲染
│   │   ├── kernel-indicator.js # 内核状态指示器
│   │   ├── completion.js  # Tab 代码补全弹窗
│   │   └── inspect.js     # ?/?? 对象内省面板
│   └── vendor/            # 本地化第三方资源
│       ├── font-awesome/  # Font Awesome 图标库
│       ├── fonts/         # Inter + Fira Code 字体
│       └── codemirror/    # CodeMirror 代码编辑器
├── tests/
│   ├── test_app.py        # pytest 测试套件
│   ├── unit/              # 单元测试（KernelManager / Provisioner / 路由）
│   ├── integration/       # 集成测试（内核 + 路由 + Provisioner 硬件）
│   └── js/                # Node.js 前端逻辑测试（completion / inspect / SSE / indicator）
├── e2e/                   # 端到端 Playwright 测试
│   ├── p2-streaming.spec.mjs        # P2 流式输出场景
│   └── p3-completion-inspect.spec.mjs  # P3 补全 & 内省场景
├── docs/                  # 项目文档
│   ├── adr/               # 架构决策记录
│   ├── design/            # 设计文档
│   ├── plan/              # 开发计划
│   └── roadmap/           # 路线图
├── pyproject.toml         # 项目元数据 & Provisioner entry point 注册
├── pytest.ini             # pytest 配置
├── .gitignore
└── README.md
```

---

## 🚀 快速开始

### 环境要求

- Python 3.8+
- pip
- 天数智芯 GPU 驱动（可选，用于 GPU 遥测功能）

### 安装依赖

```bash
pip install flask flask-cors matplotlib requests pynvml pytest
```

> **LLM 传输层 — OpenAI SDK → 自托管 LiteLLM Proxy**：请求地址在代码中**写死为本地 LiteLLM Proxy**（`http://localhost:4000/v1`，可通过 `LITELLM_PROXY_URL` 覆盖）。应用启动时自动拉起 Proxy（`pip install "litellm[proxy]"`），它再根据设置面板保存的**上游模型 API 配置**把请求转发给真实模型；代理接管超时、重试与限流/鉴权错误分类。未安装 `openai` 包时透明降级为原生 `requests` 直连同一本地代理。
>
> ```bash
> pip install openai "litellm[proxy]"
> ```
>
> 可用 `USE_OPENAI_SDK=0` 强制禁用（`USE_OPENAI_SDK=1` 强制启用；不设置时自动检测）。

### 天数智芯 GPU 环境（可选）

在装有 IXUCA SDK 的天数智芯服务器上，可启用 GPU 专用内核与 Provisioner：

```bash
# 1. 注册 IluvatarProvisioner entry point
pip install -e . --no-deps

# 2. 安装 iluvatar_python 内核描述文件
jupyter kernelspec install kernels/iluvatar_python --prefix /usr/local

# 3. 启动时开启 Provisioner
USE_ILUVATAR_PROVISIONER=true python app_fastapi.py
```

Provisioner 会在内核启动时自动注入 `IXUCA_VISIBLE_DEVICES` 等环境变量并分配 GPU 设备，中断时优先使用 `ixuca-smi --kill-compute` GPU 专用中断。

### 开发环境配置

如需参与开发，建议安装以下工具：

```bash
# 代码格式化
pip install black isort

# 类型检查
pip install mypy

# 代码检查
pip install flake8
```

### 配置（可选）

通过环境变量预设以下配置（首次启动时会作为种子写入 `~/.Iluvatar-AI-Notebook/config.yaml`）：

```env
# 上游模型提供方的 OpenAI 兼容端点（供本地 LiteLLM Proxy 路由）
OPENI_API_URL=https://token.openi.org.cn/v1/chat/completions
OPENI_API_TOKEN=your_api_token_here
OPENI_API_MODEL=dsv4

# 可选：本地 LiteLLM Proxy 地址（OpenAI SDK 固定请求此地址）
# LITELLM_PROXY_URL=http://localhost:4000
```

也可以在启动后通过 **UI 设置面板**配置（右上角「设置」）：
填写**上游模型 API 配置**（真实模型提供方的 Base URL / API Key / 模型名）后点击「保存」，配置会**自动写入宿主机用户目录的 `~/.Iluvatar-AI-Notebook/config.yaml`**（同时同步运行时默认值，无需重启）并**写入本地 LiteLLM Proxy 的路由配置、立即生效**，且保存在浏览器 localStorage；下次启动时自动从该文件恢复并自启动 LiteLLM Proxy。OpenAI SDK 始终请求 `http://localhost:4000/v1`，设置面板内嵌 **LiteLLM Proxy 原生管理台**入口（新窗口打开 / 页内预览，同源 `<origin>/ui/`），可在其中管理模型路由、虚拟密钥与用量。

如需限制跨域来源，可额外配置：

```env
ALLOWED_ORIGINS=http://127.0.0.1:5000,http://localhost:5000
```

### 启动

方案三为**单进程统一入口**：一个 uvicorn 进程同时提供 Notebook 与 Chainlit Agent。

```bash
# 启动 FastAPI 统一入口（Notebook / + /api/* + Chainlit /agent）
# 应用启动时自动拉起本地 LiteLLM Proxy（localhost:4000；首次启动需已在上游配置里保存过模型路由）
python app_fastapi.py

# 等价于上面的 uvicorn 命令
uvicorn app_fastapi:app --host 0.0.0.0 --port 5000

# Flask 薄壳仍然可用（转发到 app_fastapi，效果相同）
python app.py
```

访问：

- `http://127.0.0.1:5000/` —— Notebook 主界面（原有全部 API 路径不变）
- `http://127.0.0.1:5000/agent` —— Chainlit Agent 聊天界面（左侧自动嵌入 Notebook，两者共享同一内核与变量）

> 说明：Chainlit 挂载在 `/agent` 子路径（`chainlit.utils.mount_chainlit`），
> `/agent` 会自动 307 重定向到 `/agent/`。`OPENI_SELF_PORT` 默认 5000。

### 运行测试

```bash
# Python 后端测试（单元 + 集成，自动跳过需要 GPU 硬件的用例）
pytest -m "not iluvatar"

# 天数智芯硬件集成测试（需先完成上方「天数智芯 GPU 环境」两步安装）
pytest -m iluvatar

# 前端逻辑测试（Node.js）
node tests/js/completion.test.mjs
node tests/js/inspect.test.mjs
node tests/js/sse-client.test.mjs
node tests/js/kernel-indicator.test.mjs
node tests/js/output-renderer.test.mjs

# 端到端测试（Playwright，需先启动 FastAPI 服务）
python app_fastapi.py &
npx playwright test e2e/p2-streaming.spec.mjs
npx playwright test e2e/p3-completion-inspect.spec.mjs
```

---

## 📡 API 端点

### 核心功能

| 端点 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/` | GET | 主页面 |
| `/api/get_config` | GET | 获取默认 API 配置 |
| `/api/save_config` | POST | 持久化 LLM API 配置（Url/Token/Model）至 `~/.Iluvatar-AI-Notebook/config.yaml` 并同步运行时默认值 |
| `/api/run_cell` | POST | 同步执行 Python 代码（兼容旧 API 格式） |
| `/api/run_cell_stream` | POST | 流式执行代码，通过 SSE 实时推送 stdout/stderr/富媒体（P2 新增） |
| `/api/interrupt_kernel` | POST | 中断当前代码执行（control 通道 + GPU 专用中断） |
| `/api/kernel_status` | GET | 获取内核与 watchdog 存活状态 |
| `/api/lint_cell` | POST | 静态分析代码（语法错误 / 未定义变量） |
| `/api/get_variables` | GET | 获取内核命名空间中的变量列表 |
| `/api/complete` | POST | 代码补全（基于 IPython jedi，P3 新增） |
| `/api/inspect` | POST | 对象内省 `?`/`??` 文档查看（P3 新增） |

### GPU 与 AI

| 端点 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/api/gpu_status` | GET | 获取 GPU 实时遥测数据（利用率、显存、温度、功耗） |
| `/api/ai_call` | POST | 代理调用 LLM API（支持流式与非流式） |
| `/api/context` | GET | 获取内核结构化上下文（变量表 + 最近 Out + 最近错误摘要） |
| `/api/agent_call` | POST | 运行 ReAct Agent，SSE 流式返回工具调用/结果与最终回答 |

### 文件管理

| 端点 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/api/files/list` | GET | 列出所有 `.ipynb` 文件 |
| `/api/files/read?filename=` | GET | 读取指定 `.ipynb` 文件 |
| `/api/files/save` | POST | 保存 Notebook 至磁盘 |
| `/api/files/create` | POST | 创建新的 `.ipynb` 文件 |
| `/api/files/rename` | POST | 重命名 `.ipynb` 文件 |
| `/api/files/delete` | POST | 删除 `.ipynb` 文件 |

### `/api/run_cell`（同步）

请求体：

```json
{
  "code": "print('Hello, World!')"
}
```

响应：

```json
{
  "stdout": "Hello, World!\n",
  "stderr": "",
  "elapsed_time": 0.012,
  "plots": [],
  "error": null
}
```

### `/api/run_cell_stream`（流式 SSE）

请求体同 `/api/run_cell`，响应为 `text/event-stream`，每条消息格式：

```
data: {"type":"stream","name":"stdout","text":"Hello, World!\n"}

data: {"type":"status","execution_state":"idle"}

data: [DONE]
```

消息类型：`stream`（stdout/stderr）、`display_data`（富媒体）、`execute_result`（`Out[N]`）、`error`（traceback）、`status`（busy/idle）、`execute_input`。

### `/api/complete`（代码补全）

请求体：

```json
{
  "code": "import pandas as pd; pd.D",
  "cursor_pos": 27
}
```

响应：

```json
{
  "matches": ["DataFrame", "DataFrameGroupBy", "DataFrameGroupBy._generate_metadata"],
  "cursor_start": 25,
  "cursor_end": 27,
  "metadata": {}
}
```

### `/api/inspect`（对象内省）

请求体：

```json
{
  "code": "pd.DataFrame",
  "cursor_pos": 11,
  "detail_level": 0
}
```

响应：

```json
{
  "found": true,
  "data": {
    "text/plain": "Signature: pd.DataFrame(...)\nDocstring:\nTwo-dimensional, size-mutable, ..."
  },
  "metadata": {}
}
```

### `/api/ai_call`

请求体：

```json
{
  "url": "https://token.openi.org.cn/v1/chat/completions",
  "token": "your_token",
  "model": "dsv4",
  "messages": [
    { "role": "user", "content": "写一个快速排序" }
  ],
  "stream": false
}
```

---

## 🎮 使用指南

### Notebook 操作

- **添加代码单元**：点击「+ Cell」按钮
- **添加 Markdown 单元**：点击「+ Markdown」按钮  
- **运行代码**：点击代码单元左侧的 ▶ 运行按钮
- **编辑 Markdown**：双击 Markdown 单元进入编辑，点击外部自动渲染
- **移动/删除单元**：悬停单元格后使用工具栏按钮
- **Shell 命令**：在代码单元中以 `!` 开头执行系统命令（如 `!pip install numpy`）
- **中断执行**：长按运行按钮发送中断信号，终止长时间运行的代码

### 文件管理

- **多 Notebook**：通过文件管理面板创建、打开、保存、重命名和删除 `.ipynb` 文件
- **持久化存储**：Notebook 内容保存为磁盘上的 `.ipynb` 文件，API 配置保存至 localStorage

### AI 辅助

- **Copilot**：代码单元底部的 AI 输入框，描述需求即可生成代码
- **Debug**：代码运行失败后，点击「🔧 AI Debug」自动分析错误
- **Chat（ReAct Agent）**：右侧对话面板进行自由问答，AI 可调用工具（执行代码、查 GPU/变量/文件）后作答，支持流式输出与工具调用过程展示
- **代码检查**：代码单元输入时自动进行静态分析，标记语法错误和未定义变量

### 变量查看器

- 底部面板实时显示当前内核中所有用户定义的变量
- 包含变量名、类型、值和形状（如适用）信息

---

## 📋 更新日志

### 测试修复（2026-08）

- **图表捕获修复** — 内核启动时自动注入 `MPLBACKEND=module://matplotlib_inline.backend_inline`，避免无头环境下回退到 Agg 后端导致 `plt.show()` 不产生 `display_data`、仪表板图表捕获失效；`kernels/iluvatar_python/kernel.json` 同步内置该变量
- **文档补全** — 快速开始新增「天数智芯 GPU 环境」安装步骤（`pip install -e .` + kernelspec 安装），运行测试章节补充 `-m iluvatar` 硬件用例说明

### ReAct Agent 与结构化上下文（2026-08）

- **ReAct Agent** — AI Chat 升级为轻量 ReAct 代理，新增 `core/agent.py`（循环/双协议）、`core/tools.py`（6 个工具注册表）与 `/api/agent_call` SSE 端点；自动探测 LLM 是否支持 function calling，不支持时降级为文本 JSON 协议
- **OpenAI SDK 传输层** — LLM 传输层拆分至 `core/llm.py`：通过官方 `openai` SDK 调用 LiteLLM Proxy（base_url 归一化、超时/重试、错误分类），未安装则透明降级为原生 `requests`；`USE_OPENAI_SDK=0/1` 可强制开关
- **结构化上下文** — 新增 `core/context.py` 与 `/api/context`，将"全量灌入 Notebook 代码"替换为内核快照（变量表 + 最近 Out + 最近错误栈）；内核错误摘要由 `core/kernel.py` 记录
- **智能工具** — Agent 可执行代码单元（`run_cell`）、查变量表（`get_variables`）、列/读 Notebook（`list_files`/`read_nb`）、查 GPU（`gpu_status`）与内核状态（`kernel_status`）；前端 `main.js` 渲染工具调用过程
- **测试** — 新增 `tests/unit/test_agent.py`、`test_context.py`、`test_tools.py` 与 `tests/js/agent-stream.test.mjs`

### 里程碑 · P0–P4：内核迁移（2026-07）

- **P0 概念验证** — 在 Flask 中启动 ipykernel，实现 SSE 流式输出端点 `/api/run_cell_stream`，验证 ZMQ 五通道协议可行性
- **P1 核心执行替换** — 基于 jupyter_client + ipykernel 重写 `core/kernel.py`，替换旧 `exec()` + `multiprocessing.Queue` 实现；新增 watchdog 自动重启机制；后端 API 保持向后兼容
- **P2 前端流式适配** — 新增 `sse-client.js`（SSE 流式执行客户端）、`output-renderer.js`（Jupyter MIME 富媒体渲染）、`kernel-indicator.js`（内核状态指示器）；实现 tqdm `\r` 进度条刷新
- **P3 补全与内省** — 后端新增 `/api/complete` 和 `/api/inspect` 端点；前端新增 `completion.js`（Tab 补全弹窗）和 `inspect.js`（`?`/`??` 内省面板）；新增 E2E 测试套件
- **P4 Iluvatar GPU Provisioner** — 继承 `KernelProvisionerBase` 实现 `IluvatarProvisioner`，自动注入 IXUCA SDK 环境变量、GPU 设备分配、`ixuca-smi --kill-compute` 专用中断；`kernels/iluvatar_python/kernel.json` 内核描述文件；`pyproject.toml` entry point 注册

### 历史更新

- **无障碍优化** — 添加 ARIA 标签和无障碍属性，提升屏幕阅读器兼容性
- **CodeMirror 修复** — 修复焦点事件处理问题
- **完全本地化** — 移除所有 CDN 依赖，所有资源本地化部署
- **模块化重构** — 前端代码拆分为 API、State、Renderer 服务层
- **文件管理增强** — 支持 .ipynb 导入导出、执行历史跟踪、撤销删除
- **AI 集成** — 支持 LLM 流式响应和 AI 代码建议 UI

### 架构演进

- **ISSUE-007** — 后端模块化重构，引入 Blueprint 架构
- **ISSUE-009** — 结构化 JSON 错误处理
- **ISSUE-010** — 内核看门狗自动重启机制

---

## 📝 示例

启动后，Notebook 默认包含两个示例单元：

1. **Welcome Markdown** — 项目介绍与快速引导
2. **示例代码** — 使用 NumPy + Matplotlib 绘制正弦衰减曲线，展示代码执行与图表捕获功能

---

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。
