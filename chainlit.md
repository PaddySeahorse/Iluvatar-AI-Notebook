# Iluvatar AI Notebook 助手

欢迎使用基于 Chainlit 的 AI 助手。左侧是 Notebook 编辑器，右侧是对话面板。

## 我能做什么

- 执行 Python 代码（调用 Jupyter 内核，与左侧 Notebook 共享变量）
- 查询天数智芯（Iluvatar Corex）GPU 的实时状态
- 查看内核变量表、最近输出与错误
- 列出并读取工作区中的 notebook 文件
- 检查内核与 watchdog 的运行状态

## 提示

- 首次使用请先在左侧 Notebook 的设置中保存 LLM API 配置（或设置 `OPENI_API_TOKEN` 环境变量）。
- 对话会自动携带内核上下文（变量表 / 最近输出 / 错误），帮助模型理解当前状态。