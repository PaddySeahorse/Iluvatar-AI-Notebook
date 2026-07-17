# Iluvatar AI Notebook 前端适配计划

> 基于《Iluvatar AI Notebook 是否应该复用 Jupyter 的库？》分析报告，制定前端从阻塞式 API 到 SSE 流式输出 + 富媒体渲染 + 代码补全的适配计划。

---

## 1. 适配概述

### 1.1 当前前端状态

当前 Iluvatar AI Notebook 前端基于 **Vanilla JavaScript**，使用以下 API 通信模式：

```
POST /api/run_cell  →  阻塞等待  →  一次性渲染全部输出
POST /api/interrupt_kernel  →  中断执行
GET  /api/kernel_status  →  轮询内核状态
```

### 1.2 需要适配的变更

| 变更项 | 当前 | 目标 | 影响范围 |
|--------|------|------|---------|
| 输出获取方式 | 阻塞式 HTTP POST | SSE 流式推送 | 核心执行流程 |
| 输出内容类型 | text + base64 图片 | MIME 多类型（PNG/HTML/LaTeX/JSON） | 输出渲染器 |
| 代码补全 | 静态 AST lint | 运行时 IPython 补全 | 编辑器交互 |
| 对象内省 | 无 | `?`/`??` 文档查看 | 新增功能 |
| 状态同步 | 轮询 | 实时状态推送 | 状态指示器 |
| 进度条 | 不支持 | `\r` 刷新 + tqdm 支持 | 输出渲染 |
| stdin 交互 | 不支持 | `input()` 支持 | 新增功能 |

---

## 2. SSE 流式输出适配

### 2.1 通信模型变更

**旧模型**：
```
前端                    后端
  │                      │
  ├─ POST /run_cell ────►│
  │                      │ exec() 阻塞
  │                      │
  │◄──── JSON 响应 ──────┤ (一次性返回)
  │                      │
```

**新模型**：
```
前端                    后端
  │                      │
  ├─ POST /run_cell_stream ───►│
  │                      │ ipykernel 执行
  │◄── SSE: stream ──────┤ stdout 实时推送
  │◄── SSE: stream ──────┤
  │◄── SSE: display_data ┤ 图片/HTML 推送
  │◄── SSE: result ──────┤ 执行结果
  │◄── SSE: status:idle ─┤ 执行完成
  │                      │
```

### 2.2 SSE 客户端实现

**文件**: `static/js/sse-client.js`

```javascript
/**
 * SSE 流式执行客户端
 */
// 实际实现：export 纯函数 runStream(code, callbacks, abortSignal)，
// 用 fetch + ReadableStream 解析 SSE 数据流，不依赖 class。
// 关键导出：
//   runStream(code, callbacks, abortSignal) -> Promise<void>
//   abortStream() -> void
//
// 回调签名保持与设计一致：
//   onStream(name, text), onDisplayData(data, metadata),
//   onResult(data, executionCount), onError(ename, evalue, traceback),
//   onStatus(state), onInput(code, executionCount)
```

### 2.3 输出渲染器改造

**文件**: `static/js/output-renderer.js`

```javascript
/**
 * 流式输出渲染器 — 支持 Jupyter MIME 类型
 */
// 实际实现：export class StreamOutputRenderer，非破坏性 DOM 渲染，
// 支持 \r 回车符刷新（tqdm 进度条），输出累积到 cell.output 对象保持向后兼容。
// 关键导出：
//   export class StreamOutputRenderer { ... }
//   export function pickMime(data)       — MIME 优先级选择器
//   export function renderMarkdownInline(escapedHtml) — 轻量 Markdown 渲染
```

### 2.4 内核状态指示器

**文件**: `static/js/kernel-indicator.js`

```javascript
/**
 * 内核状态指示器
 */
class KernelIndicator {
    constructor(element) {
        this.element = element;
        this.state = 'idle'; // idle | busy | disconnected | error
        this._render();
    }

    setState(state) {
        this.state = state;
        this._render();
    }

    _render() {
        const states = {
            idle: { icon: '●', color: '#22c55e', label: '就绪' },
            busy: { icon: '◉', color: '#f59e0b', label: '执行中' },
            disconnected: { icon: '○', color: '#64748b', label: '未连接' },
            error: { icon: '⦻', color: '#ef4444', label: '错误' },
        };

        const s = states[this.state] || states.disconnected;
        this.element.innerHTML = `
            <span class="kernel-dot" style="color:${s.color}">${s.icon}</span>
            <span class="kernel-label">${s.label}</span>
        `;
    }
}
```

---

## 3. 代码补全适配

### 3.1 补全 API 调用

**文件**: `static/js/completion.js`

```javascript
/**
 * 代码补全管理器
 */
class CompletionManager {
    constructor(editor) {
        this.editor = editor;
        this.completionBox = null;
        this.debounceTimer = null;
        this._createCompletionBox();
    }

    /**
     * 请求补全（在用户输入时调用）
     */
    async requestComplete() {
        const code = this.editor.getValue();
        const cursorPos = this.editor.getCursorPosition();
        const textBeforeCursor = code.substring(0, cursorPos);

        // 只在输入 . 或 Tab 键时触发补全
        // 或者是连续输入 3 个字符以上
        const lastChar = textBeforeCursor.slice(-1);
        if (lastChar !== '.' && lastChar !== '(' && lastChar !== '[') {
            // 对于普通 Tab 补全，检查是否已有足够上下文
            const lastWord = textBeforeCursor.match(/(\w+)$/);
            if (!lastWord || lastWord[1].length < 2) return;
        }

        try {
            const response = await fetch('/api/complete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, cursor_pos: cursorPos }),
            });

            const data = await response.json();
            if (data.matches && data.matches.length > 0) {
                this._showCompletionBox(data.matches, data.cursor_start, data.cursor_end);
            } else {
                this._hideCompletionBox();
            }
        } catch (err) {
            console.warn('Completion request failed:', err);
        }
    }

    _createCompletionBox() {
        this.completionBox = document.createElement('div');
        this.completionBox.className = 'completion-box';
        this.completionBox.style.display = 'none';
        this.completionBox.style.position = 'absolute';
        this.completionBox.style.zIndex = '1000';
        this.completionBox.style.background = '#fff';
        this.completionBox.style.border = '1px solid #e2e8f0';
        this.completionBox.style.borderRadius = '8px';
        this.completionBox.style.boxShadow = '0 4px 20px rgba(0,0,0,0.12)';
        this.completionBox.style.maxHeight = '300px';
        this.completionBox.style.overflowY = 'auto';
        this.completionBox.style.minWidth = '240px';
        this.completionBox.style.fontSize = '14px';

        document.body.appendChild(this.completionBox);

        // 点击外部关闭
        document.addEventListener('click', (e) => {
            if (!this.completionBox.contains(e.target)) {
                this._hideCompletionBox();
            }
        });
    }

    _showCompletionBox(matches, cursorStart, cursorEnd) {
        this.completionBox.innerHTML = '';

        matches.forEach((match, index) => {
            const item = document.createElement('div');
            item.className = 'completion-item';
            item.style.padding = '6px 12px';
            item.style.cursor = 'pointer';
            item.style.borderBottom = '1px solid #f1f5f9';
            item.textContent = match;

            item.addEventListener('click', () => {
                this._applyCompletion(match, cursorStart, cursorEnd);
            });

            item.addEventListener('mouseenter', () => {
                this.completionBox.querySelectorAll('.completion-item').forEach(
                    el => el.style.background = ''
                );
                item.style.background = '#eff6ff';
            });

            this.completionBox.appendChild(item);
        });

        // 定位到光标位置
        const cursorCoords = this.editor.getCursorCoordinates();
        this.completionBox.style.left = `${cursorCoords.left}px`;
        this.completionBox.style.top = `${cursorCoords.bottom + 4}px`;
        this.completionBox.style.display = 'block';
    }

    _hideCompletionBox() {
        this.completionBox.style.display = 'none';
    }

    _applyCompletion(match, cursorStart, cursorEnd) {
        this.editor.replaceRange(cursorStart, cursorEnd, match);
        this._hideCompletionBox();
        this.editor.focus();
    }
}
```

### 3.2 内省功能

```javascript
/**
 * 对象内省（? 和 ?? 功能）
 */
class InspectManager {
    constructor() {
        this.inspectPanel = null;
        this._createInspectPanel();
    }

    /**
     * 请求内省
     * @param {string} code - 对象名或表达式
     * @param {number} detailLevel - 0 = ? 普通, 1 = ?? 详细
     */
    async inspect(code, detailLevel = 0) {
        try {
            const response = await fetch('/api/inspect', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ code, cursor_pos: code.length, detail_level: detailLevel }),
            });

            const data = await response.json();
            if (data.found && data.data['text/plain']) {
                this._showInspectPanel(data.data['text/plain']);
            }
        } catch (err) {
            console.warn('Inspect request failed:', err);
        }
    }

    _createInspectPanel() {
        this.inspectPanel = document.createElement('div');
        this.inspectPanel.className = 'inspect-panel';
        this.inspectPanel.style.display = 'none';
        this.inspectPanel.style.position = 'fixed';
        this.inspectPanel.style.bottom = '20px';
        this.inspectPanel.style.right = '20px';
        this.inspectPanel.style.width = '480px';
        this.inspectPanel.style.maxHeight = '60vh';
        this.inspectPanel.style.overflow = 'auto';
        this.inspectPanel.style.background = '#fff';
        this.inspectPanel.style.border = '1px solid #e2e8f0';
        this.inspectPanel.style.borderRadius = '8px';
        this.inspectPanel.style.boxShadow = '0 8px 30px rgba(0,0,0,0.15)';
        this.inspectPanel.style.padding = '16px';
        this.inspectPanel.style.fontSize = '14px';
        this.inspectPanel.style.zIndex = '1000';

        document.body.appendChild(this.inspectPanel);
    }

    _showInspectPanel(text) {
        this.inspectPanel.innerHTML = `
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                <strong>Documentation</strong>
                <button class="inspect-close" style="border:none;background:none;cursor:pointer;font-size:18px">&times;</button>
            </div>
            <pre style="white-space:pre-wrap;font-family:monospace;margin:0">${text}</pre>
        `;
        this.inspectPanel.style.display = 'block';

        this.inspectPanel.querySelector('.inspect-close').addEventListener('click', () => {
            this.inspectPanel.style.display = 'none';
        });
    }
}
```

---

## 4. 执行流程集成

### 4.1 主流程改造

**文件**: `static/js/main.js`（核心改造，~1690 行）

实际实现说明：前端沿用 `main.js` 作为主控制器文件，未引入 `notebook.js`。执行流由 `main.js` 调用 `runStream()`（来自 `sse-client.js`）与 `StreamOutputRenderer`（来自 `output-renderer.js`）协作完成，不通过 `NotebookController` 类封装。补全和内省分别由 `CompletionManager`（`completion.js`）和 `InspectManager`（`inspect.js`）管理，通过 `renderer.js` 中的 `getCompletionManager()`/`getInspectManager()` 惰性创建。

```javascript
/**
 * Notebook 主控制器 — 改造后
 */
class NotebookController {
    constructor() {
        this.kernelClient = new SSEKernelClient();
        this.kernelIndicator = new KernelIndicator(
            document.getElementById('kernel-indicator')
        );
        this.completionManager = new CompletionManager(this.editor);
        this.inspectManager = new InspectManager();
    }

    /**
     * 执行单元格（改造后）
     */
    async executeCell(cell) {
        const code = cell.getCode();
        const outputRenderer = new OutputRenderer(cell.getOutputContainer());

        // 清空之前的输出
        outputRenderer.clear();

        // 设置 busy 状态
        this.kernelIndicator.setState('busy');
        cell.setExecuting(true);

        try {
            await this.kernelClient.executeStream(code, {
                onStream: (name, text) => {
                    outputRenderer.handleStream(name, text);
                },
                onDisplayData: (data) => {
                    outputRenderer.handleDisplayData(data);
                },
                onResult: (data, count) => {
                    outputRenderer.handleResult(data, count);
                },
                onError: (ename, evalue, traceback) => {
                    outputRenderer.handleError(ename, evalue, traceback);
                },
                onStatus: (state) => {
                    outputRenderer.handleStatus(state);
                    if (state === 'idle') {
                        this.kernelIndicator.setState('idle');
                        cell.setExecuting(false);
                    }
                },
                onDone: () => {
                    this.kernelIndicator.setState('idle');
                    cell.setExecuting(false);
                },
            });
        } catch (err) {
            outputRenderer.handleError('RuntimeError', err.message, []);
            this.kernelIndicator.setState('error');
            cell.setExecuting(false);
        }
    }

    /**
     * 中断执行
     */
    interruptKernel() {
        this.kernelClient.abort();
        fetch('/api/interrupt_kernel', { method: 'POST' });
    }

    /**
     * 处理键盘快捷键
     */
    handleKeyDown(event) {
        // Tab 补全
        if (event.key === 'Tab') {
            event.preventDefault();
            this.completionManager.requestComplete();
            return;
        }

        // Shift+Tab 内省
        if (event.key === 'Tab' && event.shiftKey) {
            event.preventDefault();
            const code = this.editor.getSelectedText() || this.editor.getWordAtCursor();
            if (code) {
                this.inspectManager.inspect(code);
            }
            return;
        }
    }
}
```

---

## 5. 兼容性过渡方案

### 5.1 双 API 模式

在过渡期间，前端同时支持旧 API（阻塞式）和新 API（流式），通过配置切换：

```javascript
/**
 * 执行模式切换
 */
class ExecutionAdapter {
    constructor() {
        // 从配置或 Feature Flag 获取模式
        this.mode = localStorage.getItem('execution_mode') || 'stream';
    }

    async execute(code, callbacks) {
        if (this.mode === 'stream') {
            return this._executeStream(code, callbacks);
        } else {
            return this._executeLegacy(code, callbacks);
        }
    }

    async _executeStream(code, callbacks) {
        const client = new SSEKernelClient();
        return client.executeStream(code, callbacks);
    }

    async _executeLegacy(code, callbacks) {
        const response = await fetch('/api/run_cell', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ code }),
        });

        const result = await response.json();

        // 模拟流式回调
        if (result.stdout) {
            callbacks.onStream('stdout', result.stdout);
        }
        if (result.stderr) {
            callbacks.onStream('stderr', result.stderr);
        }
        if (result.plots) {
            for (const plot of result.plots) {
                callbacks.onDisplayData({ 'image/png': plot });
            }
        }
        if (result.error) {
            callbacks.onError('Error', result.error, []);
        }
        callbacks.onStatus('idle');
        callbacks.onDone();
    }
}
```

### 5.2 渐进增强

| 阶段 | 模式 | 说明 |
|------|------|------|
| 阶段 1 | 旧 API 兼容 | 新内核 + 旧 API 格式响应，前端零改动 |
| 阶段 2 | 流式 API 可选 | 前端通过配置切换流式模式 |
| 阶段 3 | 流式 API 默认 | 默认使用流式，旧 API 保留作为 fallback |
| 阶段 4 | 仅流式 API | 移除旧 API 支持 |

---

## 6. 新增依赖（可选）

| 库 | 大小 | 用途 | 必要性 |
|----|------|------|--------|
| `marked.js` | ~20KB | Markdown 渲染（`text/markdown` MIME） | 推荐 |
| `katex` | ~300KB | LaTeX 数学公式渲染（`text/latex` MIME） | 可选 |
| `highlight.js` | ~30KB | 代码语法高亮 | 推荐 |

这些库可通过 CDN 或本地打包引入，不影响现有 Vanilla JS 架构。

---

## 7. 前端测试

### 7.1 手动测试清单

| 场景 | 验证点 |
|------|--------|
| 执行 `print('hello')` | 输出 `hello` 正确显示 |
| 执行 `for i in range(10): print(i); time.sleep(0.1)` | 数字逐行出现，有延迟感 |
| 执行 `plt.plot([1,2,3]); plt.show()` | 图片内联显示 |
| 执行 `import pandas as pd; pd.DataFrame({'a':[1,2]})` | DataFrame HTML 表格渲染 |
| 执行 `1/0` | 错误 traceback 红色显示 |
| 执行 `while True: pass` 然后 click 中断 | 3 秒内中断成功 |
| 输入 `pd.` 后按 Tab | 补全列表弹出 |
| 输入 `?pd.DataFrame` 后按 Shift+Tab | 文档面板显示 |
| 执行 `!pip install requests` | Shell 命令输出正确 |
| 执行 `%timeit 1+1` | 时间统计显示 |

---

**文档版本**: v1.1
**最后更新**: 2026-07-17
**负责人**: 待指定