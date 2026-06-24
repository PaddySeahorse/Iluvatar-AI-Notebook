// View rendering and parsing helpers for Iluvatar AI Notebook

export function autoResizeTextarea(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = (textarea.scrollHeight) + 'px';
}

export function parseMarkdown(text) {
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

export function showFloatingNotification(text) {
    const toast = document.createElement('div');
    toast.className = 'floating-notification';
    toast.innerText = text;
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.classList.add('show');
    }, 50);
    
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 2500);
}

// Helper: render Cell Toolbar
function renderCellToolbar(cell, index, cellsLength, callbacks) {
    const toolbar = document.createElement('div');
    toolbar.className = 'cell-toolbar';
    
    const moveUpBtn = document.createElement('button');
    moveUpBtn.className = 'tb-btn';
    moveUpBtn.innerHTML = '<i class="fa-solid fa-arrow-up"></i>';
    moveUpBtn.title = '上移';
    moveUpBtn.disabled = index === 0;
    moveUpBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        callbacks.onMoveCell(cell.id, -1);
    });

    const moveDownBtn = document.createElement('button');
    moveDownBtn.className = 'tb-btn';
    moveDownBtn.innerHTML = '<i class="fa-solid fa-arrow-down"></i>';
    moveDownBtn.title = '下移';
    moveDownBtn.disabled = index === cellsLength - 1;
    moveDownBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        callbacks.onMoveCell(cell.id, 1);
    });

    const deleteBtn = document.createElement('button');
    deleteBtn.className = 'tb-btn delete';
    deleteBtn.innerHTML = '<i class="fa-solid fa-trash-can"></i>';
    deleteBtn.title = '删除';
    deleteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        callbacks.onDeleteCell(cell.id);
    });

    toolbar.appendChild(moveUpBtn);
    toolbar.appendChild(moveDownBtn);
    toolbar.appendChild(deleteBtn);
    return toolbar;
}

// Helper: render AI code suggestion preview overlay
function renderAiSuggestion(cell, callbacks) {
    const previewEl = document.createElement('div');
    previewEl.className = 'ai-suggestion-preview';
    previewEl.id = `suggestion_preview_${cell.id}`;
    
    const header = document.createElement('div');
    header.className = 'suggestion-header';
    header.innerHTML = `
        <span><i class="fa-solid fa-wand-magic-sparkles"></i> AI 推荐代码 (${cell.aiSuggestion.isGenerating ? '生成中...' : '生成完毕'}):</span>
    `;
    
    const actions = document.createElement('div');
    actions.className = 'suggestion-actions';
    if (cell.aiSuggestion.isGenerating) {
        actions.style.display = 'none';
    }
    
    const acceptOverwrite = document.createElement('button');
    acceptOverwrite.className = 'suggestion-btn accept-overwrite';
    acceptOverwrite.innerHTML = '<i class="fa-solid fa-check"></i> 覆盖当前单元格';
    acceptOverwrite.addEventListener('click', (e) => {
        e.stopPropagation();
        callbacks.onAcceptOverwrite(cell.id, cell.aiSuggestion.code);
    });
    
    const acceptInsert = document.createElement('button');
    acceptInsert.className = 'suggestion-btn accept-insert';
    acceptInsert.innerHTML = '<i class="fa-solid fa-plus"></i> 插入为新单元格';
    acceptInsert.addEventListener('click', (e) => {
        e.stopPropagation();
        callbacks.onAcceptInsert(cell.id, cell.aiSuggestion.code);
    });
    
    const discardBtn = document.createElement('button');
    discardBtn.className = 'suggestion-btn discard';
    discardBtn.innerHTML = '<i class="fa-solid fa-xmark"></i> 放弃';
    discardBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        callbacks.onDiscardSuggestion(cell.id);
    });
    
    actions.appendChild(acceptOverwrite);
    actions.appendChild(acceptInsert);
    actions.appendChild(discardBtn);
    header.appendChild(actions);
    previewEl.appendChild(header);
    
    const codePre = document.createElement('pre');
    const codeCode = document.createElement('code');
    codeCode.className = 'language-python';
    codeCode.innerText = cell.aiSuggestion.code || '等待生成...';
    codePre.appendChild(codeCode);
    previewEl.appendChild(codePre);

    return previewEl;
}

// Helper: render Cell Editor Input Area
function renderCodeEditor(cell, callbacks) {
    const inputArea = document.createElement('div');
    inputArea.className = 'cell-input-area';

    const editor = document.createElement('textarea');
    editor.className = 'cell-editor';
    editor.value = cell.content;
    editor.placeholder = '在此输入 Python 代码...';
    editor.addEventListener('input', (e) => {
        callbacks.onContentChange(cell.id, e.target.value);
        autoResizeTextarea(editor);
    });
    editor.addEventListener('focus', () => callbacks.onActivateCell(cell.id));
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
            callbacks.onAiAssist(cell.id, prompt, assistBtn);
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

    // Render AI Code suggestion card if it exists
    if (cell.aiSuggestion) {
        inputArea.appendChild(renderAiSuggestion(cell, callbacks));
    }

    return inputArea;
}

// Helper: render Cell Outputs (stdout, stderr, plots)
function renderCellOutput(cell) {
    const hasStdout = cell.output.stdout && cell.output.stdout.trim();
    const hasStderr = cell.output.stderr && cell.output.stderr.trim();
    const hasPlots = cell.output.plots && cell.output.plots.length > 0;

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

    return outputArea;
}

// Helper: render error feedback and AI debug launcher bar
function renderAiDebugBar(cell, callbacks) {
    const debugBar = document.createElement('div');
    debugBar.className = 'ai-debug-bar';
    debugBar.innerHTML = `
        <span class="debug-text"><i class="fa-solid fa-triangle-exclamation"></i> 检测到运行出错，点击让 AI 进行智能诊断</span>
        <button class="ai-debug-btn"><i class="fa-solid fa-bug-slash"></i> 一键 AI 调试</button>
    `;
    
    const debugBtn = debugBar.querySelector('.ai-debug-btn');
    debugBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        callbacks.onDebug(cell.id, debugBtn);
    });

    return debugBar;
}

// Helper: render separation bar between cells
function createHoverAddBar(index, callbacks) {
    const trigger = document.createElement('div');
    trigger.className = 'hover-add-cell-trigger';
    
    const group = document.createElement('div');
    group.className = 'hover-add-btn-group';
    
    const addCode = document.createElement('button');
    addCode.className = 'hover-add-btn';
    addCode.innerHTML = '<i class="fa-solid fa-plus"></i> 代码';
    addCode.addEventListener('click', () => callbacks.onAddCell('code', index));

    const addMd = document.createElement('button');
    addMd.className = 'hover-add-btn';
    addMd.innerHTML = '<i class="fa-solid fa-paragraph"></i> 文本';
    addMd.addEventListener('click', () => callbacks.onAddCell('markdown', index));

    group.appendChild(addCode);
    group.appendChild(addMd);
    trigger.appendChild(group);
    
    return trigger;
}

// Main cells renderer orchestrator
export function renderCells(cells, activeCellId, callbacks) {
    const container = document.getElementById('cellsList');
    if (!container) return;
    container.innerHTML = '';

    cells.forEach((cell, index) => {
        // Create inter-cell hover add menu (except before the first cell, which is handled after)
        if (index > 0) {
            container.appendChild(createHoverAddBar(index, callbacks));
        }

        const cellEl = document.createElement('div');
        cellEl.className = `cell-container ${cell.type} ${activeCellId === cell.id ? 'active' : ''}`;
        cellEl.id = cell.id;
        cellEl.setAttribute('data-index', index);

        // Click to activate cell
        cellEl.addEventListener('click', (e) => {
            if (activeCellId !== cell.id) {
                callbacks.onActivateCell(cell.id);
            }
        });

        // 1. Cell Toolbar
        const toolbar = renderCellToolbar(cell, index, cells.length, callbacks);
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
                callbacks.onRunCell(cell.id);
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
        let inputArea;
        if (cell.type === 'code') {
            inputArea = renderCodeEditor(cell, callbacks);
        } else {
            // Markdown Cell
            inputArea = document.createElement('div');
            inputArea.className = 'cell-input-area';

            if (cell.isEditingMarkdown) {
                const editor = document.createElement('textarea');
                editor.className = 'cell-editor';
                editor.value = cell.content;
                editor.placeholder = '在此输入 Markdown 格式内容...';
                editor.addEventListener('input', (e) => {
                    callbacks.onContentChange(cell.id, e.target.value);
                    autoResizeTextarea(editor);
                });
                editor.addEventListener('blur', () => {
                    cell.isEditingMarkdown = false;
                    callbacks.onDeactivateMarkdown(cell.id);
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
                    callbacks.onActivateMarkdown(cell.id);
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
                const outputArea = renderCellOutput(cell);
                cellEl.appendChild(outputArea);
            }

            // 4. Debug Action overlay if run failed
            if (!cell.success && hasStderr) {
                const debugBar = renderAiDebugBar(cell, callbacks);
                cellEl.appendChild(debugBar);
            }
        }

        container.appendChild(cellEl);
    });
}
