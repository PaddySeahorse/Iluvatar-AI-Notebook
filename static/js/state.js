// State management for Iluvatar AI Notebook

export const state = {
    cells: [],
    activeCellId: null,
    isGpuModalOpen: false,
    executionCounter: 0,
    currentFilename: '',
    notebookFiles: [],
    onSave: null
};

// Save Notebook state to localStorage and invoke server-side save
export function saveNotebookToLocalStorage() {
    const titleEl = document.getElementById('notebookTitle');
    const title = titleEl ? titleEl.value : 'Untitled_Iluvatar_Notebook.ipynb';
    localStorage.setItem('notebook_title', title);
    localStorage.setItem('notebook_cells', JSON.stringify(state.cells));
    
    if (state.onSave) {
        state.onSave();
    }
}

// Load Notebook from localStorage
export function loadSavedNotebook() {
    const title = localStorage.getItem('notebook_title');
    const titleEl = document.getElementById('notebookTitle');
    if (title && titleEl) {
        titleEl.value = title;
    }
    const savedCells = localStorage.getItem('notebook_cells');
    if (savedCells) {
        try {
            state.cells = JSON.parse(savedCells);
            // Ensure executing state is reset on load
            state.cells.forEach(c => {
                if (c.type === 'code') c.isExecuting = false;
            });
        } catch (e) {
            console.error("Failed to parse saved cells:", e);
            state.cells = [];
        }
    }
}

// Add a new cell
export function addCell(type, index = null) {
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
        state.cells.push(newCell);
    } else {
        state.cells.splice(index, 0, newCell);
    }

    state.activeCellId = newCell.id;
    saveNotebookToLocalStorage();
    return newCell;
}

export const undoStack = [];

// Delete a cell
export function deleteCell(id) {
    const idx = state.cells.findIndex(c => c.id === id);
    if (idx !== -1) {
        undoStack.push({
            cell: JSON.parse(JSON.stringify(state.cells[idx])),
            index: idx
        });
        state.cells = state.cells.filter(c => c.id !== id);
        if (state.activeCellId === id) state.activeCellId = null;
        saveNotebookToLocalStorage();
    }
}

// Restore last deleted cell
export function restoreLastDeletedCell() {
    if (undoStack.length === 0) return null;
    const { cell, index } = undoStack.pop();
    state.cells.splice(index, 0, cell);
    state.activeCellId = cell.id;
    saveNotebookToLocalStorage();
    return cell;
}

// Move a cell up or down
export function moveCell(id, direction) {
    const idx = state.cells.findIndex(c => c.id === id);
    if (idx === -1) return false;
    const targetIdx = idx + direction;
    if (targetIdx < 0 || targetIdx >= state.cells.length) return false;

    // Swap items
    const temp = state.cells[idx];
    state.cells[idx] = state.cells[targetIdx];
    state.cells[targetIdx] = temp;

    saveNotebookToLocalStorage();
    return true;
}

// Activate cell focus
export function activateCell(id) {
    state.activeCellId = id;
}

// Deactivate all cells focus
export function deactivateAllCells() {
    state.activeCellId = null;
}

// Convert state to standard .ipynb JSON
export function exportNotebookAsIpynb() {
    const ipynbCells = state.cells.map(cell => {
        const source = cell.content.split('\n').map((line, idx, arr) => {
            return idx === arr.length - 1 ? line : line + '\n';
        });

        if (cell.type === 'code') {
            const outputs = [];
            if (!cell.output) cell.output = {};
                if (cell.output.stdout) {
                    outputs.push({
                        output_type: 'stream',
                        name: 'stdout',
                        text: cell.output.stdout.split('\n').map((line, idx, arr) => idx === arr.length - 1 ? line : line + '\n')
                    });
                }
                if (cell.output.stderr) {
                    outputs.push({
                        output_type: 'stream',
                        name: 'stderr',
                        text: cell.output.stderr.split('\n').map((line, idx, arr) => idx === arr.length - 1 ? line : line + '\n')
                    });
                }
                if (cell.output.html) {
                    outputs.push({
                        output_type: 'display_data',
                        data: {
                            'text/html': cell.output.html.split('\n').map((line, idx, arr) => idx === arr.length - 1 ? line : line + '\n')
                        },
                        metadata: {}
                    });
                }
                if (cell.output.plots && cell.output.plots.length > 0) {
                    cell.output.plots.forEach(plotBase64 => {
                        outputs.push({
                            output_type: 'display_data',
                            data: {
                                'image/png': plotBase64
                            },
                            metadata: {}
                        });
                    });
                }

            return {
                cell_type: 'code',
                execution_count: cell.executionIndex || null,
                metadata: {},
                outputs: outputs,
                source: source
            };
        } else {
            return {
                cell_type: 'markdown',
                metadata: {},
                source: source
            };
        }
    });

    const titleEl = document.getElementById('notebookTitle');
    const title = titleEl ? titleEl.value : 'Untitled_Iluvatar_Notebook.ipynb';

    return {
        cells: ipynbCells,
        metadata: {
            kernelspec: {
                display_name: 'Python 3 (天数智芯 BI-150)',
                language: 'python',
                name: 'python3'
            },
            language_info: {
                name: 'python'
            },
            title: title
        },
        nbformat: 4,
        nbformat_minor: 2
    };
}

// Convert standard .ipynb JSON object to state
export function importNotebookFromIpynb(ipynbObj) {
    if (!ipynbObj || !Array.isArray(ipynbObj.cells)) {
        throw new Error("无效的 .ipynb 文件结构");
    }

    const importedCells = ipynbObj.cells.map(c => {
        const type = c.cell_type === 'code' ? 'code' : 'markdown';
        const content = Array.isArray(c.source) ? c.source.join('') : (c.source || '');
        
        let output = null;
        if (type === 'code' && Array.isArray(c.outputs) && c.outputs.length > 0) {
            let stdout = '';
            let stderr = '';
            let html = '';
            const plots = [];

            c.outputs.forEach(out => {
                if (out.output_type === 'stream') {
                    const text = Array.isArray(out.text) ? out.text.join('') : (out.text || '');
                    if (out.name === 'stdout') {
                        stdout += text;
                    } else if (out.name === 'stderr') {
                        stderr += text;
                    }
                } else if ((out.output_type === 'display_data' || out.output_type === 'execute_result') && out.data) {
                    if (out.data['image/png']) {
                        // Standard base64 content
                        plots.push(out.data['image/png'].replace(/\n/g, ''));
                    }
                    if (out.data['text/html']) {
                        const h = Array.isArray(out.data['text/html']) ? out.data['text/html'].join('') : out.data['text/html'];
                        html += h;
                    }
                }
            });

            if (stdout || stderr || html || plots.length > 0) {
                output = { stdout, stderr, html, plots };
            }
        }

        const cell = {
            id: 'cell_' + Math.random().toString(36).substr(2, 9),
            type: type,
            content: content,
            output: output
        };

        if (type === 'code') {
            cell.elapsedTime = null;
            cell.success = !output || !output.stderr;
            cell.isExecuting = false;
            cell.executionIndex = c.execution_count || null;
        } else {
            cell.isEditingMarkdown = false;
        }

        return cell;
    });

    // Update state
    state.cells = importedCells;
    state.activeCellId = importedCells.length > 0 ? importedCells[0].id : null;
    
    if (ipynbObj.metadata && ipynbObj.metadata.title) {
        const titleEl = document.getElementById('notebookTitle');
        if (titleEl) {
            titleEl.value = ipynbObj.metadata.title.endsWith('.ipynb') ? ipynbObj.metadata.title : ipynbObj.metadata.title + '.ipynb';
        }
    }

    saveNotebookToLocalStorage();
}

