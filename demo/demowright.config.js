import { defineDemo } from '@matte97p/demowright'

const INIT = `(() => {
  const OPENI_URL = 'https://token.openi.org.cn/v1'
  const YAML = [
    'model_list:',
    '- model_name: dsv4',
    '  litellm_params:',
    '    model: openai/dsv4',
    '    api_key: sk-openi-Demo-9f3a7b2c4e',
    '    api_base: https://token.openi.org.cn/v1',
    'general_settings: {}',
    ''
  ].join('\\n')
  const json = (obj) => new Response(JSON.stringify(obj), {
    status: 200,
    headers: { 'Content-Type': 'application/json' }
  })
  const orig = window.fetch.bind(window)
  window.fetch = async (input, opts) => {
    try {
      const method = String((opts && opts.method) || (input && input.method) || 'GET').toUpperCase()
      const url = new URL(typeof input === 'string' ? input : input.url, location.href)
      const p = url.pathname
      if (method === 'GET') {
        if (p === '/api/get_config') return json({ default_url: OPENI_URL, default_model: 'dsv4' })
        if (p === '/api/config_file') return json({ path: '~/.Iluvatar-AI-Notebook/litellm_config.yaml', exists: true, content: YAML, preview: false, managed_manually: false })
        if (p === '/api/health_check') return json({ ok: true, message: '连接正常' })
      } else if (method === 'POST') {
        if (p === '/api/save_config') return json({ ok: true, message: 'API 配置已保存' })
        if (p === '/api/config_file') return json({ ok: true, message: 'LiteLLM 配置已保存，代理已重启生效' })
      }
    } catch (e) {}
    return orig(input, opts)
  }
})()`

export default defineDemo({
  name: 'iluvatar-notebook-demo',
  url: 'http://127.0.0.1:5000/',
  viewport: { width: 1280, height: 720 },
  theme: { accent: '#6366f1' },
  formats: ['landscape'],
  init: INIT,
  steps: [
    // S1 开场
    { type: 'wait', duration: 2750 },
    { type: 'caption', text: 'Iluvatar AI Notebook · 浏览器里的国产 AI 算力开发环境', duration: 4400 },
    { type: 'highlight', selector: '.top-nav', duration: 2200 },
    { type: 'wait', duration: 1150 },
    { type: 'caption', text: '配置模型 · AI 对话 · 智能调试，全程 CPU 环境运行', duration: 4400 },
    { type: 'highlight', selector: '.kernel-status', duration: 2200 },
    { type: 'caption', text: '内核与遥测仪表就绪，无 GPU 环境自动降级', duration: 4000 },
    { type: 'wait', duration: 1150 },

    // S2 配置模型
    { type: 'caption', text: '第一步：在设置面板接入启智 OpenAI 兼容接口', duration: 4000 },
    { type: 'click', selector: '#settingsBtn' },
    { type: 'wait', duration: 950 },
    { type: 'zoom', selector: '#basicConfigView', duration: 1150 },
    { type: 'highlight', selector: '#basicConfigView', duration: 1800 },
    { type: 'type', selector: '#apiUrlInput', text: 'https://token.openi.org.cn/v1', perChar: 44, clear: true },
    { type: 'wait', duration: 650 },
    { type: 'type', selector: '#apiTokenInput', text: 'sk-openi-Demo-9f3a7b2c4e', perChar: 30, clear: true },
    { type: 'wait', duration: 650 },
    { type: 'click', selector: '#toggleTokenVisibility' },
    { type: 'wait', duration: 1150 },
    { type: 'click', selector: '#toggleTokenVisibility' },
    { type: 'wait', duration: 550 },
    { type: 'type', selector: '#modelInput', text: 'dsv4', perChar: 40, clear: true },
    { type: 'wait', duration: 750 },
    { type: 'zoomReset' },
    { type: 'click', selector: '#saveSettingsBtn' },
    { type: 'wait', selector: '.floating-notification.show', timeout: 15000 },
    { type: 'wait', duration: 1350 },
    { type: 'caption', text: '保存即热重启本地 LiteLLM 代理，无需重启应用', duration: 4000 },
    { type: 'click', selector: '#settingsBtn' },
    { type: 'wait', duration: 1000 },
    { type: 'click', selector: '#checkApiHealthBtn' },
    { type: 'wait', duration: 1950 },
    { type: 'caption', text: '健康检查通过，链路：Notebook → 本地代理 → 启智 API', duration: 4000 },
    { type: 'click', selector: '.advanced-mode-switch' },
    { type: 'wait', duration: 1650 },
    { type: 'highlight', selector: '#configEditorContainer .CodeMirror', duration: 2200 },
    { type: 'zoom', selector: '#configEditorContainer', duration: 1150 },
    { type: 'caption', text: '高级模式：逐字编辑 litellm_config.yaml，配置即代码', duration: 4200 },
    { type: 'wait', duration: 1550 },
    { type: 'zoomReset' },
    { type: 'caption', text: '保存失败自动回滚旧配置，代理日志可追溯', duration: 3800 },
    { type: 'click', selector: '#closeSettingsBtn' },
    { type: 'wait', duration: 850 },

    // S3 基础对话
    { type: 'caption', text: '打开 AI 助手，像聊天一样直接提问', duration: 3800 },
    { type: 'goto', url: 'http://127.0.0.1:5000/agent/' },
    { type: 'wait', duration: 3950 },
    { type: 'click', selector: '#chat-input' },
    { type: 'type', selector: '#chat-input', text: '你好，介绍一下 Iluvatar AI Notebook', perChar: 34 },
    { type: 'key', key: 'Enter' },
    { type: 'wait', duration: 6350 },
    { type: 'caption', text: '回复即刻呈现，上下文与 Notebook 内核互通', duration: 4000 },
    { type: 'wait', duration: 1650 },
    { type: 'click', selector: '#chat-input' },
    { type: 'type', selector: '#chat-input', text: '当前内核状态如何？', perChar: 32 },
    { type: 'key', key: 'Enter' },
    { type: 'wait', duration: 4950 },
    { type: 'caption', text: '多轮对话，上下文连续', duration: 3600 },
    { type: 'wait', duration: 1350 },

    // S4 ReAct 工具调用
    { type: 'caption', text: '更进一步：让 AI 亲自调用工具干活', duration: 4000 },
    { type: 'click', selector: '#chat-input' },
    { type: 'type', selector: '#chat-input', text: '用 Matplotlib 画一条正弦曲线，直接在内核里运行', perChar: 28 },
    { type: 'key', key: 'Enter' },
    { type: 'wait', duration: 4950 },
    { type: 'caption', text: 'AI 决策调用工具，代码在内核中真实执行', duration: 4000 },
    { type: 'wait', duration: 4550 },
    { type: 'caption', text: '执行完毕，AI 汇报结果，过程全程可见', duration: 3800 },
    { type: 'wait', duration: 1650 },

    // S5 单元格内 AI Debug
    { type: 'caption', text: '回到 Notebook：代码报错，单元格内一键 AI 诊断', duration: 4000 },
    { type: 'goto', url: 'http://127.0.0.1:5000/' },
    { type: 'wait', duration: 2150 },
    { type: 'caption', text: '新建一个空白笔记本', duration: 2400 },
    { type: 'click', selector: '#newNotebookBtn' },
    { type: 'wait', duration: 2400 },
    { type: 'click', selector: '#addCodeBtn' },
    { type: 'wait', duration: 1350 },
    { type: 'click', selector: '.cell-container:last-of-type .CodeMirror' },
    { type: 'wait', duration: 650 },
    { type: 'type', selector: '.cell-container:last-of-type .CodeMirror textarea', text: 'import numpy as np\nx = np.array([1, 2, 3])\nprint("结果是：" + x)', perChar: 24 },
    { type: 'wait', duration: 650 },
    { type: 'click', selector: '.cell-container:last-of-type .run-cell-btn' },
    { type: 'wait', selector: '.cell-container:last-of-type .ai-debug-bar', timeout: 45000 },
    { type: 'wait', duration: 1050 },
    { type: 'caption', text: 'TypeError：检测到报错，直接发起 AI 诊断', duration: 3600 },
    { type: 'highlight', selector: '.cell-container:last-of-type .ai-debug-bar', duration: 1900 },
    { type: 'click', selector: '.ai-debug-btn.primary' },
    { type: 'wait', selector: '.cell-container:last-of-type .suggestion-btn.accept-overwrite', timeout: 45000 },
    { type: 'caption', text: 'AI 流式分析报错原因，生成修复代码', duration: 3800 },
    { type: 'zoom', selector: '.cell-container:last-of-type .ai-debug-preview', duration: 1150 },
    { type: 'wait', duration: 1550 },
    { type: 'zoomReset' },
    { type: 'click', selector: '.cell-container:last-of-type .suggestion-actions .suggestion-btn:nth-child(2)' },
    { type: 'wait', duration: 5350 },
    { type: 'highlight', selector: '.cell-container:last-of-type .cell-output-area', duration: 2000 },
    { type: 'caption', text: '一键覆盖并重新执行，问题解决', duration: 3800 },
    { type: 'wait', duration: 1050 },
    { type: 'click', selector: '#varInspectorTabBtn' },
    { type: 'wait', duration: 1250 },
    { type: 'highlight', selector: '#variablesList', duration: 2100 },
    { type: 'caption', text: '内核变量实时可查，执行状态一目了然', duration: 3600 },
    { type: 'wait', duration: 1050 },

    // S6 内置终端
    { type: 'caption', text: '内置终端：开发与运维同一工作台', duration: 3400 },
    { type: 'click', selector: '#termToggleBtn' },
    { type: 'wait', duration: 3200 },
    { type: 'click', selector: '.terminal-panel .xterm' },
    { type: 'wait', duration: 600 },
    { type: 'type', selector: '.terminal-panel .xterm-helper-textarea', text: 'python3 --version && nproc && ls *.ipynb', perChar: 26 },
    { type: 'key', key: 'Enter' },
    { type: 'wait', duration: 2600 },
    { type: 'highlight', selector: '.terminal-panel', duration: 1900 },
    { type: 'caption', text: '真实 shell：Notebook 与终端共享同一环境', duration: 3400 },
    { type: 'wait', duration: 1000 },
    { type: 'click', selector: '#termToggleBtn' },
    { type: 'wait', duration: 800 },

    // S7 收尾
    { type: 'endcard', title: 'Iluvatar AI Notebook', subtitle: '国产 AI 算力 · 启智社区 · 开源共建', duration: 4800 },
  ],

})
