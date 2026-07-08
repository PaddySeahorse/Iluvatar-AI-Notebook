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
    runCellOnBackend,
    callLlmProxy,
    callLlmProxyStream,
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
    activeEditors
} from './renderer.js';

// Rerender helper to keep view in sync with state changes
function triggerRender() {
    renderCells(state.cells, state.activeCellId, rendererCallbacks);
}

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
        content: `# 导入数学包，在天数智芯 GPU 上模拟一段随机计算并生成绘图
import numpy as np
import matplotlib.pyplot as plt

print("正在初始化天数智芯 BI-150 运算环境...")
x = np.linspace(0, 10, 100)
y = np.sin(x) * np.exp(-x/3)

# 打印变量，这些变量可以在下一个单元格中访问
total_points = len(x)
print(f"成功计算了 {total_points} 个数据点。")

# 绘图
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
    });

    // Settings Modal
    const settingsModal = document.getElementById('settingsModal');
    document.getElementById('settingsBtn').addEventListener('click', () => {
        settingsModal.classList.add('open');
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
    
    document.getElementById('saveSettingsBtn').addEventListener('click', () => {
        const url = document.getElementById('apiUrlInput').value.trim();
        const token = document.getElementById('apiTokenInput').value.trim();
        const model = document.getElementById('modelInput').value.trim();

        saveApiConfig(url, token, model);

        settingsModal.classList.remove('open');
        showFloatingNotification('配置已保存！');
    });

    document.getElementById('resetSettingsBtn').addEventListener('click', () => {
        fetch('/api/get_config')
            .then(res => res.json())
            .then(data => {
                document.getElementById('apiUrlInput').value = data.default_url;
                document.getElementById('apiTokenInput').value = '';
                document.getElementById('modelInput').value = data.default_model;
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

    // Sidebar AI Chat
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

    document.getElementById('sendChatBtn').addEventListener('click', sendChatMessage);
    document.getElementById('chatInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChatMessage();
        }
    });

    // Bind Quick prompts in chat
    document.querySelectorAll('.quick-prompt-pill').forEach(pill => {
        pill.addEventListener('click', (e) => {
            const prompt = e.target.getAttribute('data-prompt');
            if (prompt) {
                document.getElementById('chatInput').value = prompt;
                sendChatMessage();
            }
        });
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

// Execute Python Code Kernel Route
function runCell(id) {
    const cell = state.cells.find(c => c.id === id);
    if (!cell || cell.type !== 'code') return;

    cell.isExecuting = true;
    triggerRender();
    
    // Update top header status indicator
    setKernelStatus('busy', '正在执行 Python 代码…');

    runCellOnBackend(cell.content)
    .then(data => {
        state.executionCounter++;
        cell.executionIndex = state.executionCounter;
        cell.output = {
            stdout: data.stdout,
            stderr: data.stderr,
            html: data.html,
            plots: data.plots
        };
        cell.success = data.success;
        cell.elapsedTime = data.elapsed_time;
        saveExecutionToHistory(cell.content, data.success, data.stdout || data.stderr);
    })
    .catch(err => {
        cell.success = false;
        cell.output = {
            stdout: '',
            stderr: 'Kernel Error: ' + err.message,
            plots: []
        };
        saveExecutionToHistory(cell.content, false, err.message);
    })
    .finally(() => {
        cell.isExecuting = false;
        setKernelStatus('online', 'Python 3 (天数智芯 BI-150)');
        triggerRender();
        saveNotebookToLocalStorage();
        updateVariablesInspector();
    });
}

function setKernelStatus(statusClass, text) {
    const dot = document.querySelector('.status-dot');
    const textEl = document.querySelector('.status-text');
    
    if (dot) dot.className = `status-dot ${statusClass}`;
    if (textEl) textEl.innerText = text;
}

// Real-time GPU Telemetry updates
function startGpuTelemetry() {
    setInterval(() => {
        fetchGpuStatus()
            .then(data => {
                // Update Top mini dashboard
                const utilBar = document.getElementById('gpuUtilBar');
                const utilVal = document.getElementById('gpuUtilVal');
                const vramBar = document.getElementById('gpuVramBar');
                const vramVal = document.getElementById('gpuVramVal');
                const powerVal = document.getElementById('gpuPowerVal');
                const tempVal = document.getElementById('gpuTempVal');

                if (utilBar) utilBar.style.width = `${data.utilization}%`;
                if (utilVal) utilVal.innerText = `${data.utilization}%`;
                
                const vramPercent = (data.vram_used / data.vram_total) * 100;
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
            })
            .catch(err => console.error("GPU Telemetry fetch failed:", err));
    }, 1500);
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

// AI Debugger for error cell
async function runCellDebug(id, buttonElement) {
    const cell = state.cells.find(c => c.id === id);
    if (!cell || !cell.output || !cell.output.stderr) return;

    const originalText = buttonElement.innerHTML;
    buttonElement.innerHTML = '<i class="fa-solid fa-spinner loading-icon" style="display:inline-block" aria-hidden="true"></i> 诊断中…';
    buttonElement.disabled = true;

    const messages = [
        {
            role: 'system',
            content: `你是一个部署在天数智芯(Iluvatar Corex) AI 开发 environment 下的代码调试专家。
针对用户运行失败的代码以及异常 Traceback (Stderr)，分析其发生错误的原因，并提供修改后的正确完整代码。
格式：请先用一段简短、精确的中文说明出错原因（少于 150 字），然后输出一个修改后的完整代码块，代码块请用 \`\`\`python ... \`\`\` 包裹起来。`
        },
        {
            role: 'user',
            content: `我的代码：\n${cell.content}\n\n执行报错 (Traceback)：\n${cell.output.stderr}`
        }
    ];

    // Open Right Sidebar Chat
    const aiSidebar = document.getElementById('aiSidebar');
    const openSidebarBtn = document.getElementById('openSidebarFloatingBtn');
    if (aiSidebar) aiSidebar.classList.remove('collapsed');
    if (openSidebarBtn) openSidebarBtn.classList.add('hidden');

    // Append user query message
    appendChatMessage('user', `调试单元格代码 (错误诊断)`);

    // Add thinking loader in chat
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

    try {
        await callLlmProxyStream(
            messages,
            (chunkText) => {
                if (!streamMessage) {
                    const loader = document.getElementById(loaderId);
                    if (loader) loader.remove();
                    streamMessage = appendStreamingChatMessage('assistant');
                }
                streamMessage.update(chunkText);
            }
        );
    } catch (e) {
        console.warn("Streaming debug failed, falling back to non-streaming:", e);
        try {
            const reply = await callLlmProxy(messages);
            const loader = document.getElementById(loaderId);
            if (loader) loader.remove();
            appendChatMessage('assistant', reply);
        } catch (fallbackErr) {
            const loader = document.getElementById(loaderId);
            if (loader) loader.remove();
            appendChatMessage('assistant', `⚠️ 诊断出错: ${fallbackErr.message}\n请检查 API 配置。`);
        }
    } finally {
        buttonElement.innerHTML = originalText;
        buttonElement.disabled = false;
    }
}

// Sidebar Chat Flow
async function sendChatMessage() {
    const chatInput = document.getElementById('chatInput');
    const query = chatInput ? chatInput.value.trim() : '';
    if (!query) return;

    chatInput.value = '';
    appendChatMessage('user', query);

    // Build chat message payload
    const systemPrompt = `你是一个天数智芯 (Iluvatar Corex) 智能笔记本平台的 AI 助手。
你的目标是解答关于国产 AI 芯片架构、PyTorch/TensorFlow 开发调试，以及通用 Python 编程的问题。
如果用户要求编写代码，请务必保证代码规范，并优先适配天数智芯的加速卡（可兼容 PyTorch 的 cuda 库或常规 Python 库）。`;

    const messages = [
        { role: 'system', content: systemPrompt }
    ];

    // Read context if checked
    const includeContextEl = document.getElementById('includeContextCheckbox');
    const includeContext = includeContextEl ? includeContextEl.checked : false;
    if (includeContext && state.cells.length > 0) {
        let contextText = "以下是当前 Notebook 中的所有单元格代码与执行输出，供你参考：\n\n";
        state.cells.forEach((c, i) => {
            contextText += `[单元格 ${i+1}] (类型: ${c.type})\n`;
            contextText += `--- 代码/内容 ---\n${c.content}\n`;
            if (c.output) {
                if (c.output.stdout) contextText += `--- 标准输出 ---\n${c.output.stdout}\n`;
                if (c.output.stderr) contextText += `--- 报错输出 ---\n${c.output.stderr}\n`;
            }
            contextText += '\n';
        });
        messages.push({ role: 'user', content: contextText });
    }

    messages.push({ role: 'user', content: query });

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

    try {
        await callLlmProxyStream(
            messages,
            (chunkText) => {
                if (!streamMessage) {
                    const loader = document.getElementById(loaderId);
                    if (loader) loader.remove();
                    streamMessage = appendStreamingChatMessage('assistant');
                }
                streamMessage.update(chunkText);
            }
        );
    } catch (e) {
        console.warn("Streaming chat failed, falling back to non-streaming:", e);
        try {
            const reply = await callLlmProxy(messages);
            const loader = document.getElementById(loaderId);
            if (loader) loader.remove();
            appendChatMessage('assistant', reply);
        } catch (fallbackErr) {
            const loader = document.getElementById(loaderId);
            if (loader) loader.remove();
            appendChatMessage('assistant', `⚠️ 交互出错：${fallbackErr.message}\n请检查您的网络以及在 [设置] 中检查您的 API Endpoint 或 Access Token。`);
        }
    }
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

// AI Code Explanation inside Sidebar
async function runCellExplain(id) {
    const cell = state.cells.find(c => c.id === id);
    if (!cell) return;

    // Open Right Sidebar Chat & Switch to AI Assistant Tab
    const aiSidebar = document.getElementById('aiSidebar');
    const openSidebarBtn = document.getElementById('openSidebarFloatingBtn');
    if (aiSidebar) aiSidebar.classList.remove('collapsed');
    if (openSidebarBtn) openSidebarBtn.classList.add('hidden');

    const aiAssistantTabBtn = document.getElementById('aiAssistantTabBtn');
    const execHistoryTabBtn = document.getElementById('execHistoryTabBtn');
    const varInspectorTabBtn = document.getElementById('varInspectorTabBtn');
    const aiAssistantTabContent = document.getElementById('aiAssistantTabContent');
    const execHistoryTabContent = document.getElementById('execHistoryTabContent');
    const varInspectorTabContent = document.getElementById('varInspectorTabContent');

    if (aiAssistantTabBtn && execHistoryTabBtn && varInspectorTabBtn) {
        [aiAssistantTabBtn, execHistoryTabBtn, varInspectorTabBtn].forEach(btn => btn.classList.remove('active'));
        [aiAssistantTabContent, execHistoryTabContent, varInspectorTabContent].forEach(content => content.classList.add('hidden'));
        
        aiAssistantTabBtn.classList.add('active');
        aiAssistantTabContent.classList.remove('hidden');
    }

    // Append explanation query
    appendChatMessage('user', `解释以下代码的含义与作用：\n\`\`\`python\n${cell.content}\n\`\`\``);

    // Add thinking loader
    const loaderId = 'loader_' + Math.random().toString(36).substr(2, 9);
    const chatHistory = document.getElementById('chatHistory');
    
    const loaderMsg = document.createElement('div');
    loaderMsg.className = 'chat-message assistant';
    loaderMsg.id = loaderId;
    loaderMsg.innerHTML = `
        <div class="chat-avatar"><i class="fa-solid fa-robot" aria-hidden="true"></i></div>
        <div class="chat-bubble">
            <span style="color:var(--text-muted)"><i class="fa-solid fa-compass-drafting loading-icon" style="display:inline-block;animation:spin 1.5s linear infinite" aria-hidden="true"></i> 正在分析代码，请稍候…</span>
        </div>
    `;
    if (chatHistory) {
        chatHistory.appendChild(loaderMsg);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    const messages = [
        {
            role: 'system',
            content: `你是一个部署在天数智芯 (Iluvatar Corex) AI 开发环境下的代码解释专家。
请使用精简且专业的中文解释用户提供的 Python 代码的含义、结构、设计逻辑以及其作用。
如果代码中包含天数智芯国产算力/PyTorch加速相关的指令与设置，请重点解释说明。请以排版清晰的 markdown 格式输出。`
        },
        {
            role: 'user',
            content: `需要解释的代码：\n\`\`\`python\n${cell.content}\n\`\`\``
        }
    ];

    let streamMessage = null;

    try {
        await callLlmProxyStream(
            messages,
            (chunkText) => {
                if (!streamMessage) {
                    const loader = document.getElementById(loaderId);
                    if (loader) loader.remove();
                    streamMessage = appendStreamingChatMessage('assistant');
                }
                streamMessage.update(chunkText);
            }
        );
    } catch (e) {
        console.warn("Streaming code explanation failed, falling back to non-streaming:", e);
        try {
            const reply = await callLlmProxy(messages);
            const loader = document.getElementById(loaderId);
            if (loader) loader.remove();
            appendChatMessage('assistant', reply);
        } catch (fallbackErr) {
            const loader = document.getElementById(loaderId);
            if (loader) loader.remove();
            appendChatMessage('assistant', `⚠️ 解释出错: ${fallbackErr.message}\n请检查 [设置] 中的 API 配置。`);
        }
    }
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
    });

    setupEventListeners();
});
