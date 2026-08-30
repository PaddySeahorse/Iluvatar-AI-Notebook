// Main application entry and coordinator for Iluvatar AI Notebook

import {
    state,
    loadSavedNotebook,
    saveNotebookToLocalStorage,
    addCell,
    deleteCell,
    moveCell,
    activateCell,
    deactivateAllCells,
    restoreLastDeletedCell,
    exportNotebookAsIpynb,
    importNotebookFromIpynb
} from './state.js';

import {
    initConfig,
    saveApiConfig,
    fetchGpuStatus,
    callLlmProxy,
    callLlmProxyStream,
    callAgentStream,
    fetchAgentContext,
    lintCellOnBackend,
    fetchKernelVariables,
    fetchNotebooksList,
    readNotebookFromServer,
    saveNotebookToServer,
    createNotebookOnServer,
    renameNotebookOnServer,
    deleteNotebookFromServer,
    interruptKernelOnBackend
} from './api.js';

import {
    renderCells,
    parseMarkdown,
    showFloatingNotification,
    applyLintDiagnostics,
    activeEditors,
    renderAiDebugBar
} from './renderer.js';

import { SSEKernelClient } from './sse-client.js';
import { StreamOutputRenderer } from './output-renderer.js';
import { KernelIndicator } from './kernel-indicator.js';
import { TerminalPanel } from './terminal/terminal-panel.js';
import { bindTerminalShortcuts } from './terminal/terminal-shortcuts.js';

// Rerender helper to keep view in sync with state changes
function triggerRender() {
    renderCells(state.cells, state.activeCellId, rendererCallbacks);
}

// Active streaming executions keyed by cell id, so the global interrupt
// button can abort them (client-side fetch abort + backend kernel interrupt).
const activeSseClients = new Map();

// Top-nav kernel status indicator (wraps .status-dot / .status-text).
// Created once and shared; setKernelStatus() delegates to it so existing
// call sites don't need to change.
const kernelIndicator = new KernelIndicator();

function getChainlitFrame() {
    return document.getElementById('chainlitFrame');
}

function ensureAiTabActive() {
    const aiBtn = document.getElementById('aiAssistantTabBtn');
    const aiContent = document.getElementById('aiAssistantTabContent');
    const execBtn = document.getElementById('execHistoryTabBtn');
    const varBtn = document.getElementById('varInspectorTabBtn');
    const execContent = document.getElementById('execHistoryTabContent');
    const varContent = document.getElementById('varInspectorTabContent');
    if (aiBtn && aiContent) {
        [aiBtn, execBtn, varBtn].forEach(b => b && b.classList.remove('active'));
        [aiContent, execContent, varContent].forEach(c => c && c.classList.add('hidden'));
        aiBtn.classList.add('active');
        aiContent.classList.remove('hidden');
    }
    const aiSidebar = document.getElementById('aiSidebar');
    const openBtn = document.getElementById('openSidebarFloatingBtn');
    if (aiSidebar && aiSidebar.classList.contains('collapsed')) {
        aiSidebar.classList.remove('collapsed');
        if (openBtn) openBtn.classList.add('hidden');
    }
}

function sendToChainlit(text) {
    const frame = getChainlitFrame();
    if (!frame || !frame.contentWindow) return false;
    ensureAiTabActive();
    try {
        frame.contentWindow.postMessage({ type: 'iluvatar:ask', text }, '*');
        return true;
    } catch (e) {
        return false;
    }
}

function insertAgentCell(code, opts = {}) {
    if (!code || !code.trim()) return;
    const cellType = opts.cell_type === 'markdown' ? 'markdown' : 'code';
    const stdout = opts.stdout || '';
    const stderr = opts.stderr || '';
    const ok = opts.ok !== false;
    let idx = opts.index;
    if (idx != null) {
        idx = parseInt(idx, 10);
        if (isNaN(idx) || idx < 0) idx = state.cells.length;
        if (idx > state.cells.length) idx = state.cells.length;
    } else {
        idx = state.cells.length;
    }
    if (cellType === 'markdown') {
        const cell = {
            id: 'cell_' + Math.random().toString(36).substr(2, 9),
            type: 'markdown',
            content: code,
            isEditingMarkdown: false
        };
        state.cells.splice(idx, 0, cell);
        state.activeCellId = cell.id;
        triggerRender();
        saveNotebookToLocalStorage();
        showFloatingNotification(idx === state.cells.length - 1 ? 'Agent 已创建 Markdown 单元格' : `Agent 已在位置 ${idx} 创建 Markdown 单元格`);
        return;
    }
    state.executionCounter++;
    const cell = {
        id: 'cell_' + Math.random().toString(36).substr(2, 9),
        type: 'code',
        content: code,
        output: stdout || stderr ? { stdout, stderr, html: '', plots: [] } : null,
        elapsedTime: null,
        success: ok,
        isExecuting: false,
        executionIndex: state.executionCounter
    };
    state.cells.splice(idx, 0, cell);
    state.activeCellId = cell.id;
    triggerRender();
    saveNotebookToLocalStorage();
    showFloatingNotification(idx === state.cells.length - 1 ? 'Agent 已创建代码单元格' : `Agent 已在位置 ${idx} 创建代码单元格`);
    if (cellType === 'code') updateVariablesInspector();
}

window.addEventListener('message', (event) => {
    const d = event.data;
    if (!d || d.type !== 'iluvatar:agent_cell') return;
    if (d.source === 'create_cell') {
        insertAgentCell(d.code, { cell_type: d.cell_type, index: d.index, ok: d.ok });
    } else {
        insertAgentCell(d.code, { stdout: d.stdout, stderr: d.stderr, ok: d.ok });
    }
});

// Callbacks passed to renderer.js to decouple it from state mutation logic
const rendererCallbacks = {
    onRunCell: (id) => runCell(id),
    onDeleteCell: (id) => {
        deleteCell(id);
        triggerRender();
    },
    onMoveCell: (id, direction) => {
        if (moveCell(id, direction)) {
            triggerRender();
        }
    },
    onAddCell: (type, index) => {
        addCell(type, index);
        triggerRender();
    },
    onActivateCell: (id) => {
        if (state.activeCellId === id) return;
        activateCell(id);
        triggerRender();
    },
    onContentChange: (id, content) => {
        const cell = state.cells.find(c => c.id === id);
        if (cell) {
            cell.content = content;
            saveNotebookToLocalStorage();
        }
    },
    onActivateMarkdown: (id) => {
        const cell = state.cells.find(c => c.id === id);
        if (cell) {
            cell.isEditingMarkdown = true;
            triggerRender();
        }
    },
    onDeactivateMarkdown: (id) => {
        const cell = state.cells.find(c => c.id === id);
        if (cell) {
            cell.isEditingMarkdown = false;
            triggerRender();
            saveNotebookToLocalStorage();
        }
    },
    onCodeChangeDebounced: (id, code) => debounceLintCell(id, code),
    onAiAssist: (id, prompt, btn) => runCellAiAssist(id, prompt, btn),
    onDebug: (id, btn) => runCellDebug(id, btn),
    onExplainCell: (id) => runCellExplain(id),
    onAcceptOverwrite: (id, code) => {
        const cell = state.cells.find(c => c.id === id);
        if (cell) {
            cell.content = code;
            delete cell.aiSuggestion;
            triggerRender();
            saveNotebookToLocalStorage();
            showFloatingNotification('已覆盖单元格代码！');
        }
    },
    onAcceptInsert: (id, code) => {
        const currentIdx = state.cells.findIndex(c => c.id === id);
        const newCell = {
            id: 'cell_' + Math.random().toString(36).substr(2, 9),
            type: 'code',
            content: code,
            output: null,
            elapsedTime: null,
            success: true,
            isExecuting: false
        };
        state.cells.splice(currentIdx + 1, 0, newCell);
        
        const cell = state.cells.find(c => c.id === id);
        if (cell) {
            delete cell.aiSuggestion;
        }
        
        state.activeCellId = newCell.id;
        triggerRender();
        saveNotebookToLocalStorage();
        showFloatingNotification('已将推荐代码插入为新单元格！');
    },
    onDiscardSuggestion: (id) => {
        const cell = state.cells.find(c => c.id === id);
        if (cell) {
            delete cell.aiSuggestion;
            triggerRender();
            saveNotebookToLocalStorage();
        }
    }
};

// Initialize welcome cells on empty notebook
function addInitialCells() {
    // Welcome Markdown Cell
    state.cells.push({
        id: 'cell_' + Math.random().toString(36).substr(2, 9),
        type: 'markdown',
        content: `# 🚀 天数智芯 AI-First 智能笔记本 (Iluvatar AI Notebook)
这是一个为AI开发者打造的**国产算力（天数智芯 BI-150）加速的智能 Notebook 环境**。

### ✨ 特性
1. **持久化 Python 变量环境**：不同单元格之间的变量和库导入会持续存在。
2. **Matplotlib 绘图集成**：自动捕获 Matplotlib 图表，并在单元格输出区即时展示。
3. **AI Code Copilot**：在每个单元格下方输入提示词，让 AI 帮您编写或优化代码。
4. **一键 AI 调试 (AI Debug)**：代码运行出错时，点击一键调试，自动诊断 traceback 并生成修复代码。
5. **实时 GPU 硬件看板**：监控天数智芯 BI-150 GPU 显存 (VRAM)、利用率、功率及温度状态。

*双击本单元格即可开始编辑 Markdown 格式文本。*`,
        output: null,
        isEditingMarkdown: false
    });

    // Example PyTorch Code Cell
    state.cells.push({
        id: 'cell_' + Math.random().toString(36).substr(2, 9),
        type: 'code',
        content: `# 导入数学包，在天数智芯 GPU 上模拟随机计算并绘图
# 提示：绘图必须以 plt.show() 或 display(fig) 结束才会捕获为 display_data；
# 仅 plt.savefig("/tmp/x.png") 不会显示在输出区，请用 plt.show()。
import numpy as np
import matplotlib.pyplot as plt

print("正在初始化天数智芯 BI-150 运算环境...")
x = np.linspace(0, 10, 100)
y = np.sin(x) * np.exp(-x/3)

# 打印变量，这些变量可在下一个单元格中访问
total_points = len(x)
print(f"成功计算了 {total_points} 个数据点。")

# 绘图（务必调用 plt.show() 才会内嵌显示）
plt.figure(figsize=(7, 3.5))
plt.plot(x, y, label='Loss Curve (BI-150)', color='#00f2fe', linewidth=2)
plt.title("Iluvatar GPU Simulated Training Loss")
plt.xlabel("Epochs")
plt.ylabel("Loss")
plt.grid(True, linestyle='--', alpha=0.3)
plt.legend()
plt.show()`,
        output: null,
        elapsedTime: null,
        success: true,
        isExecuting: false
    });

    triggerRender();
    saveNotebookToLocalStorage();
}

const lintTimers = new Map();
function debounceLintCell(id, code) {
    if (lintTimers.has(id)) {
        clearTimeout(lintTimers.get(id));
    }
    const timer = setTimeout(async () => {
        lintTimers.delete(id);
        try {
            const diagnostics = await lintCellOnBackend(code);
            applyLintDiagnostics(id, diagnostics);
        } catch (e) {
            console.error("Lint error:", e);
        }
    }, 600);
    lintTimers.set(id, timer);
}

async function updateVariablesInspector() {
    try {
        const variables = await fetchKernelVariables();
        const listEl = document.getElementById('variablesList');
        if (!listEl) return;
        
        if (variables.length === 0) {
            listEl.innerHTML = `
                <tr>
                    <td colspan="4" class="no-vars-msg">暂无活动变量</td>
                </tr>
            `;
            return;
        }
        
        listEl.innerHTML = '';
        variables.forEach(v => {
            const tr = document.createElement('tr');
            
            const nameTd = document.createElement('td');
            nameTd.className = 'var-name';
            nameTd.innerText = v.name;
            tr.appendChild(nameTd);
            
            const typeTd = document.createElement('td');
            typeTd.className = 'var-type';
            typeTd.innerText = v.type;
            tr.appendChild(typeTd);
            
            const shapeTd = document.createElement('td');
            shapeTd.className = 'var-shape';
            shapeTd.innerText = v.shape || '-';
            tr.appendChild(shapeTd);
            
            const reprTd = document.createElement('td');
            reprTd.className = 'var-repr';
            reprTd.innerText = v.repr;
            tr.appendChild(reprTd);
            
            listEl.appendChild(tr);
        });
    } catch (e) {
        console.error("Failed to update variables inspector:", e);
    }
}

// Render the list of files in left sidebar
function renderFileList() {
    const listEl = document.getElementById('fileList');
    if (!listEl) return;
    
    listEl.innerHTML = '';
    
    if (state.notebookFiles.length === 0) {
        listEl.innerHTML = '<li class="no-files-msg">暂无 Notebook 文件</li>';
        return;
    }
    
    state.notebookFiles.forEach(filename => {
        const li = document.createElement('li');
        li.className = `file-item ${filename === state.currentFilename ? 'active' : ''}`;
        
        const nameSpan = document.createElement('button');
        nameSpan.className = 'file-name';
        nameSpan.type = 'button';
        nameSpan.innerHTML = `<i class="fa-solid fa-file-invoice" aria-hidden="true"></i> ${filename}`;
        nameSpan.addEventListener('click', () => {
            selectNotebookFile(filename);
        });
        li.appendChild(nameSpan);

        const actions = document.createElement('div');
        actions.className = 'file-actions';

        const renameBtn = document.createElement('button');
        renameBtn.className = 'file-action-btn';
        renameBtn.innerHTML = '<i class="fa-solid fa-pen-to-square" aria-hidden="true"></i>';
        renameBtn.title = '重命名';
        renameBtn.setAttribute('aria-label', '重命名 ' + filename);
        renameBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            renameNotebookPrompt(filename);
        });

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'file-action-btn delete';
        deleteBtn.innerHTML = '<i class="fa-solid fa-trash-can" aria-hidden="true"></i>';
        deleteBtn.title = '删除';
        deleteBtn.setAttribute('aria-label', '删除 ' + filename);
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteNotebookPrompt(filename);
        });
        
        actions.appendChild(renameBtn);
        actions.appendChild(deleteBtn);
        li.appendChild(actions);
        listEl.appendChild(li);
    });
}

// Load selected notebook from server
async function selectNotebookFile(filename) {
    if (state.currentFilename === filename && state.cells.length > 0) return;
    
    // Save current notebook state before switching
    if (state.currentFilename && state.cells.length > 0) {
        try {
            const content = exportNotebookAsIpynb();
            await saveNotebookToServer(state.currentFilename, content);
        } catch (e) {
            console.error("Auto-save failed before switching notebook:", e);
        }
    }
    
    try {
        const data = await readNotebookFromServer(filename);
        if (data.success) {
            state.currentFilename = filename;
            localStorage.setItem('notebook_current_filename', filename);
            importNotebookFromIpynb(data.content);
            triggerRender();
            renderFileList();
            
            // Sync title input
            const titleEl = document.getElementById('notebookTitle');
            if (titleEl) titleEl.value = filename;
            
            showFloatingNotification(`已加载 ${filename}`);
        } else {
            showFloatingNotification(`加载失败: ${data.message}`);
        }
    } catch (err) {
        showFloatingNotification(`读取 Notebook 失败: ${err.message}`);
    }
}

// Rename notebook via prompt dialog
async function renameNotebookPrompt(filename) {
    const baseName = filename.endsWith('.ipynb') ? filename.slice(0, -6) : filename;
    const newBaseName = prompt('输入新的文件名:', baseName);
    if (!newBaseName) return;
    
    const cleanNewName = newBaseName.trim();
    if (!cleanNewName) return;
    
    const newFilename = cleanNewName.endsWith('.ipynb') ? cleanNewName : cleanNewName + '.ipynb';
    
    try {
        const res = await renameNotebookOnServer(filename, newFilename);
        if (res.success) {
            if (state.currentFilename === filename) {
                state.currentFilename = newFilename;
                localStorage.setItem('notebook_current_filename', newFilename);
                const titleEl = document.getElementById('notebookTitle');
                if (titleEl) titleEl.value = newFilename;
            }
            showFloatingNotification('重命名成功！');
            await refreshNotebooksListFromServer();
        } else {
            alert(`重命名失败: ${res.message}`);
        }
    } catch (err) {
        alert(`重命名出错: ${err.message}`);
    }
}

// Delete notebook via confirm prompt
async function deleteNotebookPrompt(filename) {
    if (!confirm(`确定要删除笔记本 ${filename} 吗？`)) return;
    
    try {
        const res = await deleteNotebookFromServer(filename);
        if (res.success) {
            showFloatingNotification('删除成功！');
            
            if (state.currentFilename === filename) {
                state.currentFilename = '';
                localStorage.removeItem('notebook_current_filename');
            }
            
            await refreshNotebooksListFromServer();
            
            if (!state.currentFilename) {
                if (state.notebookFiles.length > 0) {
                    await selectNotebookFile(state.notebookFiles[0]);
                } else {
                    await createNewNotebook();
                }
            }
        } else {
            alert(`删除失败: ${res.message}`);
        }
    } catch (err) {
        alert(`删除出错: ${err.message}`);
    }
}

// Create new blank notebook on server
async function createNewNotebook() {
    try {
        const res = await createNotebookOnServer();
        if (res.success) {
            showFloatingNotification('新建笔记本成功！');
            await refreshNotebooksListFromServer();
            await selectNotebookFile(res.filename);
        } else {
            alert(`新建失败: ${res.message}`);
        }
    } catch (err) {
        alert(`新建出错: ${err.message}`);
    }
}

// Sync notebooks list from server
async function refreshNotebooksListFromServer() {
    try {
        const data = await fetchNotebooksList();
        if (data.success) {
            state.notebookFiles = data.files;
            renderFileList();
        }
    } catch (err) {
        console.error("Failed to load notebooks list:", err);
    }
}

// Bind Global UI Elements
function setupEventListeners() {
    const refreshVarsBtn = document.getElementById('refreshVarsBtn');
    if (refreshVarsBtn) {
        refreshVarsBtn.addEventListener('click', updateVariablesInspector);
    }
    
    const interruptKernelBtn = document.getElementById('interruptKernelBtn');
    if (interruptKernelBtn) {
        interruptKernelBtn.addEventListener('click', async () => {
            // If there are active streaming executions, abort them; the SSE
            // client aborts the fetch and signals the backend kernel interrupt
            // (control channel works even when shell is blocked by GPU compute).
            if (activeSseClients.size > 0) {
                for (const client of activeSseClients.values()) {
                    client.abort();
                }
                showFloatingNotification('⚡️ 已中断正在执行的代码');
                return;
            }
            // No active stream: fall back to a direct backend interrupt.
            try {
                const res = await interruptKernelOnBackend();
                if (res.success) {
                    showFloatingNotification('⚡️ 已向内核发送强行中断信号');
                } else {
                    alert(`中断失败: ${res.message}`);
                }
            } catch (err) {
                alert(`中断请求出错: ${err.message}`);
            }
        });
    }
    // Notebook Title Update / Rename on server
    const titleEl = document.getElementById('notebookTitle');
    if (titleEl) {
        titleEl.addEventListener('focus', function() {
            this.setAttribute('data-old-val', this.value);
        });
        titleEl.addEventListener('blur', async function() {
            const oldVal = this.getAttribute('data-old-val');
            const newVal = this.value.trim();
            if (!newVal || newVal === oldVal) return;
            
            const oldFilename = state.currentFilename || oldVal;
            const newFilename = newVal.endsWith('.ipynb') ? newVal : newVal + '.ipynb';
            
            try {
                const res = await renameNotebookOnServer(oldFilename, newFilename);
                if (res.success) {
                    state.currentFilename = newFilename;
                    localStorage.setItem('notebook_current_filename', newFilename);
                    this.value = newFilename;
                    showFloatingNotification('文件名已更新！');
                    await refreshNotebooksListFromServer();
                } else {
                    alert(`重命名失败: ${res.message}`);
                    this.value = oldFilename;
                }
            } catch (err) {
                alert(`重命名出错: ${err.message}`);
                this.value = oldFilename;
            }
        });
    }

    // Left File Sidebar Toggle
    const fileSidebar = document.getElementById('fileSidebar');
    const openFileSidebarBtn = document.getElementById('openFileSidebarFloatingBtn');
    const toggleFileSidebarBtn = document.getElementById('toggleFileSidebarBtn');
    
    if (toggleFileSidebarBtn && fileSidebar && openFileSidebarBtn) {
        toggleFileSidebarBtn.addEventListener('click', () => {
            fileSidebar.classList.add('collapsed');
            openFileSidebarBtn.classList.remove('hidden');
        });
        
        openFileSidebarBtn.addEventListener('click', () => {
            fileSidebar.classList.remove('collapsed');
            openFileSidebarBtn.classList.add('hidden');
        });
    }

    // New Notebook button
    const newNotebookBtn = document.getElementById('newNotebookBtn');
    if (newNotebookBtn) {
        newNotebookBtn.addEventListener('click', createNewNotebook);
    }

    // Top action buttons
    document.getElementById('addCodeBtn').addEventListener('click', () => {
        addCell('code');
        triggerRender();
    });
    document.getElementById('addMarkdownBtn').addEventListener('click', () => {
        addCell('markdown');
        triggerRender();
    });
    document.getElementById('addCodeBottomBtn').addEventListener('click', () => {
        addCell('code');
        triggerRender();
    });
    document.getElementById('addMarkdownBottomBtn').addEventListener('click', () => {
        addCell('markdown');
        triggerRender();
    });
    
    document.getElementById('clearAllOutputsBtn').addEventListener('click', () => {
        state.cells.forEach(c => {
            if (c.type === 'code') {
                c.output = null;
                c.elapsedTime = null;
                c.success = true;
            }
        });
        triggerRender();
        saveNotebookToLocalStorage();
    });

    // Notebook Import/Export
    document.getElementById('exportNotebookBtn').addEventListener('click', () => {
        const ipynbData = exportNotebookAsIpynb();
        const jsonStr = JSON.stringify(ipynbData, null, 2);
        const titleEl = document.getElementById('notebookTitle');
        const filename = titleEl ? titleEl.value : 'Untitled_Iluvatar_Notebook.ipynb';
        
        const blob = new Blob([jsonStr], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename.endsWith('.ipynb') ? filename : filename + '.ipynb';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        showFloatingNotification('导出 Notebook 成功！');
    });

    const importInput = document.getElementById('importNotebookInput');
    document.getElementById('importNotebookBtn').addEventListener('click', () => {
        importInput.click();
    });

    importInput.addEventListener('change', (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (event) => {
            try {
                const ipynbObj = JSON.parse(event.target.result);
                importNotebookFromIpynb(ipynbObj);
                triggerRender();
                showFloatingNotification('导入 Notebook 成功！');
            } catch (err) {
                alert('解析 .ipynb 文件失败: ' + err.message);
            }
            importInput.value = ''; // Reset input
        };
        reader.readAsText(file);
    });

    // Theme toggler (placeholder)
    document.getElementById('themeToggleBtn').addEventListener('click', () => {
        document.body.classList.toggle('light-theme');
        const icon = document.querySelector('#themeToggleBtn i');
        const isDark = !document.body.classList.contains('light-theme');
        if (isDark) {
            icon.className = 'fa-solid fa-sun';
        } else {
            icon.className = 'fa-solid fa-moon';
        }
        
        // Update CodeMirror editor themes dynamically
        const cmTheme = isDark ? 'dracula' : 'neo';
        activeEditors.forEach(editor => {
            editor.setOption('theme', cmTheme);
        });
        if (configFileCm) {
            configFileCm.setOption('theme', cmTheme);
        }
    });

    // Settings Modal
    const settingsModal = document.getElementById('settingsModal');
    const apiUrlInput = document.getElementById('apiUrlInput');
    const advancedModeToggle = document.getElementById('advancedModeToggle');
    const basicConfigView = document.getElementById('basicConfigView');
    const advancedConfigView = document.getElementById('advancedConfigView');

    let configFileCm = null;

    function isAdvancedMode() {
        return advancedModeToggle.checked;
    }

    // Lazily create the shared CodeMirror editor for the advanced view using
    // the project's locally-vendored CodeMirror (window.CodeMirror UMD global).
    function getConfigFileEditor() {
        if (configFileCm) return configFileCm;
        const isDark = document.body.classList.contains('light-theme');
        configFileCm = CodeMirror(document.getElementById('configEditorContainer'), {
            value: '',
            lineNumbers: true,
            indentUnit: 2,
            viewportMargin: Infinity,
            theme: isDark ? 'neo' : 'dracula',
        });
        return configFileCm;
    }

    async function refreshConfigFileEditor() {
        let data = {};
        try {
            const res = await fetch('/api/config_file');
            data = res.ok ? await res.json() : {};
        } catch (e) {
            console.error('Failed to load config file:', e);
        }
        getConfigFileEditor().setValue(data.content || '');
        const pathEl = document.getElementById('configFilePath');
        const noticeEl = document.getElementById('configFileNotice');
        if (pathEl && data.path) {
            pathEl.textContent = data.path;
        }
        if (noticeEl) {
            if (data.preview) {
                noticeEl.textContent = '当前为预览内容（文件尚未写入磁盘），保存后生效';
                noticeEl.hidden = false;
            } else if (data.managed_manually) {
                noticeEl.textContent = 'LiteLLM 路由处于手动接管状态：基础模式表单的保存将被拒绝';
                noticeEl.hidden = false;
            } else {
                noticeEl.hidden = true;
            }
        }
    }

    // Restore persisted advanced-mode toggle state, then show the matching view
    // (the advanced view is an independent CodeMirror editor, not the basic form).
    advancedModeToggle.checked = localStorage.getItem('openi_advanced_mode') === '1';
    basicConfigView.hidden = advancedModeToggle.checked;
    advancedConfigView.hidden = !advancedModeToggle.checked;

    advancedModeToggle.addEventListener('change', () => {
        const on = advancedModeToggle.checked;
        localStorage.setItem('openi_advanced_mode', on ? '1' : '0');
        basicConfigView.hidden = on;
        if (on) {
            advancedConfigView.hidden = false;
            refreshConfigFileEditor();
        } else {
            advancedConfigView.hidden = true;
        }
    });

    document.getElementById('settingsBtn').addEventListener('click', () => {
        settingsModal.classList.add('open');
        if (isAdvancedMode()) {
            refreshConfigFileEditor();
        }
    });
    document.getElementById('closeSettingsBtn').addEventListener('click', () => {
        settingsModal.classList.remove('open');
    });
    document.getElementById('toggleTokenVisibility').addEventListener('click', () => {
        const input = document.getElementById('apiTokenInput');
        const icon = document.querySelector('#toggleTokenVisibility i');
        if (input.type === 'password') {
            input.type = 'text';
            icon.className = 'fa-solid fa-eye-slash';
        } else {
            input.type = 'password';
            icon.className = 'fa-solid fa-eye';
        }
    });
    document.getElementById('saveSettingsBtn').addEventListener('click', async () => {
        if (isAdvancedMode()) {
            let success = false;
            let message = 'config.yaml 已保存并应用';
            try {
                const res = await fetch('/api/config_file', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: getConfigFileEditor().getValue() }),
                });
                const data = await res.json().catch(() => ({}));
                success = res.ok;
                if (!success) {
                    message = data.message || `写入失败（HTTP ${res.status}）`;
                } else if (data.message) {
                    message = data.message;
                }
            } catch (e) {
                message = '写入服务器配置文件失败: ' + e.message;
            }
            if (success) {
                settingsModal.classList.remove('open');
            }
            showFloatingNotification(message);
            return;
        }

        const url = apiUrlInput.value.trim();
        const token = document.getElementById('apiTokenInput').value.trim();
        const model = document.getElementById('modelInput').value.trim();

        const saved = await saveApiConfig(url, token, model);
        if (saved.ok) {
            settingsModal.classList.remove('open');
            showFloatingNotification('上游模型配置已保存，LiteLLM 代理已更新');
            return;
        }
        if (saved.errorCode === 'CONFIG_MANAGED_MANUALLY') {
            showFloatingNotification(saved.message || 'LiteLLM 路由处于手动接管状态，请在高级模式中手动配置');
            if (!isAdvancedMode()) {
                advancedModeToggle.checked = true;
                localStorage.setItem('openi_advanced_mode', '1');
                basicConfigView.hidden = true;
                advancedConfigView.hidden = false;
                refreshConfigFileEditor();
            }
            return;
        }
        showFloatingNotification(saved.message || '写入服务器配置失败');
    });

    document.getElementById('resetSettingsBtn').addEventListener('click', () => {
        fetch('/api/get_config')
            .then(res => res.json())
            .then(data => {
                document.getElementById('apiUrlInput').value = data.default_url;
                document.getElementById('apiTokenInput').value = '';
                document.getElementById('modelInput').value = data.default_model;
                if (isAdvancedMode()) {
                    refreshConfigFileEditor();
                }
            });
    });

    // GPU Status Modal
    const gpuModal = document.getElementById('gpuModal');
    document.getElementById('gpuDashboard').addEventListener('click', () => {
        gpuModal.classList.add('open');
        state.isGpuModalOpen = true;
    });
    document.getElementById('closeGpuBtn').addEventListener('click', () => {
        gpuModal.classList.remove('open');
        state.isGpuModalOpen = false;
    });
    document.getElementById('closeGpuBottomBtn').addEventListener('click', () => {
        gpuModal.classList.remove('open');
        state.isGpuModalOpen = false;
    });

    // Sidebar Tabs navigation
    const aiAssistantTabBtn = document.getElementById('aiAssistantTabBtn');
    const execHistoryTabBtn = document.getElementById('execHistoryTabBtn');
    const varInspectorTabBtn = document.getElementById('varInspectorTabBtn');
    const aiAssistantTabContent = document.getElementById('aiAssistantTabContent');
    const execHistoryTabContent = document.getElementById('execHistoryTabContent');
    const varInspectorTabContent = document.getElementById('varInspectorTabContent');

    if (aiAssistantTabBtn && execHistoryTabBtn && varInspectorTabBtn) {
        const switchTab = (activeBtn, activeContent) => {
            [aiAssistantTabBtn, execHistoryTabBtn, varInspectorTabBtn].forEach(btn => btn.classList.remove('active'));
            [aiAssistantTabContent, execHistoryTabContent, varInspectorTabContent].forEach(content => content.classList.add('hidden'));
            
            activeBtn.classList.add('active');
            activeContent.classList.remove('hidden');
        };

        aiAssistantTabBtn.addEventListener('click', () => {
            switchTab(aiAssistantTabBtn, aiAssistantTabContent);
        });

        execHistoryTabBtn.addEventListener('click', () => {
            switchTab(execHistoryTabBtn, execHistoryTabContent);
            renderHistoryList();
        });

        varInspectorTabBtn.addEventListener('click', () => {
            switchTab(varInspectorTabBtn, varInspectorTabContent);
            updateVariablesInspector();
        });
    }

    // Clear history
    const clearHistoryBtn = document.getElementById('clearHistoryBtn');
    if (clearHistoryBtn) {
        clearHistoryBtn.addEventListener('click', () => {
            localStorage.removeItem('notebook_execution_history');
            renderHistoryList();
            showFloatingNotification('执行历史已清空！');
        });
    }

    const aiSidebar = document.getElementById('aiSidebar');
    const openSidebarBtn = document.getElementById('openSidebarFloatingBtn');
    
    document.getElementById('toggleSidebarBtn').addEventListener('click', () => {
        aiSidebar.classList.add('collapsed');
        openSidebarBtn.classList.remove('hidden');
    });

    openSidebarBtn.addEventListener('click', () => {
        aiSidebar.classList.remove('collapsed');
        openSidebarBtn.classList.add('hidden');
    });

    // Document click to de-activate cells
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.cell-container') && !e.target.closest('.action-btn') && !e.target.closest('.round-add-btn') && !e.target.closest('.hover-add-cell-trigger') && !e.target.closest('.sidebar-tabs')) {
            deactivateAllCells();
            triggerRender();
        }
    });

    // Keyboard Shortcuts
    document.addEventListener('keydown', (e) => {
        const isMac = navigator.platform.toUpperCase().indexOf('MAC') >= 0;
        const cmdOrCtrl = isMac ? e.metaKey : e.ctrlKey;
        const activeEl = document.activeElement;
        const isTextarea = activeEl && (activeEl.tagName === 'TEXTAREA' || activeEl.tagName === 'INPUT');
        
        // 1. Run Cell: Ctrl/Cmd + Enter
        if (cmdOrCtrl && e.key === 'Enter') {
            e.preventDefault();
            if (state.activeCellId) {
                runCell(state.activeCellId);
            }
            return;
        }

        // 2. Run and Jump/Create: Shift + Enter
        if (e.shiftKey && e.key === 'Enter') {
            e.preventDefault();
            if (state.activeCellId) {
                const currentIdx = state.cells.findIndex(c => c.id === state.activeCellId);
                runCell(state.activeCellId);
                
                if (currentIdx !== -1) {
                    if (currentIdx + 1 < state.cells.length) {
                        const nextCell = state.cells[currentIdx + 1];
                        state.activeCellId = nextCell.id;
                    } else {
                        addCell('code');
                    }
                    triggerRender();
                    
                    // Focus next editor
                    setTimeout(() => {
                        const nextContainer = document.getElementById(state.activeCellId);
                        if (nextContainer) {
                            const ta = nextContainer.querySelector('textarea');
                            if (ta) ta.focus();
                        }
                    }, 50);
                }
            }
            return;
        }

        // 3. Save: Ctrl/Cmd + S
        if (cmdOrCtrl && e.key === 's') {
            e.preventDefault();
            saveNotebookToLocalStorage();
            showFloatingNotification('Notebook 已保存！');
            return;
        }

        // 4. Defocus/Esc to exit edit mode
        if (e.key === 'Escape') {
            if (isTextarea) {
                activeEl.blur();
                deactivateAllCells();
                triggerRender();
            }
            return;
        }

        // 5. Command Mode (non-editor shortcuts)
        if (!isTextarea && state.activeCellId) {
            const currentIdx = state.cells.findIndex(c => c.id === state.activeCellId);
            if (currentIdx === -1) return;

            // Ctrl/Cmd + A: Add Cell Above
            if (cmdOrCtrl && e.key === 'a') {
                e.preventDefault();
                addCell('code', currentIdx);
                triggerRender();
                return;
            }

            // Ctrl/Cmd + B: Add Cell Below
            if (cmdOrCtrl && e.key === 'b') {
                e.preventDefault();
                addCell('code', currentIdx + 1);
                triggerRender();
                return;
            }

            // Ctrl/Cmd + D: Delete Cell
            if (cmdOrCtrl && e.key === 'd') {
                e.preventDefault();
                deleteCell(state.activeCellId);
                triggerRender();
                showFloatingNotification('单元格已删除！');
                return;
            }

            // Ctrl/Cmd + Z: Cell-Level Undo
            if (cmdOrCtrl && e.key === 'z') {
                e.preventDefault();
                const restored = restoreLastDeletedCell();
                if (restored) {
                    triggerRender();
                    showFloatingNotification('已撤销删除单元格！');
                } else {
                    showFloatingNotification('没有可撤销的删除记录');
                }
                return;
            }
        }
    });
}

// Execute Python Code Kernel Route (SSE streaming with auto fallback)
function runCell(id) {
    const cell = state.cells.find(c => c.id === id);
    if (!cell || cell.type !== 'code') return;
    if (cell.isExecuting) return; // guard against re-entrant runs on the same cell

    // Assign the execution count up front (matches Jupyter semantics: a count
    // is consumed even if the cell later errors or is interrupted).
    state.executionCounter++;
    cell.executionIndex = state.executionCounter;
    cell.isExecuting = true;
    cell.success = true;

    // Discard any previous output area so the new execution starts clean
    // (otherwise renderer.js would preserve the old streamed DOM for the
    // now-executing cell). Then render once to create the cell DOM; the
    // renderer ensures an empty .cell-output-area exists for the executing
    // cell. Subsequent stream messages update that container directly (no
    // full re-render) so CodeMirror editors keep their state and focus.
    const prevCellEl = document.getElementById(cell.id);
    if (prevCellEl) {
        const prevArea = prevCellEl.querySelector('.cell-output-area');
        if (prevArea) prevArea.remove();
    }
    triggerRender();
    setKernelStatus('busy', '正在执行 Python 代码…');

    const cellEl = document.getElementById(cell.id);
    let outputArea = cellEl && cellEl.querySelector('.cell-output-area');
    if (!outputArea) {
        // Defensive: create one manually if the renderer didn't.
        outputArea = document.createElement('div');
        outputArea.className = 'cell-output-area';
        if (cellEl) cellEl.appendChild(outputArea);
    }

    const streamRenderer = new StreamOutputRenderer(outputArea);
    const client = new SSEKernelClient();
    activeSseClients.set(cell.id, client);
    const startedAt = performance.now();

    client.executeStream(cell.content, {
        onStream: (name, text) => streamRenderer.handleStream(name, text),
        onDisplayData: (data, metadata) => streamRenderer.handleDisplayData(data, metadata),
        onResult: (data, _count) => streamRenderer.handleResult(data, cell.executionIndex),
        onError: (ename, evalue, traceback) => streamRenderer.handleError(ename, evalue, traceback),
        onStatus: (execState) => {
            streamRenderer.handleStatus(execState);
            if (execState === 'busy') setKernelStatus('busy', '正在执行 Python 代码…');
        },
        onDone: () => {
            cell.output = streamRenderer.getAccumulatedOutput();
            // If the client was aborted, the kernel's exit path didn't reach
            // us as a clean error — surface it as a failure so the UI shows
            // the AI debug bar and the cell is marked unsuccessful. Also
            // synthesise a stderr line so history / .ipynb exports reflect
            // the interruption explicitly.
            const wasInterrupted = client.wasAborted();
            if (wasInterrupted) {
                cell.output.stderr = (cell.output.stderr || '') + '\nKeyboardInterrupt: 用户中断执行';
            }
            cell.success = !streamRenderer.hasError() && !wasInterrupted;
            cell.elapsedTime = (performance.now() - startedAt) / 1000;
            cell.isExecuting = false;
            activeSseClients.delete(cell.id);
            setKernelStatus('online', 'Python 3 (天数智芯 BI-150)');
            const out = cell.output || {};
            const summary = (out.stdout && out.stdout.trim())
                || (out.stderr && out.stderr.trim())
                || (cell.success ? '执行完成' : (wasInterrupted ? '执行被中断' : '执行出错'));
            saveExecutionToHistory(cell.content, cell.success, summary);
            // Finalize the executing cell in place: reset the gutter/run button
            // and append the AI debug bar on failure, WITHOUT a full re-render
            // (preserves the streamed DOM, including Out[N] results).
            finalizeCellExecution(cell);
            saveNotebookToLocalStorage();
            updateVariablesInspector();
        },
    });
}

// Finalize a cell's executing UI in place after streaming completes, without
// a full re-render (preserves the streamed output DOM). Resets the gutter
// count and run button, and appends/removes the AI debug bar based on success.
function finalizeCellExecution(cell) {
    const cellEl = document.getElementById(cell.id);
    if (!cellEl) return;
    const runBtn = cellEl.querySelector('.run-cell-btn');
    if (runBtn) {
        runBtn.innerHTML = '<i class="fa-solid fa-play" aria-hidden="true"></i>';
        runBtn.setAttribute('aria-label', '运行单元格');
    }
    const count = cellEl.querySelector('.execution-count');
    if (count) {
        count.innerText = cell.executionIndex ? `[${cell.executionIndex}]` : '[ ]';
    }
    const existingDebug = cellEl.querySelector('.ai-debug-bar');
    if (!cell.success) {
        if (!existingDebug) {
            cellEl.appendChild(renderAiDebugBar(cell, rendererCallbacks));
        }
    } else if (existingDebug) {
        existingDebug.remove();
    }
}

// Thin wrapper kept for existing call sites; delegates to the shared
// KernelIndicator instance so the DOM manipulation lives in one place.
// `statusClass` is one of: 'online' | 'busy' | 'error' | 'disconnected'.
// ('online' is the legacy name for the design-doc 'idle' state.)
function setKernelStatus(statusClass, text) {
    const state = statusClass === 'online' ? 'idle' : statusClass;
    kernelIndicator.setState(state, text);
}

// Real-time GPU Telemetry updates
let gpuTelemetryInterval = null;

function startGpuTelemetry() {
    fetchGpuStatus()
        .then(data => {
            const gpuDashboard = document.getElementById('gpuDashboard');
            if (!data.gpu_available) {
                if (gpuDashboard) {
                    gpuDashboard.style.display = '';
                    gpuDashboard.classList.add('no-gpu');
                    gpuDashboard.title = '未检测到天数智芯 GPU 驱动（pynvml 不可用），遥测已降级为占位数据';
                    const utilVal = document.getElementById('gpuUtilVal');
                    const vramVal = document.getElementById('gpuVramVal');
                    const powerVal = document.getElementById('gpuPowerVal');
                    const tempVal = document.getElementById('gpuTempVal');
                    if (utilVal) utilVal.innerText = '--';
                    if (vramVal) vramVal.innerText = '无 GPU';
                    if (powerVal) powerVal.innerText = '--';
                    if (tempVal) tempVal.innerText = '--';
                }
                return;
            }
            if (gpuDashboard) {
                gpuDashboard.style.display = '';
                gpuDashboard.classList.remove('no-gpu');
            }
            updateGpuDisplay(data);
            gpuTelemetryInterval = setInterval(() => {
                fetchGpuStatus()
                    .then(updateGpuDisplay)
                    .catch(err => console.error("GPU Telemetry fetch failed:", err));
            }, 1500);
        })
        .catch(err => {
            console.error("GPU Telemetry fetch failed:", err);
        });
}

function updateGpuDisplay(data) {
    // Update Top mini dashboard
    const utilBar = document.getElementById('gpuUtilBar');
    const utilVal = document.getElementById('gpuUtilVal');
    const vramBar = document.getElementById('gpuVramBar');
    const vramVal = document.getElementById('gpuVramVal');
    const powerVal = document.getElementById('gpuPowerVal');
    const tempVal = document.getElementById('gpuTempVal');

    if (utilBar) utilBar.style.width = `${data.utilization}%`;
    if (utilVal) utilVal.innerText = `${data.utilization}%`;
    
    const vramPercent = data.vram_total > 0 ? (data.vram_used / data.vram_total) * 100 : 0;
    if (vramBar) vramBar.style.width = `${vramPercent}%`;
    if (vramVal) vramVal.innerText = `${data.vram_used}MB / ${Math.round(data.vram_total / 1024)}GB`;
    
    if (powerVal) powerVal.innerText = `${data.power_draw} W`;
    if (tempVal) tempVal.innerText = `${data.temperature}°C`;

    // If Details Modal is open, update modal fields
    if (state.isGpuModalOpen) {
        const modalTemp = document.getElementById('gpuModalTemp');
        const modalPower = document.getElementById('gpuModalPower');
        const modalStatus = document.getElementById('gpuModalStatus');
        const modalVramUsed = document.getElementById('gpuModalVramUsed');
        const modalVramBar = document.getElementById('gpuModalVramBar');

        if (modalTemp) modalTemp.innerText = `${data.temperature}°C`;
        if (modalPower) modalPower.innerText = `${data.power_draw} W`;
        if (modalStatus) modalStatus.innerText = data.status;
        if (modalVramUsed) modalVramUsed.innerText = `${data.vram_used} MB`;
        if (modalVramBar) modalVramBar.style.width = `${vramPercent}%`;
    }
}

// AI Copilot Code generation inside cell
async function runCellAiAssist(id, prompt, buttonElement) {
    const cell = state.cells.find(c => c.id === id);
    if (!cell) return;

    const originalText = buttonElement.innerText;
    buttonElement.innerText = "生成中…";
    buttonElement.disabled = true;

    // Initialize the suggestion structure
    cell.aiSuggestion = {
        code: '',
        prompt: prompt,
        isGenerating: true
    };
    
    triggerRender();

    const previewContainer = document.getElementById(`suggestion_preview_${cell.id}`);
    const codeElement = previewContainer ? previewContainer.querySelector('pre code') : null;

    // Build context
    let contextText = "";
    const includeContextEl = document.getElementById('includeContextCheckbox');
    const includeContext = includeContextEl ? includeContextEl.checked : false;
    if (includeContext) {
        const cellIdx = state.cells.findIndex(c => c.id === id);
        if (cellIdx > 0) {
            contextText = "以下是当前单元格前的所有单元格代码与执行输出，供你参考变量、导入的库和上下文：\n\n";
            for (let i = 0; i < cellIdx; i++) {
                const c = state.cells[i];
                contextText += `[单元格 ${i+1}] (类型: ${c.type})\n`;
                contextText += `--- 代码/内容 ---\n${c.content}\n`;
                if (c.output) {
                    if (c.output.stdout) contextText += `--- 标准输出 ---\n${c.output.stdout}\n`;
                    if (c.output.stderr) contextText += `--- 报错输出 ---\n${c.output.stderr}\n`;
                }
                contextText += '\n';
            }
        }
    }

    let userMsgContent = "";
    if (contextText) {
        userMsgContent += contextText + "\n请结合以上上下文，编写/修改以下单元格代码。\n\n";
    }
    userMsgContent += `原单元格代码：\n${cell.content}\n\n我的提示词：\n${prompt}`;

    const messages = [
        {
            role: 'system',
            content: `你是一个部署在天数智芯(Iluvatar Corex) AI 开发环境下的代码助理。
用户输入一段提示词，你需要帮用户编写出干净、高效的 Python 代码。
不要输出任何 markdown 格式 of 解释，也不要使用 \`\`\` 包裹代码。
只需直接输出可运行的代码，且如果是加速计算代码，默认在 GPU (比如 PyTorch 中使用 cuda 设备，天数智芯兼容 CUDA API) 上运行。`
        },
        {
            role: 'user',
            content: userMsgContent
        }
    ];

    const cleanLlmCode = (rawText) => {
        let cleanCode = rawText;
        if (cleanCode.startsWith('```python')) {
            cleanCode = cleanCode.substring(9);
        } else if (cleanCode.startsWith('```')) {
            cleanCode = cleanCode.substring(3);
        }
        if (cleanCode.endsWith('```')) {
            cleanCode = cleanCode.substring(0, cleanCode.length - 3);
        }
        return cleanCode.trim();
    };

    try {
        await callLlmProxyStream(
            messages,
            (chunkText) => {
                const cleaned = cleanLlmCode(chunkText);
                cell.aiSuggestion.code = cleaned;
                if (codeElement) {
                    codeElement.innerText = cleaned;
                }
            }
        );
        
        cell.aiSuggestion.isGenerating = false;
        triggerRender();
        saveNotebookToLocalStorage();
        showFloatingNotification('AI 代码生成完毕！');
    } catch (e) {
        console.warn("AI Copilot streaming failed, falling back to non-streaming:", e);
        try {
            const reply = await callLlmProxy(messages);
            const cleaned = cleanLlmCode(reply);
            cell.aiSuggestion.code = cleaned;
            cell.aiSuggestion.isGenerating = false;
            triggerRender();
            saveNotebookToLocalStorage();
            showFloatingNotification('AI 代码生成完毕！');
        } catch (fallbackErr) {
            console.error(fallbackErr);
            alert("AI 代码生成失败: " + fallbackErr.message + "\n请检查 [设置] 中的 API 端点及 Token 配置是否正确。");
            delete cell.aiSuggestion;
            triggerRender();
        }
    } finally {
        buttonElement.innerText = originalText;
        buttonElement.disabled = false;
        
        // Clear the input field
        const containerEl = document.getElementById(cell.id);
        if (containerEl) {
            const inputField = containerEl.querySelector('.ai-assist-input');
            if (inputField) inputField.value = '';
        }
    }
}

async function runCellDebug(id, buttonElement) {
    const cell = state.cells.find(c => c.id === id);
    if (!cell || !cell.output || !cell.output.stderr) return;
    const originalText = buttonElement.innerHTML;
    buttonElement.innerHTML = '<i class="fa-solid fa-spinner loading-icon" style="display:inline-block" aria-hidden="true"></i> 诊断中…';
    buttonElement.disabled = true;
    const text = `调试单元格代码 (错误诊断)\n\n我的代码：\n\`\`\`python\n${cell.content}\n\`\`\`\n\n执行报错 (Traceback)：\n${cell.output.stderr}\n\n请分析原因并给出修复后的完整代码。`;
    const sent = sendToChainlit(text);
    if (sent) {
        showFloatingNotification('已将诊断请求发送至 AI 助手');
        setTimeout(() => { buttonElement.innerHTML = originalText; buttonElement.disabled = false; }, 800);
        return;
    }
    buttonElement.innerHTML = originalText;
    buttonElement.disabled = false;
    showFloatingNotification('AI 助手未就绪，请在右侧 AI 助手手动提问');
}

async function sendChatMessage() {
    const chatInput = document.getElementById('chatInput');
    if (!chatInput) return;
    const query = chatInput.value.trim();
    if (!query) return;
    if (sendToChainlit(query)) {
        chatInput.value = '';
        return;
    }
    chatInput.value = '';
    appendChatMessage('user', query);

    // Conversation history prior to this turn (excludes the query itself).
    const history = window._agentChatHistory || [];

    const includeContextEl = document.getElementById('includeContextCheckbox');
    const includeContext = includeContextEl ? includeContextEl.checked : false;

    // Add thinking loader
    const loaderId = 'loader_' + Math.random().toString(36).substr(2, 9);
    const chatHistory = document.getElementById('chatHistory');

    const loaderMsg = document.createElement('div');
    loaderMsg.className = 'chat-message assistant';
    loaderMsg.id = loaderId;
    loaderMsg.innerHTML = `
        <div class="chat-avatar"><i class="fa-solid fa-robot" aria-hidden="true"></i></div>
        <div class="chat-bubble">
            <span style="color:var(--text-muted)"><i class="fa-solid fa-compass-drafting loading-icon" style="display:inline-block;animation:spin 1.5s linear infinite" aria-hidden="true"></i> 思考中，请稍候…</span>
        </div>
    `;
    if (chatHistory) {
        chatHistory.appendChild(loaderMsg);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    let streamMessage = null;
    let assistantBlock = null;
    let toolLogEl = null;
    const toolLogs = [];

    const ensureAssistantBlock = () => {
        if (assistantBlock) return assistantBlock;
        assistantBlock = document.createElement('div');
        assistantBlock.className = 'chat-message assistant agent-assistant-block';
        assistantBlock.innerHTML = `
            <div class="chat-avatar"><i class="fa-solid fa-robot" aria-hidden="true"></i></div>
            <div class="chat-bubble"></div>
        `;
        if (chatHistory) {
            chatHistory.appendChild(assistantBlock);
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }
        return assistantBlock;
    };

    const appendToolLog = (name, summary, ok) => {
        const block = ensureAssistantBlock();
        toolLogs.push({ name, summary, ok });
        if (toolLogEl && toolLogEl.parentNode) toolLogEl.parentNode.removeChild(toolLogEl);
        toolLogEl = document.createElement('div');
        toolLogEl.className = 'agent-tool-log';
        let html = '';
        toolLogs.forEach((t) => {
            const icon = t.ok ? 'fa-check' : 'fa-triangle-exclamation';
            html += `<div class="agent-tool-log-item"><i class="fa-solid ${icon}" aria-hidden="true"></i><span class="agent-tool-name">${t.name}</span><span class="agent-tool-summary">${escapeHtml(t.summary)}</span></div>`;
        });
        toolLogEl.innerHTML = html;
        block.querySelector('.chat-bubble').appendChild(toolLogEl);
        if (chatHistory) chatHistory.scrollTop = chatHistory.scrollHeight;
    };

    const removeLoader = () => {
        const loader = document.getElementById(loaderId);
        if (loader) loader.remove();
    };

    const failWith = (message) => {
        removeLoader();
        appendChatMessage('assistant', `⚠️ 交互出错：${message}\n请检查您的网络以及在 [设置] 中检查您的 API Endpoint 或 Access Token。`);
    };

    try {
        await callAgentStream(
            {
                query,
                messages: history,
                includeContext,
                maxSteps: 0
            },
            {
                onStatus: () => {},
                onToolCall: (evt) => {
                    appendToolLog(evt.label || evt.name, '调用中…', true);
                    if (evt.name === 'create_cell') {
                        const code = (evt.arguments && evt.arguments.code) || '';
                        const cellType = (evt.arguments && evt.arguments.cell_type) || 'code';
                        const idx = evt.arguments && (evt.arguments.index ?? evt.arguments.position);
                        if (code && code.trim()) {
                            insertAgentCell(code, { cell_type: cellType, index: idx, ok: true });
                        }
                    } else if (evt.name === 'run_cell') {
                        const idx = evt.arguments && (evt.arguments.cell_index || evt.arguments.cellId || evt.arguments.cell_id);
                        const nIdx = idx != null ? parseInt(idx, 10) : NaN;
                        if (!isNaN(nIdx) && nIdx >= 1 && nIdx <= state.cells.length) {
                            const target = state.cells[nIdx - 1];
                            if (target && target.type === 'code') {
                                target.isExecuting = true;
                                state.executionCounter++;
                                target.executionIndex = state.executionCounter;
                                triggerRender();
                            }
                        }
                    }
                },
                onToolResult: (evt) => {
                    appendToolLog(evt.label || evt.name, evt.summary || '完成', evt.ok);
                    if (evt.name === 'create_cell' && evt.ok) {
                        const data = evt.data || {};
                        const code = (evt.arguments && evt.arguments.code) || data.code || '';
                        const cellType = (evt.arguments && evt.arguments.cell_type) || data.cell_type || 'code';
                        const idx = (evt.arguments && (evt.arguments.index ?? evt.arguments.position)) ?? data.index;
                        const alreadyInserted = state.cells.some(c => c.content === code);
                        if (code && code.trim() && !alreadyInserted) {
                            insertAgentCell(code, { cell_type: cellType, index: idx, ok: true });
                        }
                    } else if (evt.name === 'run_cell') {
                        const data = evt.data || {};
                        const idx = (evt.arguments && (evt.arguments.cell_index || evt.arguments.cellId || evt.arguments.cell_id)) || data.cell_index;
                        const nIdx = idx != null ? parseInt(idx, 10) : NaN;
                        const stdout = evt.stdout || '';
                        const stderr = evt.stderr || '';
                        if (!isNaN(nIdx) && nIdx >= 1 && nIdx <= state.cells.length) {
                            const target = state.cells[nIdx - 1];
                            if (target && target.type === 'code') {
                                target.isExecuting = false;
                                target.success = !!evt.ok;
                                target.output = { stdout: stdout || '', stderr: stderr || '', html: '', plots: [] };
                                if (!evt.ok && !stderr) target.output.stderr = evt.summary || '执行出错';
                                if (!stdout && !stderr && evt.ok) target.output.stdout = evt.summary || '执行完成';
                                triggerRender();
                                saveNotebookToLocalStorage();
                                updateVariablesInspector();
                            }
                        } else if (!isNaN(nIdx)) {
                            showFloatingNotification(evt.summary || (evt.ok ? `单元格 ${nIdx} 执行完成` : `单元格 ${nIdx} 执行失败`));
                        }
                    }
                },
                onContent: (chunkText) => {
                    removeLoader();
                    if (!streamMessage) {
                        const block = ensureAssistantBlock();
                        streamMessage = appendStreamingBlock(block, chunkText);
                    } else {
                        streamMessage.update(chunkText);
                    }
                },
                onError: (evt) => {
                    removeLoader();
                },
                onDone: (finalText) => {
                    removeLoader();
                    finalText = finalText || '（助手没有返回内容）';
                    if (streamMessage) streamMessage.update(finalText);
                    else appendChatMessage('assistant', finalText);
                    window._agentChatHistory = (window._agentChatHistory || []).concat([
                        { role: 'user', content: query },
                        { role: 'assistant', content: finalText }
                    ]);
                }
            }
        );
    } catch (e) {
        console.warn("Agent chat failed, falling back to plain chat:", e);
        removeLoader();
        const plainMessages = [
            { role: 'system', content: `你是一个天数智芯 (Iluvatar Corex) 智能笔记本平台的 AI 助手。
你的目标是解答关于国产 AI 芯片架构、PyTorch/TensorFlow 开发调试，以及通用 Python 编程的问题。
如果用户要求编写代码，请务必保证代码规范，并优先适配天数智芯的加速卡（可兼容 PyTorch 的 cuda 库或常规 Python 库）。` }
        ];
        if (includeContext) {
            try {
                const ctx = await fetchAgentContext();
                plainMessages.push({ role: 'user', content: renderContextForPrompt(ctx) });
            } catch (ctxErr) {
                console.warn("Fetch context failed after agent fallback:", ctxErr);
            }
        }
        plainMessages.push({ role: 'user', content: query });

        try {
            await callLlmProxyStream(
                plainMessages,
                (chunkText) => {
                    removeLoader();
                    if (!streamMessage) streamMessage = appendStreamingChatMessage('assistant');
                    streamMessage.update(chunkText);
                }
            );
        } catch (secondErr) {
            console.warn("Streaming fallback failed, using non-streaming:", secondErr);
            try {
                const reply = await callLlmProxy(plainMessages);
                removeLoader();
                appendChatMessage('assistant', reply);
            } catch (thirdErr) {
                failWith(thirdErr.message);
            }
        }
    }
}

// Render a structured-context object into a short prompt block.
function renderContextForPrompt(ctx) {
    let parts = ['以下是当前内核实时采集的结构化上下文，供你参考：'];
    if (ctx && Array.isArray(ctx.variables) && ctx.variables.length) {
        const lines = ctx.variables.map(v => `- ${v.name} (${v.type}${v.shape ? ' shape=' + v.shape : ''}): ${v.repr}`);
        parts.push('活动变量：\n' + lines.join('\n'));
    }
    const outputs = (ctx && ctx.recent_outputs) || {};
    const outKeys = Object.keys(outputs);
    if (outKeys.length) {
        const lines = outKeys.sort((a, b) => parseInt(a) - parseInt(b)).map(k => `[Out ${k}] ${outputs[k]}`);
        parts.push('最近的输出：\n' + lines.join('\n'));
    }
    if (ctx && Array.isArray(ctx.recent_errors) && ctx.recent_errors.length) {
        ctx.recent_errors.forEach(e => parts.push(`最近错误：${e.title}\n${e.summary || ''}`));
    }
    return parts.join('\n\n');
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}

// Extracted & Deduplicated Code Block Actions Binder
function attachCodeBlockActions(container) {
    container.querySelectorAll('pre').forEach(pre => {
        if (pre.parentNode && pre.parentNode.style.position === 'relative') {
            return; // Already wrapped
        }
        
        const wrapper = document.createElement('div');
        wrapper.style.position = 'relative';
        pre.parentNode.insertBefore(wrapper, pre);
        wrapper.appendChild(pre);

        const actions = document.createElement('div');
        actions.style.position = 'absolute';
        actions.style.top = '4px';
        actions.style.right = '4px';
        actions.style.display = 'flex';
        actions.style.gap = '4px';

        const cpy = document.createElement('button');
        cpy.className = 'tb-btn';
        cpy.innerHTML = '<i class="fa-solid fa-copy" aria-hidden="true"></i>';
        cpy.title = '复制';
        cpy.setAttribute('aria-label', '复制代码');
        cpy.addEventListener('click', () => {
            navigator.clipboard.writeText(pre.innerText);
            showFloatingNotification('代码已复制！');
        });

        const insert = document.createElement('button');
        insert.className = 'tb-btn';
        insert.innerHTML = '<i class="fa-solid fa-plus" aria-hidden="true"></i> 插入';
        insert.title = '作为新单元格插入 Notebook';
        insert.addEventListener('click', () => {
            const newCell = addCell('code');
            newCell.content = pre.innerText;
            saveNotebookToLocalStorage();
            triggerRender();
            showFloatingNotification('已将代码插入笔记本！');
        });

        actions.appendChild(cpy);
        actions.appendChild(insert);
        wrapper.appendChild(actions);
    });
}

function appendChatMessage(sender, text) {
    const chatHistory = document.getElementById('chatHistory');
    if (!chatHistory) return;
    const msg = document.createElement('div');
    msg.className = `chat-message ${sender}`;
    
    const avatarIcon = sender === 'user' ? 'fa-user' : 'fa-robot';
    
    msg.innerHTML = `
        <div class="chat-avatar"><i class="fa-solid ${avatarIcon}" aria-hidden="true"></i></div>
        <div class="chat-bubble">
            ${parseMarkdown(text)}
        </div>
    `;
    
    attachCodeBlockActions(msg);

    chatHistory.appendChild(msg);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

function appendStreamingChatMessage(sender) {
    const chatHistory = document.getElementById('chatHistory');
    if (!chatHistory) return { update: () => {} };
    const msg = document.createElement('div');
    msg.className = `chat-message ${sender}`;
    
    const avatarIcon = sender === 'user' ? 'fa-user' : 'fa-robot';
    
    msg.innerHTML = `
        <div class="chat-avatar"><i class="fa-solid ${avatarIcon}" aria-hidden="true"></i></div>
        <div class="chat-bubble">
            <span class="streaming-text"></span>
        </div>
    `;
    
    chatHistory.appendChild(msg);
    chatHistory.scrollTop = chatHistory.scrollHeight;
    
    return {
        update: (text) => {
            const bubble = msg.querySelector('.chat-bubble');
            bubble.innerHTML = parseMarkdown(text);
            
            attachCodeBlockActions(bubble);
            
            chatHistory.scrollTop = chatHistory.scrollHeight;
        }
    };
}

// Append a streaming answer block *inside* an existing assistant message
// (below its tool logs) and return a streaming updater for it.
function appendStreamingBlock(assistantBlock, initialText) {
    const chatHistory = document.getElementById('chatHistory');
    const streamingBox = document.createElement('div');
    streamingBox.className = 'streaming-text';
    assistantBlock.querySelector('.chat-bubble').appendChild(streamingBox);

    const render = (text) => {
        streamingBox.innerHTML = parseMarkdown(text);
        attachCodeBlockActions(streamingBox);
        if (chatHistory) chatHistory.scrollTop = chatHistory.scrollHeight;
    };
    render(initialText);
    return { update: render };
}

// Save cell execution details to localStorage history log
function saveExecutionToHistory(code, success, outputText) {
    if (!code || !code.trim()) return;
    let history = [];
    try {
        const stored = localStorage.getItem('notebook_execution_history');
        if (stored) {
            history = JSON.parse(stored);
        }
    } catch (e) {
        console.error("Failed to load execution history:", e);
    }
    
    const newItem = {
        id: 'hist_' + Math.random().toString(36).substr(2, 9),
        timestamp: new Date().toLocaleTimeString('zh-CN', { hour12: false }),
        code: code,
        success: success,
        outputSummary: outputText ? outputText.substring(0, 150) : ''
    };
    
    history.unshift(newItem);
    if (history.length > 50) {
        history.pop();
    }
    
    localStorage.setItem('notebook_execution_history', JSON.stringify(history));
    
    const execHistoryTabBtn = document.getElementById('execHistoryTabBtn');
    if (execHistoryTabBtn && execHistoryTabBtn.classList.contains('active')) {
        renderHistoryList();
    }
}

// Render the side log of executed codes
function renderHistoryList() {
    const listContainer = document.getElementById('historyList');
    const countEl = document.getElementById('historyCount');
    if (!listContainer) return;
    
    listContainer.innerHTML = '';
    
    let history = [];
    try {
        const stored = localStorage.getItem('notebook_execution_history');
        if (stored) {
            history = JSON.parse(stored);
        }
    } catch (e) {
        console.error(e);
    }
    
    if (countEl) {
        countEl.innerText = history.length > 0 ? `共 ${history.length} 条记录` : '暂无历史记录';
    }
    
    if (history.length === 0) {
        listContainer.innerHTML = `
            <div style="text-align: center; color: var(--text-muted); font-size: 0.8rem; margin-top: 40px; padding: 0 10px;">
                <i class="fa-solid fa-clock-rotate-left" style="font-size: 1.8rem; margin-bottom: 12px; display: block; opacity: 0.25; color: var(--accent-purple);" aria-hidden="true"></i>
                暂无代码执行历史
            </div>
        `;
        return;
    }
    
    history.forEach(item => {
        const itemEl = document.createElement('div');
        itemEl.className = 'history-item';
        
        const metaEl = document.createElement('div');
        metaEl.className = 'history-item-meta';
        metaEl.innerHTML = `
            <span class="history-item-time"><i class="fa-solid fa-clock" aria-hidden="true"></i> ${item.timestamp}</span>
            <span class="history-item-badge ${item.success ? 'success' : 'error'}">${item.success ? '成功' : '失败'}</span>
        `;
        
        const codeEl = document.createElement('pre');
        codeEl.className = 'history-item-code';
        codeEl.innerText = item.code;
        
        const actionsEl = document.createElement('div');
        actionsEl.className = 'history-item-actions';
        
        const copyBtn = document.createElement('button');
        copyBtn.className = 'history-action-btn';
        copyBtn.innerHTML = '<i class="fa-solid fa-copy" aria-hidden="true"></i> 复制';
        copyBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            navigator.clipboard.writeText(item.code);
            showFloatingNotification('代码已复制！');
        });
        
        const restoreBtn = document.createElement('button');
        restoreBtn.className = 'history-action-btn';
        restoreBtn.innerHTML = '<i class="fa-solid fa-arrow-left-long" aria-hidden="true"></i> 恢复';
        restoreBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            let insertIdx = state.cells.length;
            if (state.activeCellId) {
                const currentIdx = state.cells.findIndex(c => c.id === state.activeCellId);
                if (currentIdx !== -1) {
                    insertIdx = currentIdx + 1;
                }
            }
            const newCell = addCell('code', insertIdx);
            newCell.content = item.code;
            saveNotebookToLocalStorage();
            triggerRender();
            showFloatingNotification('已恢复代码至新单元格！');
        });
        
        actionsEl.appendChild(copyBtn);
        actionsEl.appendChild(restoreBtn);
        
        itemEl.appendChild(metaEl);
        itemEl.appendChild(codeEl);
        itemEl.appendChild(actionsEl);
        listContainer.appendChild(itemEl);
    });
}

async function runCellExplain(id) {
    const cell = state.cells.find(c => c.id === id);
    if (!cell) return;
    const text = `解释以下代码的含义与作用：\n\`\`\`python\n${cell.content}\n\`\`\``;
    const sent = sendToChainlit(text);
    if (sent) {
        showFloatingNotification('已将解释请求发送至 AI 助手');
        return;
    }
    showFloatingNotification('AI 助手未就绪，请在右侧 AI 助手手动提问');
}

// Lifecycle Init: runs when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    // 1. Set state auto-save callback to server
    state.onSave = () => {
        if (state.currentFilename) {
            const ipynbData = exportNotebookAsIpynb();
            saveNotebookToServer(state.currentFilename, ipynbData)
                .catch(err => console.error("Auto-save to server failed:", err));
        }
    };

    initConfig().then((config) => {
        // Sync configuration fields in settings modal
        const apiEl = document.getElementById('apiUrlInput');
        const tokenEl = document.getElementById('apiTokenInput');
        const modelEl = document.getElementById('modelInput');
        
        if (apiEl) apiEl.value = config.url;
        if (tokenEl) tokenEl.value = config.token;
        if (modelEl) modelEl.value = config.model;

        // 2. Fetch server notebooks list and load active notebook
        fetchNotebooksList()
            .then(data => {
                if (data.success) {
                    state.notebookFiles = data.files;
                    const savedFilename = localStorage.getItem('notebook_current_filename');
                    
                    if (savedFilename && state.notebookFiles.includes(savedFilename)) {
                        selectNotebookFile(savedFilename);
                    } else if (state.notebookFiles.length > 0) {
                        selectNotebookFile(state.notebookFiles[0]);
                    } else {
                        createNewNotebook();
                    }
                } else {
                    // Fallback to local storage
                    loadSavedNotebook();
                    if (state.cells.length === 0) {
                        addInitialCells();
                    } else {
                        triggerRender();
                    }
                }
            })
            .catch(err => {
                console.warn("Failed to load notebooks from server, falling back to local storage:", err);
                loadSavedNotebook();
                if (state.cells.length === 0) {
                    addInitialCells();
                } else {
                    triggerRender();
                }
            });

        startGpuTelemetry();

        // Test hooks (no-op in production; only present so e2e suites can
        // drive state and renders without going through the UI).
        window.__appState = state;
        window.__triggerRender = triggerRender;
    });

    setupEventListeners();
    const termRoot = document.getElementById("terminalPanel");
    if (termRoot) {
        const termPanel = new TerminalPanel();
        termPanel.mount(termRoot);
        bindTerminalShortcuts(termPanel);
        window.__terminalPanel = termPanel;
    }
});
