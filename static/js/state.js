// State management for Iluvatar AI Notebook

export const state = {
    cells: [],
    activeCellId: null,
    isGpuModalOpen: false,
    executionCounter: 0
};

// Save Notebook state to localStorage
export function saveNotebookToLocalStorage() {
    const titleEl = document.getElementById('notebookTitle');
    const title = titleEl ? titleEl.value : 'Untitled_Iluvatar_Notebook.ipynb';
    localStorage.setItem('notebook_title', title);
    localStorage.setItem('notebook_cells', JSON.stringify(state.cells));
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

// Delete a cell
export function deleteCell(id) {
    state.cells = state.cells.filter(c => c.id !== id);
    if (state.activeCellId === id) state.activeCellId = null;
    saveNotebookToLocalStorage();
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
