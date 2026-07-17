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
| **AI 集成** | OpenAI 兼容 API（支持 DeepSeek 等模型） |
| **GPU 集成** | 天数智芯 IXUCA SDK + 自定义 KernelProvisioner |
| **图标** | Font Awesome |
| **字体** | Inter + Fira Code |

---

## 📁 项目结构

```
.
├── app.py                 # 入口点：配置加载、运行时状态、Blueprint 装配与启动
├── core/                  # 后端核心逻辑（模块化，ISSUE-007 refactor）
│   ├── __init__.py
│   ├── errors.py          # 自定义异常层次（AppError / KernelError / FileStorageError / UpstreamAPIError）
│   ├── kernel.py          # KernelManager — 基于 jupyter_client + ipykernel 的内核管理（含 watchdog）
│   ├── gpu.py             # 天数智芯 GPU 遥测（pynvml / IXUCA SDK）
│   ├── iluvatar_provisioner.py  # 自定义 KernelProvisioner，GPU 资源分配与专用中断
│   ├── utils.py           # 通用工具（is_safe_path 路径校验）
│   └── routes/            # Flask Blueprint 路由层
│       ├── __init__.py    # 路由与错误处理器注册
│       ├── static_routes.py   # 静态资源与首页
│       ├── gpu_routes.py      # GPU 状态
│       ├── kernel_routes.py   # 代码执行 / 流式 SSE / 中断 / 补全 / 内省 / 变量
│       ├── ai_routes.py       # API 配置与 AI 代理调用（流式 + 非流式）
│       ├── lint_routes.py     # 静态代码检查（AST 分析）
│       └── file_routes.py     # Notebook 文件管理
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

在项目根目录创建 `.env` 文件，配置以下环境变量：

```env
OPENI_API_URL=https://token.openi.org.cn/v1/chat/completions
OPENI_API_TOKEN=your_api_token_here
OPENI_API_MODEL=dsv4
```

也可以在启动后通过 UI 设置面板配置。

如需限制跨域来源，可额外配置：

```env
ALLOWED_ORIGINS=http://127.0.0.1:5000,http://localhost:5000
```

### 启动

```bash
python app.py
```

访问 `http://127.0.0.1:5000` 即可使用。

### 运行测试

```bash
# Python 后端测试（单元 + 集成）
pytest

# 前端逻辑测试（Node.js）
node tests/js/completion.test.mjs
node tests/js/inspect.test.mjs
node tests/js/sse-client.test.mjs
node tests/js/kernel-indicator.test.mjs
node tests/js/output-renderer.test.mjs

# 端到端测试（Playwright，需先启动 Flask 服务）
python app.py &
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
- **Chat**：右侧对话面板进行自由问答，可勾选「附加 Notebook 上下文」，支持流式输出
- **代码检查**：代码单元输入时自动进行静态分析，标记语法错误和未定义变量

### 变量查看器

- 底部面板实时显示当前内核中所有用户定义的变量
- 包含变量名、类型、值和形状（如适用）信息

---

## 📋 更新日志

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
