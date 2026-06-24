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
