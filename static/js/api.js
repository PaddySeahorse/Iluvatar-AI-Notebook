// API services for Iluvatar AI Notebook

export const apiConfig = {
    url: '',
    token: '',
    model: ''
};

// Load configuration from local storage or backend default configuration
export async function initConfig() {
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
                apiConfig.token = savedToken || '';
                apiConfig.model = savedModel || data.default_model;
            }
        } catch (e) {
            console.error("Failed to fetch config from backend:", e);
            apiConfig.url = savedUrl || 'https://token.openi.org.cn/v1/chat/completions';
            apiConfig.token = savedToken || '';
            apiConfig.model = savedModel || 'dsv4';
        }
    }
    return apiConfig;
}

// Save API configuration
export function saveApiConfig(url, token, model) {
    apiConfig.url = url;
    apiConfig.token = token;
    apiConfig.model = model;
    localStorage.setItem('openi_api_url', url);
    localStorage.setItem('openi_api_token', token);
    localStorage.setItem('openi_api_model', model);
}

// Fetch GPU hardware metrics
export async function fetchGpuStatus() {
    const res = await fetch('/api/gpu_status');
    if (!res.ok) throw new Error("Failed to fetch GPU status");
    return await res.json();
}

// Run code execution on python kernel backend
export async function runCellOnBackend(code) {
    const res = await fetch('/api/run_cell', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ code: code })
    });
    if (!res.ok) throw new Error("Backend server response failed");
    return await res.json();
}

// Interrupt kernel execution
export async function interruptKernelOnBackend() {
    const res = await fetch('/api/interrupt_kernel', {
        method: 'POST'
    });
    if (!res.ok) throw new Error("Failed to interrupt kernel");
    return await res.json();
}

// Proxy call to LLM Endpoint (non-streaming)
export async function callLlmProxy(messages) {
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

// Streaming call to LLM Endpoint
export async function callLlmProxyStream(messages, onChunk, onDone) {
    const res = await fetch('/api/ai_call', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            url: apiConfig.url,
            token: apiConfig.token,
            model: apiConfig.model,
            messages: messages,
            stream: true
        })
    });
    
    if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.message || `HTTP error ${res.status}`);
    }
    
    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';
    let fullText = '';
    
    try {
        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            
            buffer += decoder.decode(value, { stream: true });
            let lines = buffer.split('\n');
            buffer = lines.pop(); // save trailing line fragment
            
            for (const line of lines) {
                const cleanLine = line.trim();
                if (!cleanLine) continue;
                if (cleanLine === 'data: [DONE]') continue;
                if (cleanLine.startsWith('data: ')) {
                    try {
                        const parsed = JSON.parse(cleanLine.substring(6));
                        const content = parsed.choices?.[0]?.delta?.content || '';
                        if (content) {
                            fullText += content;
                            onChunk(fullText);
                        }
                    } catch (e) {
                        console.error("Failed to parse SSE JSON chunk:", e, cleanLine);
                    }
                }
            }
        }
        
        // Process any leftover buffer
        if (buffer) {
            const cleanLine = buffer.trim();
            if (cleanLine.startsWith('data: ') && cleanLine !== 'data: [DONE]') {
                try {
                    const parsed = JSON.parse(cleanLine.substring(6));
                    const content = parsed.choices?.[0]?.delta?.content || '';
                    if (content) {
                        fullText += content;
                        onChunk(fullText);
                    }
                } catch (e) {
                    console.error("Failed to parse trailing chunk:", e);
                }
            }
        }
        
        if (onDone) {
            onDone(fullText);
        }
        return fullText;
    } catch (e) {
        reader.cancel();
        throw e;
    }
}

// Check syntax and variable loading via AST in backend
export async function lintCellOnBackend(code) {
    const res = await fetch('/api/lint_cell', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ code: code })
    });
    if (!res.ok) throw new Error("Backend lint request failed");
    return await res.json();
}

// Fetch active python variables in kernel
export async function fetchKernelVariables() {
    const res = await fetch('/api/get_variables');
    if (!res.ok) throw new Error("Backend get_variables request failed");
    return await res.json();
}

// Fetch list of server notebooks
export async function fetchNotebooksList() {
    const res = await fetch('/api/files/list');
    if (!res.ok) throw new Error("Failed to fetch notebooks list");
    return await res.json();
}

// Read server notebook content
export async function readNotebookFromServer(filename) {
    const res = await fetch(`/api/files/read?filename=${encodeURIComponent(filename)}`);
    if (!res.ok) throw new Error(`Failed to read notebook ${filename}`);
    return await res.json();
}

// Save notebook content to server
export async function saveNotebookToServer(filename, content) {
    const res = await fetch('/api/files/save', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ filename, content })
    });
    if (!res.ok) throw new Error(`Failed to save notebook ${filename}`);
    return await res.json();
}

// Create new blank notebook on server
export async function createNotebookOnServer() {
    const res = await fetch('/api/files/create', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    });
    if (!res.ok) throw new Error("Failed to create new notebook");
    return await res.json();
}

// Rename notebook on server
export async function renameNotebookOnServer(oldName, newName) {
    const res = await fetch('/api/files/rename', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ old_name: oldName, new_name: newName })
    });
    if (!res.ok) throw new Error(`Failed to rename notebook from ${oldName} to ${newName}`);
    return await res.json();
}

// Delete notebook on server
export async function deleteNotebookFromServer(filename) {
    const res = await fetch('/api/files/delete', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({ filename })
    });
    if (!res.ok) throw new Error(`Failed to delete notebook ${filename}`);
    return await res.json();
}

