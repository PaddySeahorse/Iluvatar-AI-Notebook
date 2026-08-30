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
| **后端** | Python / FastAPI (ASGI 统一入口) + Flask 薄壳兼容 |
| **前端** | HTML5 + CSS3 + Vanilla JavaScript (无构建) |
| **运行时** | jupyter_client + ipykernel（ZMQ 五通道协议，持久化全局命名空间） |
| **AI 集成** | OpenAI SDK → LiteLLM Proxy（OpenAI 兼容网关，硬编码 `http://localhost:4000/v1`），requests 兜底 |
| **GPU 集成** | 天数智芯 IXUCA SDK + 自定义 KernelProvisioner |
| **图标 / 字体** | Font Awesome / Inter + Fira Code |

### 项目结构

```
.
├── app.py                 # 兼容薄壳：转发到 app_fastapi
├── app_fastapi.py         # FastAPI 统一入口：Notebook / + /api/* + Chainlit /agent
├── chainlit_app.py        # Chainlit 应用 target（mount_chainlit 加载）
├── core/                  # 后端核心逻辑
│   ├── kernel.py          # KernelManager（jupyter_client + ipykernel, watchdog）
│   ├── state.py           # 共享运行时状态（单例 app_state）
│   ├── context.py         # 结构化上下文构建器
│   ├── tools.py / agent.py# ReAct 工具与循环
│   ├── llm.py             # LLM 传输层（固定请求本地 LiteLLM Proxy）
│   ├── litellm_manager.py # 本地 LiteLLM Proxy 生命周期
│   ├── gpu.py / iluvatar_provisioner.py / utils.py
│   └── routes/            # APIRouter 路由层（litellm_routes catch-all 必须最后注册）
├── static/                # 前端（index.html + js/* + vendor/）
├── kernels/iluvatar_python/kernel.json
├── tests/unit|integration # pytest 套件
├── tests/js/              # Node --test 前端单测
├── e2e/                   # Playwright 端到端
├── pyproject.toml / pytest.ini / requirements.txt
└── CHANGELOG.md
```

---

## 🚀 快速开始

### 环境要求

- Python 3.8+ / pip
- 天数智芯 GPU 驱动（可选，用于 GPU 遥测）

### 安装依赖

```bash
pip install -r requirements.txt
pip install openai "litellm[proxy]"
```

> LLM 传输层固定请求本地 LiteLLM Proxy（`LITELLM_PROXY_URL` 默认 `http://localhost:4000`），代理再按设置面板保存的上游配置转发；启动时自动强制 `USE_OPENAI_SDK=1`（OpenAI SDK 传输），显式设 `0` 可回退 requests 兜底。

天数智芯 GPU 环境（可选）：

```bash
# 注册 Provisioner entry point
pip install -e . --no-deps
# 安装内核描述文件
jupyter kernelspec install kernels/iluvatar_python --prefix /usr/local
# 启动时自动经 ixuca-smi/ixsmi 探测天数 GPU 并切换 iluvatar_python 内核；
# 探测结果持久化到 ~/.Iluvatar-AI-Notebook/setting.json，也可显式覆盖：
# USE_ILUVATAR_PROVISIONER=true python app_fastapi.py
python app_fastapi.py
```

开发工具（可选）：`pip install black isort mypy flake8`

### 配置

环境变量首次启动自动种子化至 `~/.Iluvatar-AI-Notebook/config.yaml`（0600）：

```env
OPENI_API_URL=https://token.openi.org.cn/v1/chat/completions
OPENI_API_TOKEN=your_api_token_here
OPENI_API_MODEL=dsv4
# 可选
# LITELLM_PROXY_URL=http://localhost:4000
# ALLOWED_ORIGINS=http://127.0.0.1:5000,http://localhost:5000
```

也可启动后在 UI 右上角「设置」面板填写上游模型 API 配置（Base URL / API Key / 模型名），保存后写入 `config.yaml` 与 `litellm_config.yaml` 并热重启代理，无需重启服务。

聊天历史（`/agent`）通过 Chainlit Data Layer 持久化到 `~/.Iluvatar-AI-Notebook/chat_history.db`（SQLite + aiosqlite/sqlalchemy，`@cl.data_layer` 自动建表），刷新或重启后侧边栏仍可见历史线程并可点开恢复；`@cl.on_chat_resume` 会把旧线程的 user/assistant 消息重建为 `cl.user_session["history"]` 供 ReAct agent 多轮上下文使用。依赖已写入 `requirements.txt`/`pyproject.toml`：`aiosqlite`、`sqlalchemy`、`greenlet`。

### 启动

> **约束**：启动文件必须是 Python；用户仅能访问 `OPENI_SELF_PORT` 指定的端口（默认 5000），不要绑定其他端口，API 通过同进程 `/api/*` 代理。

```bash
# FastAPI 统一入口（单 uvicorn 进程同时提供 Notebook + Chainlit）
python app_fastapi.py
# 等价
uvicorn app_fastapi:app --host 0.0.0.0 --port 5000
# Flask 薄壳仍可用
python app.py
```

访问：`http://127.0.0.1:5000/`（Notebook）· `http://127.0.0.1:5000/agent/`（Chainlit，`/agent` 307 重定向到 `/agent/`）

### 使用指南

- **Notebook**：`+ Cell` / `+ Markdown` 添加单元，▶ 运行，双击 Markdown 编辑，悬停移动/删除；`!` 前缀执行 shell，中断按钮走 control 通道
- **文件**：侧边栏创建/打开/保存/重命名/删除 `.ipynb`
- **AI**：单元底部 Copilot 输入框生成代码，错误时 `🔧 AI Debug`；右侧 ReAct Chat 可执行代码/查变量/GPU/文件，流式展示工具调用
- **变量**：底部面板实时显示内核变量（名/类型/值/形状）
- **示例**：启动默认含 Welcome Markdown + NumPy/Matplotlib 正弦衰减曲线演示

### 运行测试

```bash
pytest -m "not iluvatar"
pytest -m iluvatar  # 需 IXUCA 硬件 + kernelspec 已安装
node --test tests/js/completion.test.mjs
node --test tests/js/inspect.test.mjs
node --test tests/js/sse-client.test.mjs
node --test tests/js/kernel-indicator.test.mjs
node --test tests/js/output-renderer.test.mjs
python app_fastapi.py & npx playwright test e2e/p2-streaming.spec.mjs
```

---

## 📡 API 端点

### 核心功能

| 端点 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/` | GET | 主页面 |
| `/api/get_config` | GET | 获取默认 API 配置 |
| `/api/save_config` | POST | 持久化 LLM 配置至 `~/.Iluvatar-AI-Notebook/config.yaml` 并同步代理 |
| `/api/run_cell` | POST | 同步执行 Python 代码 |
| `/api/run_cell_stream` | POST | 流式执行（SSE 推送 stdout/stderr/富媒体） |
| `/api/interrupt_kernel` | POST | 中断执行（control 通道 + GPU 专用中断） |
| `/api/kernel_status` | GET | 内核与 watchdog 状态 |
| `/api/lint_cell` | POST | 静态检查（AST） |
| `/api/get_variables` | GET | 内核变量列表 |
| `/api/complete` | POST | 代码补全（jedi） |
| `/api/inspect` | POST | 对象内省 `?`/`??` |

### GPU 与 AI

| 端点 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/api/gpu_status` | GET | GPU 遥测 |
| `/api/ai_call` | POST | 代理 LLM 调用（流式/非流式） |
| `/api/context` | GET | 内核结构化上下文（变量表 + 最近 Out + 错误摘要） |
| `/api/agent_call` | POST | ReAct Agent（SSE 流式） |

### 文件管理

| 端点 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/api/files/list` | GET | 列出 `.ipynb` |
| `/api/files/read?filename=` | GET | 读取文件 |
| `/api/files/save` | POST | 保存 |
| `/api/files/create` | POST | 创建 |
| `/api/files/rename` | POST | 重命名 |
| `/api/files/delete` | POST | 删除 |

### 示例

**`/api/run_cell` 同步**

```json
// 请求
{"code": "print('Hello, World!')"}
// 响应
{"stdout": "Hello, World!\n", "stderr": "", "elapsed_time": 0.012, "plots": [], "error": null}
```

**`/api/run_cell_stream` SSE**

```
data: {"type":"stream","name":"stdout","text":"Hello, World!\n"}
data: {"type":"status","execution_state":"idle"}
data: [DONE]
```

**`/api/complete` / `/api/inspect` / `/api/ai_call`** 详见原文档，请求格式分别为 `{"code","cursor_pos"}` / `{"code","cursor_pos","detail_level"}` / `{"url","token","model","messages","stream"}`。

---

更新日志见 [CHANGELOG.md](CHANGELOG.md) · 许可证 MIT（[LICENSE](LICENSE)）
