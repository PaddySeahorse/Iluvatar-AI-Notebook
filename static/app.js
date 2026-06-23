// Global Application State
let cells = [];
let apiConfig = {
    url: '',
    token: '',
    model: ''
};
let isGpuModalOpen = false;
let activeCellId = null;

// Initialize the Application
document.addEventListener('DOMContentLoaded', () => {
    initConfig().then(() => {
        // Load default cells if none exist
        loadSavedNotebook();
        if (cells.length === 0) {
            // Add initial welcome cell and code cell
            addInitialCells();
        } else {
            renderCells();
        }
        
        // Start GPU telemetry updates
        startGpuTelemetry();
    });

    // Bind Global UI Elements
    setupEventListeners();
});

// Load Configuration from LocalStorage or Backend
async function initConfig() {
    const savedUrl = localStorage.getItem('openi_api_url');
    const savedToken = localStorage.getItem('openi_api_token');
    const savedModel = localStorage.getItem('openi_api_model');

    if (savedUrl !== null && savedToken !== null && savedModel !== null) {
        apiConfig.url = savedUrl;
        apiConfig.token = savedToken;
        apiConfig.model = savedModel;
    } else {
        try {
            const res = await fetch('/api/get_config');
            if (res.ok) {
                const data = await res.json();
                apiConfig.url = savedUrl || data.default_url;
                apiConfig.token = savedToken || data.default_token;
                apiConfig.model = savedModel || data.default_model;
            }
        } catch (e) {
            console.error("Failed to fetch config from backend:", e);
            apiConfig.url = savedUrl || 'https://token.openi.org.cn/v1/chat/completions';
            apiConfig.token = savedToken || '';
            apiConfig.model = savedModel || 'dsv4';
        }
    }

    // Update settings modal inputs
    document.getElementById('apiUrlInput').value = apiConfig.url;
    document.getElementById('apiTokenInput').value = apiConfig.token;
    document.getElementById('modelInput').value = apiConfig.model;
}

// Set up initial cells on empty notebook
function addInitialCells() {
    // Welcome Markdown Cell
    cells.push({
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
    cells.push({
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

    renderCells();
    saveNotebookToLocalStorage();
}

// Bind Page Event Listeners
function setupEventListeners() {
    // Notebook Title Update
    document.getElementById('notebookTitle').addEventListener('blur', saveNotebookToLocalStorage);

    // Top action buttons
    document.getElementById('addCodeBtn').addEventListener('click', () => addCell('code'));
    document.getElementById('addMarkdownBtn').addEventListener('click', () => addCell('markdown'));
    document.getElementById('addCodeBottomBtn').addEventListener('click', () => addCell('code'));
    document.getElementById('addMarkdownBottomBtn').addEventListener('click', () => addCell('markdown'));
    
    document.getElementById('clearAllOutputsBtn').addEventListener('click', () => {
        cells.forEach(c => {
            if (c.type === 'code') {
                c.output = null;
                c.elapsedTime = null;
                c.success = true;
            }
        });
        renderCells();
        saveNotebookToLocalStorage();
    });

    // Theme toggler (placeholder)
    document.getElementById('themeToggleBtn').addEventListener('click', () => {
        document.body.classList.toggle('light-theme');
        const icon = document.querySelector('#themeToggleBtn i');
        if (document.body.classList.contains('light-theme')) {
            icon.className = 'fa-solid fa-sun';
        } else {
            icon.className = 'fa-solid fa-moon';
        }
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
        apiConfig.url = document.getElementById('apiUrlInput').value.trim();
        apiConfig.token = document.getElementById('apiTokenInput').value.trim();
        apiConfig.model = document.getElementById('modelInput').value.trim();

        localStorage.setItem('openi_api_url', apiConfig.url);
        localStorage.setItem('openi_api_token', apiConfig.token);
        localStorage.setItem('openi_api_model', apiConfig.model);

        settingsModal.classList.remove('open');
        showFloatingNotification('配置已保存！');
    });

    document.getElementById('resetSettingsBtn').addEventListener('click', () => {
        fetch('/api/get_config')
            .then(res => res.json())
            .then(data => {
                document.getElementById('apiUrlInput').value = data.default_url;
                document.getElementById('apiTokenInput').value = data.default_token;
                document.getElementById('modelInput').value = data.default_model;
            });
    });

    // GPU Status Modal
    const gpuModal = document.getElementById('gpuModal');
    document.getElementById('gpuDashboard').addEventListener('click', () => {
        gpuModal.classList.add('open');
        isGpuModalOpen = true;
    });
    document.getElementById('closeGpuBtn').addEventListener('click', () => {
        gpuModal.classList.remove('open');
        isGpuModalOpen = false;
    });
    document.getElementById('closeGpuBottomBtn').addEventListener('click', () => {
        gpuModal.classList.remove('open');
        isGpuModalOpen = false;
    });

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
            document.getElementById('chatInput').value = e.target.getAttribute('data-prompt');
            sendChatMessage();
        });
    });

    // Document click to de-activate cells
    document.addEventListener('click', (e) => {
        if (!e.target.closest('.cell-container') && !e.target.closest('.action-btn') && !e.target.closest('.round-add-btn') && !e.target.closest('.hover-add-cell-trigger')) {
            deactivateAllCells();
        }
    });
}

// Save Notebook state to localStorage
function saveNotebookToLocalStorage() {
    const title = document.getElementById('notebookTitle').value;
    localStorage.setItem('notebook_title', title);
    localStorage.setItem('notebook_cells', JSON.stringify(cells));
}

// Load Notebook from localStorage
function loadSavedNotebook() {
    const title = localStorage.getItem('notebook_title');
    if (title) {
        document.getElementById('notebookTitle').value = title;
    }
    const savedCells = localStorage.getItem('notebook_cells');
    if (savedCells) {
        try {
            cells = JSON.parse(savedCells);
            // Ensure executing state is reset on load
            cells.forEach(c => {
                if (c.type === 'code') c.isExecuting = false;
            });
        } catch (e) {
            console.error("Failed to parse saved cells:", e);
            cells = [];
        }
    }
}

// Render cells list to DOM
function renderCells() {
    const container = document.getElementById('cellsList');
    container.innerHTML = '';

    cells.forEach((cell, index) => {
        // Create inter-cell hover add menu (except before the first cell, which is handled after)
        if (index > 0) {
            container.appendChild(createHoverAddBar(index));
        }

        const cellEl = document.createElement('div');
        cellEl.className = `cell-container ${cell.type} ${activeCellId === cell.id ? 'active' : ''}`;
        cellEl.id = cell.id;
        cellEl.setAttribute('data-index', index);

        // Click to activate cell
        cellEl.addEventListener('click', (e) => {
            if (activeCellId !== cell.id) {
                activateCell(cell.id);
            }
        });

        // 1. Cell Toolbar
        const toolbar = document.createElement('div');
        toolbar.className = 'cell-toolbar';
        
        const moveUpBtn = document.createElement('button');
        moveUpBtn.className = 'tb-btn';
        moveUpBtn.innerHTML = '<i class="fa-solid fa-arrow-up"></i>';
        moveUpBtn.title = '上移';
        moveUpBtn.disabled = index === 0;
        moveUpBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            moveCell(cell.id, -1);
        });

        const moveDownBtn = document.createElement('button');
        moveDownBtn.className = 'tb-btn';
        moveDownBtn.innerHTML = '<i class="fa-solid fa-arrow-down"></i>';
        moveDownBtn.title = '下移';
        moveDownBtn.disabled = index === cells.length - 1;
        moveDownBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            moveCell(cell.id, 1);
        });

        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'tb-btn delete';
        deleteBtn.innerHTML = '<i class="fa-solid fa-trash-can"></i>';
        deleteBtn.title = '删除';
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            deleteCell(cell.id);
        });

        toolbar.appendChild(moveUpBtn);
        toolbar.appendChild(moveDownBtn);
        toolbar.appendChild(deleteBtn);
        cellEl.appendChild(toolbar);

        // 2. Cell Content body
        const cellBody = document.createElement('div');
        cellBody.className = 'cell-body';

        // Gutter
        const gutter = document.createElement('div');
        gutter.className = 'cell-gutter';
        
        if (cell.type === 'code') {
            const runBtn = document.createElement('button');
            runBtn.className = 'run-cell-btn';
            runBtn.innerHTML = cell.isExecuting 
                ? '<i class="fa-solid fa-circle-notch loading-icon" style="display:block"></i>' 
                : '<i class="fa-solid fa-play"></i>';
            runBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                runCell(cell.id);
            });
            gutter.appendChild(runBtn);

            const count = document.createElement('div');
            count.className = 'execution-count';
            count.innerText = cell.isExecuting ? '[*]' : (cell.executionIndex ? `[${cell.executionIndex}]` : '[ ]');
            gutter.appendChild(count);
        } else {
            gutter.innerHTML = '<i class="fa-solid fa-paragraph" style="color:var(--text-muted);font-size:0.8rem;margin-top:10px;"></i>';
        }
        cellBody.appendChild(gutter);

        // Input Editor / Content Area
        const inputArea = document.createElement('div');
        inputArea.className = 'cell-input-area';

        if (cell.type === 'code') {
            const editor = document.createElement('textarea');
            editor.className = 'cell-editor';
            editor.value = cell.content;
            editor.placeholder = '在此输入 Python 代码...';
            editor.addEventListener('input', (e) => {
                cell.content = e.target.value;
                autoResizeTextarea(editor);
                saveNotebookToLocalStorage();
            });
            editor.addEventListener('focus', () => activateCell(cell.id));
            inputArea.appendChild(editor);
            
            // Auto resize on layout paint
            setTimeout(() => autoResizeTextarea(editor), 10);
            
            // AI Copilot Input Bar
            const copilotBar = document.createElement('div');
            copilotBar.className = 'cell-ai-assist-bar';
            copilotBar.innerHTML = `
                <i class="fa-solid fa-wand-magic-sparkles ai-icon-sparkle"></i>
                <input type="text" class="ai-assist-input" placeholder="✨ 描述需要帮您编写或优化的 Python 核心逻辑...">
                <button class="ai-assist-btn">AI 生成</button>
            `;
            
            const assistInput = copilotBar.querySelector('.ai-assist-input');
            const assistBtn = copilotBar.querySelector('.ai-assist-btn');
            
            const triggerAiAssist = (e) => {
                e.stopPropagation();
                const prompt = assistInput.value.trim();
                if (prompt) {
                    runCellAiAssist(cell.id, prompt, assistBtn);
                }
            };
            
            assistBtn.addEventListener('click', triggerAiAssist);
            assistInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    triggerAiAssist(e);
                }
            });
            
            inputArea.appendChild(copilotBar);
        } else {
            // Markdown Cell
            if (cell.isEditingMarkdown) {
                const editor = document.createElement('textarea');
                editor.className = 'cell-editor';
                editor.value = cell.content;
                editor.placeholder = '在此输入 Markdown 格式内容...';
                editor.addEventListener('input', (e) => {
                    cell.content = e.target.value;
                    autoResizeTextarea(editor);
                    saveNotebookToLocalStorage();
                });
                editor.addEventListener('blur', () => {
                    cell.isEditingMarkdown = false;
                    renderCells();
                    saveNotebookToLocalStorage();
                });
                inputArea.appendChild(editor);
                setTimeout(() => {
                    editor.focus();
                    autoResizeTextarea(editor);
                }, 10);
            } else {
                const rendered = document.createElement('div');
                rendered.className = 'markdown-rendered-view';
                rendered.innerHTML = parseMarkdown(cell.content);
                rendered.addEventListener('dblclick', () => {
                    cell.isEditingMarkdown = true;
                    renderCells();
                });
                inputArea.appendChild(rendered);
            }
        }
        
        cellBody.appendChild(inputArea);
        cellEl.appendChild(cellBody);

        // 3. Cell Output rendering
        if (cell.type === 'code' && cell.output) {
            const hasStdout = cell.output.stdout && cell.output.stdout.trim();
            const hasStderr = cell.output.stderr && cell.output.stderr.trim();
            const hasPlots = cell.output.plots && cell.output.plots.length > 0;

            if (hasStdout || hasStderr || hasPlots) {
                const outputArea = document.createElement('div');
                outputArea.className = 'cell-output-area';

                if (hasStdout) {
                    const pre = document.createElement('pre');
                    pre.className = 'output-stdout';
                    pre.innerText = cell.output.stdout;
                    outputArea.appendChild(pre);
                }

                if (hasStderr) {
                    const pre = document.createElement('pre');
                    pre.className = 'output-stderr';
                    pre.innerText = cell.output.stderr;
                    outputArea.appendChild(pre);
                }

                if (hasPlots) {
                    const plotsContainer = document.createElement('div');
                    plotsContainer.className = 'output-plots-container';
                    cell.output.plots.forEach(plotBase64 => {
                        const img = document.createElement('img');
                        img.className = 'output-plot-img';
                        img.src = `data:image/png;base64,${plotBase64}`;
                        plotsContainer.appendChild(img);
                    });
                    outputArea.appendChild(plotsContainer);
                }

                cellEl.appendChild(outputArea);
            }

            // 4. Debug Action overlay if run failed
            if (!cell.success && hasStderr) {
                const debugBar = document.createElement('div');
                debugBar.className = 'ai-debug-bar';
                debugBar.innerHTML = `
                    <span class="debug-text"><i class="fa-solid fa-triangle-exclamation"></i> 检测到运行出错，点击让 AI 进行智能诊断</span>
                    <button class="ai-debug-btn"><i class="fa-solid fa-bug-slash"></i> 一键 AI 调试</button>
                `;
                
                const debugBtn = debugBar.querySelector('.ai-debug-btn');
                debugBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    runCellDebug(cell.id, debugBtn);
                });
                
                cellEl.appendChild(debugBar);
            }
        }

        container.appendChild(cellEl);
    });
}

// Create the hover insert cell separator bar
function createHoverAddBar(index) {
    const trigger = document.createElement('div');
    trigger.className = 'hover-add-cell-trigger';
    
    const group = document.createElement('div');
    group.className = 'hover-add-btn-group';
    
    const addCode = document.createElement('button');
    addCode.className = 'hover-add-btn';
    addCode.innerHTML = '<i class="fa-solid fa-plus"></i> 代码';
    addCode.addEventListener('click', () => addCell('code', index));

    const addMd = document.createElement('button');
    addMd.className = 'hover-add-btn';
    addMd.innerHTML = '<i class="fa-solid fa-paragraph"></i> 文本';
    addMd.addEventListener('click', () => addCell('markdown', index));

    group.appendChild(addCode);
    group.appendChild(addMd);
    trigger.appendChild(group);
    
    return trigger;
}

// Manage Cell active focus state
function activateCell(id) {
    activeCellId = id;
    document.querySelectorAll('.cell-container').forEach(el => {
        if (el.id === id) {
            el.classList.add('active');
        } else {
            el.classList.remove('active');
        }
    });
}

function deactivateAllCells() {
    activeCellId = null;
    document.querySelectorAll('.cell-container').forEach(el => {
        el.classList.remove('active');
    });
}

// Textarea auto-expanding logic
function autoResizeTextarea(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = (textarea.scrollHeight) + 'px';
}

// Cell array manipulations
function addCell(type, index = null) {
    const newCell = {
        id: 'cell_' + Math.random().toString(36).substr(2, 9),
        type: type,
        content: '',
        output: null
    };

    if (type === 'code') {
        newCell.elapsedTime = null;
        newCell.success = true;
        newCell.isExecuting = false;
    } else {
        newCell.isEditingMarkdown = true;
    }

    if (index === null) {
        cells.push(newCell);
    } else {
        cells.splice(index, 0, newCell);
    }

    activeCellId = newCell.id;
    renderCells();
    saveNotebookToLocalStorage();
}

function deleteCell(id) {
    cells = cells.filter(c => c.id !== id);
    if (activeCellId === id) activeCellId = null;
    renderCells();
    saveNotebookToLocalStorage();
}

function moveCell(id, direction) {
    const idx = cells.findIndex(c => c.id === id);
    if (idx === -1) return;
    const targetIdx = idx + direction;
    if (targetIdx < 0 || targetIdx >= cells.length) return;

    // Swap items
    const temp = cells[idx];
    cells[idx] = cells[targetIdx];
    cells[targetIdx] = temp;

    renderCells();
    saveNotebookToLocalStorage();
}

// Execute Python Code Kernel Route
let executionCounter = 0;
function runCell(id) {
    const cell = cells.find(c => c.id === id);
    if (!cell || cell.type !== 'code') return;

    cell.isExecuting = true;
    renderCells();
    
    // Update top header status indicator
    setKernelStatus('busy', '正在执行 Python 代码...');

    fetch('/api/run_cell', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ code: cell.content })
    })
    .then(res => {
        if (!res.ok) throw new Error("Backend server response failed");
        return res.json();
    })
    .then(data => {
        executionCounter++;
        cell.executionIndex = executionCounter;
        cell.output = {
            stdout: data.stdout,
            stderr: data.stderr,
            plots: data.plots
        };
        cell.success = data.success;
        cell.elapsedTime = data.elapsed_time;
    })
    .catch(err => {
        cell.success = false;
        cell.output = {
            stdout: '',
            stderr: 'Kernel Error: ' + err.message,
            plots: []
        };
    })
    .finally(() => {
        cell.isExecuting = false;
        setKernelStatus('online', 'Python 3 (天数智芯 BI-150)');
        renderCells();
        saveNotebookToLocalStorage();
    });
}

function setKernelStatus(statusClass, text) {
    const dot = document.querySelector('.status-dot');
    const textEl = document.querySelector('.status-text');
    
    dot.className = `status-dot ${statusClass}`;
    textEl.innerText = text;
}

// Real-time GPU Telemetry updates
function startGpuTelemetry() {
    setInterval(() => {
        fetch('/api/gpu_status')
            .then(res => res.json())
            .then(data => {
                // Update Top mini dashboard
                document.getElementById('gpuUtilBar').style.width = `${data.utilization}%`;
                document.getElementById('gpuUtilVal').innerText = `${data.utilization}%`;
                
                const vramPercent = (data.vram_used / data.vram_total) * 100;
                document.getElementById('gpuVramBar').style.width = `${vramPercent}%`;
                document.getElementById('gpuVramVal').innerText = `${data.vram_used}MB / ${Math.round(data.vram_total / 1024)}GB`;
                
                document.getElementById('gpuPowerVal').innerText = `${data.power_draw} W`;
                document.getElementById('gpuTempVal').innerText = `${data.temperature}°C`;

                // If Details Modal is open, update modal fields
                if (isGpuModalOpen) {
                    document.getElementById('gpuModalTemp').innerText = `${data.temperature}°C`;
                    document.getElementById('gpuModalPower').innerText = `${data.power_draw} W`;
                    document.getElementById('gpuModalStatus').innerText = data.status;
                    document.getElementById('gpuModalVramUsed').innerText = `${data.vram_used} MB`;
                    document.getElementById('gpuModalVramBar').style.width = `${vramPercent}%`;
                }
            })
            .catch(err => console.error("GPU Telemetry fetch failed:", err));
    }, 1500);
}

// Proxy call to LLM Endpoint
async function callLlmProxy(messages) {
    const res = await fetch('/api/ai_call', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            url: apiConfig.url,
            token: apiConfig.token,
            model: apiConfig.model,
            messages: messages
        })
    });
    
    if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.message || `HTTP error ${res.status}`);
    }
    
    const data = await res.json();
    if (data.choices && data.choices[0] && data.choices[0].message) {
        return data.choices[0].message.content;
    }
    throw new Error("Invalid format returned by LLM endpoint");
}

// AI Copilot Code generation inside cell
async function runCellAiAssist(id, prompt, buttonElement) {
    const cell = cells.find(c => c.id === id);
    if (!cell) return;

    const originalText = buttonElement.innerText;
    buttonElement.innerText = "生成中...";
    buttonElement.disabled = true;

    // Build context
    const messages = [
        {
            role: 'system',
            content: `你是一个部署在天数智芯(Iluvatar Corex) AI 开发环境下的代码助理。
用户输入一段提示词，你需要帮用户编写出干净、高效的 Python 代码。
不要输出任何 markdown 格式的解释，也不要使用 \`\`\` 包裹代码。
只需直接输出可运行的代码，且如果是加速计算代码，默认在 GPU (比如 PyTorch 中使用 cuda 设备，天数智芯兼容 CUDA API) 上运行。`
        },
        {
            role: 'user',
            content: `原单元格代码：\n${cell.content}\n\n我的提示词：\n${prompt}`
        }
    ];

    try {
        const reply = await callLlmProxy(messages);
        
        // Clean reply in case model still added markdown formatting
        let cleanCode = reply;
        if (cleanCode.startsWith('```python')) {
            cleanCode = cleanCode.substring(9);
        } else if (cleanCode.startsWith('```')) {
            cleanCode = cleanCode.substring(3);
        }
        if (cleanCode.endsWith('```')) {
            cleanCode = cleanCode.substring(0, cleanCode.length - 3);
        }
        cleanCode = cleanCode.trim();

        cell.content = cleanCode;
        renderCells();
        saveNotebookToLocalStorage();
        showFloatingNotification('AI 代码生成完毕！');
    } catch (e) {
        console.error(e);
        alert("AI 代码生成失败: " + e.message + "\n请检查 [设置] 中的 API 端点及 Token 配置是否正确。");
    } finally {
        buttonElement.innerText = originalText;
        buttonElement.disabled = false;
    }
}

// AI Debugger for error cell
async function runCellDebug(id, buttonElement) {
    const cell = cells.find(c => c.id === id);
    if (!cell || !cell.output || !cell.output.stderr) return;

    const originalText = buttonElement.innerHTML;
    buttonElement.innerHTML = '<i class="fa-solid fa-spinner loading-icon" style="display:inline-block"></i> 诊断中...';
    buttonElement.disabled = true;

    const messages = [
        {
            role: 'system',
            content: `你是一个部署在天数智芯(Iluvatar Corex) AI 开发环境下的代码调试专家。
针对用户运行失败的代码以及异常 Traceback (Stderr)，分析其发生错误的原因，并提供修改后的正确完整代码。
格式：请先用一段简短、精确的中文说明出错原因（少于 150 字），然后输出一个修改后的完整代码块，代码块请用 \`\`\`python ... \`\`\` 包裹起来。`
        },
        {
            role: 'user',
            content: `我的代码：\n${cell.content}\n\n执行报错 (Traceback)：\n${cell.output.stderr}`
        }
    ];

    try {
        const reply = await callLlmProxy(messages);
        
        // Open Right Sidebar Chat and dump the debugging result there
        const aiSidebar = document.getElementById('aiSidebar');
        const openSidebarBtn = document.getElementById('openSidebarFloatingBtn');
        aiSidebar.classList.remove('collapsed');
        openSidebarBtn.classList.add('hidden');

        // Append chat messages
        appendChatMessage('user', `调试单元格代码 (错误诊断)`);
        appendChatMessage('assistant', reply);
    } catch (e) {
        console.error(e);
        alert("AI 诊断出错: " + e.message + "\n请检查 API 配置。");
    } finally {
        buttonElement.innerHTML = originalText;
        buttonElement.disabled = false;
    }
}

// Sidebar Chat Flow
async function sendChatMessage() {
    const chatInput = document.getElementById('chatInput');
    const query = chatInput.value.trim();
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
    const includeContext = document.getElementById('includeContextCheckbox').checked;
    if (includeContext && cells.length > 0) {
        let contextText = "以下是当前 Notebook 中的所有单元格代码与执行输出，供你参考：\n\n";
        cells.forEach((c, i) => {
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
        <div class="chat-avatar"><i class="fa-solid fa-robot"></i></div>
        <div class="chat-bubble">
            <span style="color:var(--text-muted)"><i class="fa-solid fa-compass-drafting loading-icon" style="display:inline-block;animation:spin 1.5s linear infinite"></i> 思考中，请稍候...</span>
        </div>
    `;
    chatHistory.appendChild(loaderMsg);
    chatHistory.scrollTop = chatHistory.scrollHeight;

    try {
        const reply = await callLlmProxy(messages);
        
        // Remove loader and insert actual response
        document.getElementById(loaderId).remove();
        appendChatMessage('assistant', reply);
    } catch(e) {
        document.getElementById(loaderId).remove();
        appendChatMessage('assistant', `⚠️ 交互出错：${e.message}\n请检查您的网络以及在 [设置] 中检查您的 API Endpoint 或 Access Token。`);
    }
}

function appendChatMessage(sender, text) {
    const chatHistory = document.getElementById('chatHistory');
    const msg = document.createElement('div');
    msg.className = `chat-message ${sender}`;
    
    const avatarIcon = sender === 'user' ? 'fa-user' : 'fa-robot';
    
    msg.innerHTML = `
        <div class="chat-avatar"><i class="fa-solid ${avatarIcon}"></i></div>
        <div class="chat-bubble">
            ${parseMarkdown(text)}
        </div>
    `;
    
    // Add special event listeners to code block copy buttons if generated
    msg.querySelectorAll('pre').forEach(pre => {
        // Create copy and insert code cells overlay
        const container = document.createElement('div');
        container.style.position = 'relative';
        pre.parentNode.insertBefore(container, pre);
        container.appendChild(pre);

        const actions = document.createElement('div');
        actions.style.position = 'absolute';
        actions.style.top = '4px';
        actions.style.right = '4px';
        actions.style.display = 'flex';
        actions.style.gap = '4px';

        const cpy = document.createElement('button');
        cpy.className = 'tb-btn';
        cpy.innerHTML = '<i class="fa-solid fa-copy"></i>';
        cpy.title = '复制';
        cpy.addEventListener('click', () => {
            navigator.clipboard.writeText(pre.innerText);
            showFloatingNotification('代码已复制！');
        });

        const insert = document.createElement('button');
        insert.className = 'tb-btn';
        insert.innerHTML = '<i class="fa-solid fa-plus"></i> 插入';
        insert.title = '作为新单元格插入 Notebook';
        insert.addEventListener('click', () => {
            const newCell = {
                id: 'cell_' + Math.random().toString(36).substr(2, 9),
                type: 'code',
                content: pre.innerText,
                output: null,
                elapsedTime: null,
                success: true,
                isExecuting: false
            };
            cells.push(newCell);
            renderCells();
            saveNotebookToLocalStorage();
            showFloatingNotification('已将代码插入笔记本！');
        });

        actions.appendChild(cpy);
        actions.appendChild(insert);
        container.appendChild(actions);
    });

    chatHistory.appendChild(msg);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

// Simple Markdown Parser (Zero Dependencies)
function parseMarkdown(text) {
    if (!text) return '';
    let html = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");
    
    // Code blocks with syntax wrapping
    html = html.replace(/```python([\s\S]*?)```/gim, '<pre><code class="language-python">$1</code></pre>');
    html = html.replace(/```([\s\S]*?)```/gim, '<pre><code>$1</code></pre>');
    html = html.replace(/`(.*?)`/g, '<code>$1</code>');
    
    // Headers
    html = html.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    html = html.replace(/^## (.*$)/gim, '<h2>$1</h2>');
    html = html.replace(/^# (.*$)/gim, '<h1>$1</h1>');
    
    // Bold & Italic
    html = html.replace(/\*\*(.*?)\*\*/gim, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/gim, '<em>$1</em>');
    
    // Blockquotes
    html = html.replace(/^\> (.*$)/gim, '<blockquote>$1</blockquote>');
    
    // Lists
    html = html.replace(/^\s*[\-\*]\s+(.*$)/gim, '<li>$1</li>');
    
    // Line breaks and paragraphs split
    const lines = html.split('\n');
    let output = [];
    let inList = false;
    
    lines.forEach(line => {
        const trimmed = line.trim();
        if (!trimmed) {
            if (inList) {
                output.push('</ul>');
                inList = false;
            }
            return;
        }
        
        if (trimmed.startsWith('<li>')) {
            if (!inList) {
                output.push('<ul>');
                inList = true;
            }
            output.push(line);
        } else {
            if (inList) {
                output.push('</ul>');
                inList = false;
            }
            
            if (trimmed.startsWith('<h') || trimmed.startsWith('<pre') || trimmed.startsWith('<code') || trimmed.startsWith('<blockquote>')) {
                output.push(line);
            } else {
                output.push(`<p>${line}</p>`);
            }
        }
    });
    
    if (inList) output.push('</ul>');
    
    return output.join('\n');
}

// UI notification helper
function showFloatingNotification(text) {
    const toast = document.createElement('div');
    toast.style.position = 'fixed';
    toast.style.bottom = '20px';
    toast.style.left = '50%';
    toast.style.transform = 'translateX(-50%) translateY(100px)';
    toast.style.background = 'var(--gradient-accent)';
    toast.style.color = '#070913';
    toast.style.padding = '10px 24px';
    toast.style.borderRadius = '20px';
    toast.style.fontSize = '0.85rem';
    toast.style.fontWeight = '600';
    toast.style.boxShadow = '0 8px 30px rgba(0, 242, 254, 0.3)';
    toast.style.transition = 'all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275)';
    toast.style.zIndex = '9999';
    toast.innerText = text;
    
    document.body.appendChild(toast);
    
    // Trigger slide up
    setTimeout(() => {
        toast.style.transform = 'translateX(-50%) translateY(0)';
    }, 50);
    
    // Trigger fade down & remove
    setTimeout(() => {
        toast.style.transform = 'translateX(-50%) translateY(100px)';
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 2500);
}
