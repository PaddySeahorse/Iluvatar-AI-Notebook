import { defineDemo } from '@matte97p/demowright'

// Pre-seed the workspace notebook so the recording starts with the demo
// markdown header and an empty code cell (no typing/editing detours).
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
  const MD_CELL = {
    id: 'cell_mr100md01',
    type: 'markdown',
    content: '## MR-100 图像推理演示\\n\\n使用目标检测模型分析测试图片，并评估推理延迟、吞吐量、显存占用和 GPU 利用率。',
    output: null,
    isEditingMarkdown: false
  }
  const CODE_CELL = {
    id: 'cell_mr100code1',
    type: 'code',
    content: '',
    output: null,
    elapsedTime: null,
    success: true,
    isExecuting: false
  }
  try {
    localStorage.setItem('notebook_title', 'MR-100_Inference_Demo.ipynb')
    localStorage.setItem('notebook_cells', JSON.stringify([MD_CELL, CODE_CELL]))
  } catch (e) {}
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
        if (p === '/api/files/list') return json({ success: false })
      } else if (method === 'POST') {
        if (p === '/api/save_config') return json({ ok: true, message: 'API 配置已保存' })
        if (p === '/api/config_file') return json({ ok: true, message: 'LiteLLM 配置已保存，代理已重启生效' })
      }
    } catch (e) {}
    return orig(input, opts)
  }
})()`

const INFERENCE_PROMPT =
    '请生成目标检测推理代码：\n' +
    '1. 加载本地已经准备好的 YOLOv8s 模型；\n' +
    '2. 对 demo.jpg 执行目标检测；\n' +
    '3. 使用 GPU 0；\n' +
    '4. 输出检测到的目标类别、置信度和边界框；\n' +
    '5. 显示带检测框的结果图片；\n' +
    '6. 统计模型加载时间和单次推理时间。'

const BENCHMARK_PROMPT =
    '请复用已经加载的模型和测试图片：\n' +
    '1. 预热 10 次；\n' +
    '2. 正式推理 50 次；\n' +
    '3. 统计平均延迟、P50、P95 和 FPS；\n' +
    '4. 用表格打印结果；\n' +
    '5. 用 Matplotlib 绘制每次推理延迟变化。'

const ERROR_CODE =
    'results = model.predict("assets/not-exist.jpg", device=device, imgsz=640, verbose=False)\n' +
    'print(results[0].boxes)'

const SUMMARY_PROMPT =
    '请根据当前 Notebook 的代码和输出：\n' +
    '1. 总结图片中检测到了哪些目标；\n' +
    '2. 判断推理延迟是否稳定；\n' +
    '3. 解释平均延迟、P95 和 FPS 分别代表什么；\n' +
    '4. 给出两条提高推理吞吐量的建议。\n' +
    '请简洁回答，不超过 200 字。'

export default defineDemo({
  name: 'iluvatar-mr100-inference-demo',
  url: 'http://127.0.0.1:5000/',
  viewport: { width: 1280, height: 720 },
  theme: { accent: '#6366f1' },
  formats: ['landscape'],
  init: INIT,
  steps: [
    // S1 0:00-0:25 MR-100 环境
    { type: 'wait', duration: 2200 },
    { type: 'caption', text: '运行在天数智芯 MR-100 推理卡上的 Iluvatar AI Notebook', duration: 4400 },
    { type: 'highlight', selector: '#gpuDashboard', duration: 2200 },
    { type: 'caption', text: '利用率 · 显存 · 温度 · 功耗，每 1.5 秒刷新的真实硬件遥测', duration: 4400 },
    { type: 'wait', duration: 1000 },
    { type: 'click', selector: '#gpuDashboard' },
    { type: 'wait', duration: 1500 },
    { type: 'caption', text: '芯片型号实时上报自设备驱动，不写死在页面里', duration: 4000 },
    { type: 'highlight', selector: '#gpuModal .modal-card', duration: 2200 },
    { type: 'wait', duration: 1400 },
    { type: 'click', selector: '#closeGpuBottomBtn' },
    { type: 'wait', duration: 900 },
    { type: 'caption', text: 'Notebook 已就绪：让 Copilot 生成第一段推理代码', duration: 4000 },
    { type: 'wait', duration: 900 },

    // S2 0:25-1:05 Copilot 生成推理代码
    { type: 'highlight', selector: '.cell-container:first-of-type', duration: 2000 },
    { type: 'caption', text: '在代码单元格下方输入需求，AI 直接写代码', duration: 3800 },
    { type: 'click', selector: '.cell-container:last-of-type .ai-assist-input' },
    { type: 'type', selector: '.cell-container:last-of-type .ai-assist-input', text: INFERENCE_PROMPT, perChar: 22 },
    { type: 'wait', duration: 450 },
    { type: 'click', selector: '.cell-container:last-of-type .ai-assist-btn' },
    { type: 'wait', selector: '.cell-container:last-of-type .ai-suggestion-preview .suggestion-btn.accept-overwrite', timeout: 60000 },
    { type: 'caption', text: '流式生成：加载 YOLOv8s → GPU 0 检测 → 结果可视化 → 计时统计', duration: 4400 },
    { type: 'wait', duration: 1200 },
    { type: 'click', selector: '.cell-container:last-of-type .suggestion-actions .suggestion-btn:nth-child(1)' },
    { type: 'wait', duration: 900 },
    { type: 'highlight', selector: '.cell-container:last-of-type .CodeMirror', duration: 2200 },
    { type: 'caption', text: '生成的代码已写入单元格，可以直接运行', duration: 4000 },
    { type: 'wait', duration: 800 },

    // S3 1:05-1:45 执行真实推理
    { type: 'click', selector: '.cell-container:last-of-type .run-cell-btn' },
    { type: 'caption', text: '在 MR-100 上真实执行：模型加载 → 首次推理', duration: 4200 },
    { type: 'wait', selector: '.cell-container:last-of-type .output-plot-img', timeout: 180000 },
    { type: 'wait', duration: 1500 },
    { type: 'highlight', selector: '.cell-container:last-of-type .cell-output-area', duration: 2200 },
    { type: 'caption', text: '检出目标直接呈现：类别、置信度、边界框与带框结果图', duration: 4600 },
    { type: 'wait', duration: 1800 },
    { type: 'highlight', selector: '#gpuDashboard', duration: 2200 },
    { type: 'caption', text: '模型权重进入显存：遥测看板第一时间看到变化', duration: 4200 },
    { type: 'wait', duration: 1100 },

    // S4 1:45-2:25 基准测试
    { type: 'caption', text: '单次推理太快？做一轮基准测试，复用已加载的模型', duration: 4200 },
    { type: 'click', selector: '#addCodeBtn' },
    { type: 'wait', duration: 1100 },
    { type: 'click', selector: '.cell-container:last-of-type .ai-assist-input' },
    { type: 'type', selector: '.cell-container:last-of-type .ai-assist-input', text: BENCHMARK_PROMPT, perChar: 22 },
    { type: 'wait', duration: 450 },
    { type: 'click', selector: '.cell-container:last-of-type .ai-assist-btn' },
    { type: 'wait', selector: '.cell-container:last-of-type .ai-suggestion-preview .suggestion-btn.accept-overwrite', timeout: 60000 },
    { type: 'caption', text: '预热 10 次再正式推理：P50 / P95 / FPS 全部实测', duration: 4400 },
    { type: 'click', selector: '.cell-container:last-of-type .suggestion-actions .suggestion-btn:nth-child(1)' },
    { type: 'wait', duration: 800 },
    { type: 'click', selector: '.cell-container:last-of-type .run-cell-btn' },
    { type: 'wait', selector: '.cell-container:last-of-type .output-plot-img', timeout: 240000 },
    { type: 'caption', text: 'MR-100 负载拉起：顶部利用率与功耗同步跳动', duration: 4400 },
    { type: 'wait', duration: 1500 },
    { type: 'highlight', selector: '.cell-container:last-of-type .cell-output-area', duration: 2200 },
    { type: 'caption', text: '实测延迟曲线与统计表：这不是模拟数据', duration: 4200 },
    { type: 'wait', duration: 1400 },

    // S5 2:25-3:00 错误 + AI Debug
    { type: 'caption', text: '真实开发难免出错：输入路径写错，一键 AI 调试', duration: 4400 },
    { type: 'click', selector: '#addCodeBtn' },
    { type: 'wait', duration: 1100 },
    { type: 'click', selector: '.cell-container:last-of-type .CodeMirror' },
    { type: 'wait', duration: 500 },
    { type: 'type', selector: '.cell-container:last-of-type .CodeMirror textarea', text: ERROR_CODE, perChar: 20 },
    { type: 'wait', duration: 500 },
    { type: 'click', selector: '.cell-container:last-of-type .run-cell-btn' },
    { type: 'wait', selector: '.cell-container:last-of-type .ai-debug-bar', timeout: 60000 },
    { type: 'caption', text: 'FileNotFoundError：AI 结合代码与真实报错开始诊断', duration: 4200 },
    { type: 'wait', duration: 900 },
    { type: 'click', selector: '.cell-container:last-of-type .ai-debug-btn.primary' },
    { type: 'wait', selector: '.cell-container:last-of-type .suggestion-btn.accept-overwrite', timeout: 60000 },
    { type: 'wait', duration: 1200 },
    { type: 'zoom', selector: '.cell-container:last-of-type .ai-debug-preview', duration: 1150 },
    { type: 'caption', text: '指出路径不存在 → 建议前置检查 → 生成修复代码', duration: 4400 },
    { type: 'wait', duration: 1200 },
    { type: 'zoomReset' },
    { type: 'click', selector: '.cell-container:last-of-type .suggestion-actions .suggestion-btn:nth-child(2)' },
    { type: 'wait', duration: 5200 },
    { type: 'highlight', selector: '.cell-container:last-of-type .cell-output-area', duration: 2000 },
    { type: 'caption', text: '一键修复并重跑：检测恢复正常', duration: 3800 },
    { type: 'wait', duration: 1100 },

    // S6 3:00-3:35 AI 总结（独立 /agent/ 页）
    { type: 'goto', url: 'http://127.0.0.1:5000/agent/' },
    { type: 'wait', duration: 3600 },
    { type: 'caption', text: 'AI 助手自动携带 Notebook 运行时上下文（变量表 + 最近输出）', duration: 4400 },
    { type: 'click', selector: '#chat-input' },
    { type: 'type', selector: '#chat-input', text: SUMMARY_PROMPT, perChar: 22 },
    { type: 'key', key: 'Enter' },
    { type: 'wait', duration: 7500 },
    { type: 'caption', text: '汇总检测结果与性能数据，并给出吞吐优化建议', duration: 4600 },
    { type: 'wait', duration: 1800 },

    // S7 3:35-4:00 收尾
    { type: 'goto', url: 'http://127.0.0.1:5000/' },
    { type: 'wait', duration: 2600 },
    { type: 'caption', text: '从代码生成、模型推理、硬件监控，到错误诊断和结果总结', duration: 4800 },
    { type: 'highlight', selector: '#gpuDashboard', duration: 2200 },
    { type: 'wait', duration: 900 },
    { type: 'endcard', title: 'AI 辅助的 MR-100 目标检测与推理性能分析', subtitle: 'Iluvatar AI Notebook · 天数智芯 MR-100', duration: 4800 },
  ],
})
