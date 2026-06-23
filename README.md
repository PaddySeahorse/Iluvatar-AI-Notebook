# Iluvatar AI Notebook · 天数智芯智能笔记本

> 面向国产 AI 芯片（天数智芯 Iluvatar BI-150）的 AI 辅助 Notebook 开发环境，融合交互式编程与 AI Copilot 能力，在浏览器中即可完成 Python 开发、数据可视化和智能辅助编码。

---

## ✨ 功能特性

- **交互式 Notebook** — 支持 Python 代码单元和 Markdown 文本单元的添加、编辑与执行，持久化保存
- **实时 GPU 遥测** — 顶部仪表板实时展示 Iluvatar BI-150 的使用率、显存、温度、功耗等关键指标
- **AI Copilot** — 代码单元内嵌 AI 输入框，一键生成代码；运行错误时可一键 AI 诊断
- **AI Chat 助手** — 右侧对话面板支持自由问答，可选择携带 Notebook 全部上下文
- **暗色/亮色主题** — 一键切换，适配不同使用场景
- **图表捕获** — 自动捕获 Matplotlib 生成的图表并以 Base64 形式内嵌展示
- **持久化存储** — Notebook 内容与 API 配置自动保存至浏览器 localStorage

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
├── app.py              # Flask 后端服务
├── static/
│   ├── index.html      # 前端主页面
│   ├── style.css       # 样式表
│   └── app.js          # 前端核心逻辑
└── README.md
```

---

## 🚀 快速开始

### 环境要求

- Python 3.8+
- pip

### 安装依赖

```bash
pip install flask matplotlib requests
```

### 配置（可选）

在项目根目录创建 `.env` 文件，配置以下环境变量：

```env
OPENI_API_URL=https://token.openi.org.cn/v1/chat/completions
OPENI_API_TOKEN=your_api_token_here
OPENI_API_MODEL=dsv4
```

也可以在启动后通过 UI 设置面板配置。

### 启动

```bash
python app.py
```

访问 `http://127.0.0.1:5000` 即可使用。

---

## 📡 API 端点

| 端点 | 方法 | 说明 |
| :--- | :--- | :--- |
| `/` | GET | 主页面 |
| `/api/get_config` | GET | 获取默认 API 配置 |
| `/api/run_cell` | POST | 执行 Python 代码单元 |
| `/api/gpu_status` | GET | 获取 GPU 实时遥测数据 |
| `/api/ai_call` | POST | 代理调用 LLM API |

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
  ]
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

### AI 辅助

- **Copilot**：代码单元底部的 AI 输入框，描述需求即可生成代码
- **Debug**：代码运行失败后，点击「🔧 AI Debug」自动分析错误
- **Chat**：右侧对话面板进行自由问答，可勾选「附加 Notebook 上下文」

---

## 📝 示例

启动后，Notebook 默认包含两个示例单元：

1. **Welcome Markdown** — 项目介绍与快速引导
2. **示例代码** — 使用 NumPy + Matplotlib 绘制正弦衰减曲线，展示代码执行与图表捕获功能
