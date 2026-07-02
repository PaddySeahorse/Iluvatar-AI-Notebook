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
- **内核中断** — 支持中断长时间运行的代码执行

---

## 🛠️ 技术栈

| 层 | 技术 |
| :--- | :--- |
| **后端** | Python / Flask |
| **前端** | HTML5 + CSS3 + Vanilla JavaScript |
| **运行时** | Python 3 内核（exec 模式，持久化全局命名空间） |
| **AI 集成** | OpenAI 兼容 API（支持 DeepSeek 等模型） |
| **图标** | Font Awesome |
| **字体** | Inter + Fira Code |

---

## 📁 项目结构

```
.
├── app.py              # 入口点：配置加载、运行时状态、Blueprint 装配与启动
├── core/               # 后端核心逻辑（模块化，ISSUE-007）
│   ├── __init__.py
│   ├── errors.py       # 自定义异常层次（AppError / KernelError / FileStorageError / UpstreamAPIError）
│   ├── kernel.py       # KernelManager 内核管理 + kernel_worker 子进程执行器
│   ├── gpu.py          # pynvml GPU 遥测
│   ├── utils.py        # 通用工具（is_safe_path 路径校验）
│   └── routes/         # Flask Blueprint 路由层
│       ├── __init__.py           # 路由与错误处理器注册
│       ├── static_routes.py      # 静态资源与首页
│       ├── gpu_routes.py         # GPU 状态
│       ├── kernel_routes.py      # 代码执行 / 中断 / 内核状态 / 变量
│       ├── ai_routes.py          # API 配置与 AI 代理调用
│       ├── lint_routes.py        # 静态代码检查
│       └── file_routes.py        # Notebook 文件管理
├── static/
│   ├── index.html      # 前端主页面
│   ├── style.css       # 样式表
│   └── js/
│       ├── api.js      # API 通信层
│       ├── state.js    # 状态管理
│       ├── renderer.js # UI 渲染逻辑
│       └── main.js     # 主入口与事件绑定
├── tests/
│   └── test_app.py     # pytest 测试套件
└── README.md
```

---

## 🚀 快速开始

### 环境要求

- Python 3.8+
- pip

### 安装依赖

```bash
pip install flask flask-cors matplotlib requests pynvml pytest
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
pytest
```

---

## 📡 API 端点

### 核心功能

| 端点 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/` | GET | 主页面 |
| `/api/get_config` | GET | 获取默认 API 配置 |
| `/api/run_cell` | POST | 执行 Python 代码单元 |
| `/api/interrupt_kernel` | POST | 中断当前代码执行 |
| `/api/lint_cell` | POST | 静态分析代码（语法错误 / 未定义变量） |
| `/api/get_variables` | GET | 获取内核命名空间中的变量列表 |

### GPU 与 AI

| 端点 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/api/gpu_status` | GET | 获取 GPU 实时遥测数据 |
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

### `/api/run_cell`

请求体：

```json
{
  "code": "print('Hello, World!')"
}
```

响应：

```json
{
  "success": true,
  "stdout": "Hello, World!\n",
  "stderr": "",
  "elapsed_time": 0.012,
  "plots": []
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

## 📝 示例

启动后，Notebook 默认包含两个示例单元：

1. **Welcome Markdown** — 项目介绍与快速引导
2. **示例代码** — 使用 NumPy + Matplotlib 绘制正弦衰减曲线，展示代码执行与图表捕获功能
