# Iluvatar AI Notebook — Vercel 极简风格 UI 重设计

## 概述

将 Iluvatar AI Notebook 项目的 UI 以 Vercel 极简风格重新设计，输出为 `.design` 画布项目。仅做视觉设计，不修改原始项目的任何代码文件。

## 当前状态分析

原始项目位于 `/data/user/work/Iluvatar-AI-Notebook-main/`，是一个 Flask + 原生 JS 的 Jupyter-like Notebook 应用：

- **布局**: 三栏结构 — 左侧文件浏览器 (240px) + 中间单元格编辑区 + 右侧 AI 助手面板 (380px)
- **当前风格**: 深蓝黑背景 + 青紫霓虹渐变 + 发光阴影 + 大圆角 (12-16px) + 厚重 box-shadow
- **技术**: CodeMirror 代码编辑器、Font Awesome 图标、Inter + Fira Code 字体
- **主要组件**: 顶部导航栏 (Logo + 内核状态 + GPU 仪表板 + 设置)、文件侧栏、单元格 (代码/Markdown)、AI 聊天面板、执行历史、变量检查器、设置模态框、GPU 详情模态框

## 设计方向 — Vercel 极简风格

核心视觉转变：

| 维度 | 当前 | Vercel 目标 |
|------|------|------------|
| 背景 | `#070913` 深蓝黑 | `#000` 纯黑 |
| 边框 | `#212c47` 蓝灰 + 发光 | `#222` 中性灰，无发光 |
| 强调色 | `#00f2fe`/`#4facfe` 青蓝渐变 | `#0070f3` Vercel 蓝（极少使用） |
| 阴影 | 厚重 (12-40px) | 极简 (1px 边框线) |
| 圆角 | 12-16px | 6-8px |
| 按钮 | 渐变填充 + 发光 hover | 纯黑/白 + 1px 边框 |
| 动效 | 0.25s cubic-bezier + pulse | 0.15s ease，无持续动画 |
| 字重 | 700 标题 | 600 标题（更纤细） |
| 间距 | 20-24px 单元格间距 | 2-4px（紧凑无缝） |

## 实施方案

### 输出文件结构

```
/workspace/iluvatar-notebook-vercel-redesign/
├── iluvatar-notebook-vercel-redesign.design    # 画布元数据
├── colors_and_type.css                          # Vercel 设计令牌
├── pages/
│   └── notebook-main.html                      # 完整重设计的 Notebook 页面 mockup
└── assets/
    └── (无图片资源，纯 CSS 设计)
```

### Step 1 — 准备画布项目

创建 `.design` 元数据文件和 `colors_and_type.css` 设计令牌：
- Vercel 色彩系统（纯黑背景、中性灰边框、极简蓝强调色）
- Inter + Fira Code 字体保留
- 小圆角 (6-8px)、细线框阴影、0.15s ease 过渡

### Step 2 — 设计 Notebook 主页面

生成一个完整的 `pages/notebook-main.html` 作为静态 mockup，包含：

**HTML 结构要求：**
- 保留原始项目的所有 DOM 结构（id 和 class 不变），以便展示完整的 UI 全貌
- 包含示例内容：欢迎 Markdown 单元格 + 示例代码单元格 + 输出区域
- 展示 AI 聊天面板的欢迎消息和快捷提示
- 展示 GPU 仪表板数据、设置模态框和 GPU 详情模态框的静态状态
- 响应式布局保留（桌面端为主）

**各组件设计要点：**

1. **顶部导航栏**: 56px 高度，纯黑背景 + 1px 底边框，Logo 纯白文字，GPU 统计使用细进度条，设置按钮为幽灵样式
2. **文件侧栏**: 透明背景 + 1px 右边框，文件列表紧凑排列，活跃项使用细微背景高亮
3. **单元格**: 8px 圆角，1px 边框无边框阴影，紧凑间距 (2-4px)，运行按钮改为圆角方形 (6px) 而非圆形，移除 gutter 背景和边框
4. **AI 辅助栏**: 灰色虚线边框替代紫色半透明，生成按钮为纯黑背景
5. **输出区域**: `#111` 纯色背景替代半透明黑
6. **AI 聊天面板**: 透明背景融合，标签页活跃态使用白色底线，聊天气泡 8px 圆角，快捷提示改为文字链接样式
7. **模态框**: 移除 backdrop-filter blur，8px 圆角，无边框阴影仅用 1px 边框
8. **浮动按钮**: 纯黑/白背景 + 1px 边框，移除渐变和阴影
9. **通知弹窗**: 纯黑背景 + 1px 边框，8px 圆角替代 20px 胶囊形
10. **滚动条**: 更细 (6px)，更透明

### Step 3 — 验证 & 交付

运行验证脚本确认 `.design` 项目完整性，然后交付。

## 关键约束

- 所有 JS 使用的 DOM id/class 名在 mockup HTML 中保留（用于展示结构完整性）
- 不修改原始项目 (`/data/user/work/Iluvatar-AI-Notebook-main/`) 的任何文件
- 不需要功能交互（mockup 是纯静态展示）
- 仅使用 CSS 实现视觉变化，无额外 JS 依赖
