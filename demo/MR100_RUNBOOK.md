# MR-100 真机演示执行手册

主题：AI 辅助的 MR-100 目标检测与推理性能分析（~4 分钟录屏）。

分工：推理执行、检测结果、耗时、GPU 遥测**全部真实**；仅 Copilot 生成代码、AI Debug 解释、AI Chat 总结走本地 mock（`mock_llm.py`，画面上显示启智风格配置，实际流量走本地回环，观众不可见）。

## 0. 前提

- MR-100 机器已装 IXUCA SDK、`ixsmi`、torch-iluvatar（机器自带）
- Python 3.10+、pip 可用
- 浏览器可访问 `http://127.0.0.1:5000`

## 1. 获取 demo 代码

```bash
git fetch origin demo/mr100-inference
git checkout demo/mr100-inference
```

demo/ 目录包含：录制脚本、mock LLM、单元格代码、环境准备脚本、本手册。

## 2. 环境准备（一次性）

```bash
bash demo/prep_inference_env.sh
```

- 自动安装 ultralytics（清华镜像）、生成 `assets/demo.jpg`（ultralytics 自带测试图，免外网）、下载 `models/yolov8s.pt`（多镜像）
- 末尾体检报告：**GPU 与 ixsmi 两项必须 PASS**，否则停止排查（演示必须是真实 GPU 遥测）

## 3. 单元格代码干跑（推荐）

```bash
python3 demo/dryrun_cells.py
```

无卡机器也能跑（device 自动落 CPU），验证三段单元格流程：检测出 5 个目标 + 结果图、benchmark 统计 + 曲线、`not-exist.jpg` 触发 FileNotFoundError。

## 4. 启动服务

终端 1 —— mock LLM（监听 127.0.0.1:5055）：

```bash
python3 demo/mock_llm.py
```

预置 LiteLLM 配置（**关键**：让代理流量走本地 mock，页面显示启智风格配置）：

```bash
mkdir -p ~/.Iluvatar-AI-Notebook
cp demo/litellm_config.mock.yaml ~/.Iluvatar-AI-Notebook/litellm_config.yaml
chmod 600 ~/.Iluvatar-AI-Notebook/litellm_config.yaml
```

终端 2 —— 应用：

```bash
OPENI_API_URL=https://token.openi.org.cn/v1/chat/completions
OPENI_API_TOKEN=sk-openi-demo-placeholder
OPENI_API_MODEL=dsv4
export OPENI_API_URL OPENI_API_TOKEN OPENI_API_MODEL
OPENI_SELF_PORT=5000 python3 app_fastapi.py
```

注意：
- 若这台机器以前跑过应用，先清空 `~/.Iluvatar-AI-Notebook/` 再按上面预置配置（保证干净状态），浏览器侧用全新 profile（录制工具每次新建 context，无历史污染）
- 预置配置的 `api_base` 指向 mock（127.0.0.1:5055），应用只在文件缺失时才从环境变量重写

链路验证：

```bash
curl -s -X POST http://127.0.0.1:5000/api/ai_call \
  -H "Content-Type: application/json" \
  -d '{"url":"https://token.openi.org.cn/v1/chat/completions","token":"x","model":"dsv4","messages":[{"role":"user","content":"请生成目标检测推理代码"}]}'
```

应返回 `{"content":"# MR-100 目标检测推理：..."` 开头的 YOLO 代码。同时 mock 终端出现 `POST /v1/chat/completions 200`。

## 5. Benchmark 时长标定（核心）

目标：benchmark 单元格连续执行时长落在 **8-15 秒**（GPU 看板需要足够采样窗口）。

1. 浏览器打开 Notebook，手动新建代码单元格，粘贴 `demo/cells/benchmark_cell.py` 全文，运行
2. 看输出"吞吐量 FPS"换算单次延迟：`单次ms = 1000 / FPS`
3. 计算次数：`BENCH_RUNS = round(目标秒数 × 1000 / 单次ms)`（例：单次 25ms、目标 12s → 480）
4. 修改 `demo/cells/benchmark_cell.py` 顶部的 `BENCH_RUNS`，保存即可（mock 每次请求都重新读该文件，无需重启）

## 6. 安装录制工具（真机首次）

```bash
curl -o- https://mirrors.aliyun.com/nodejs-release/v22.22.0/node-v22.22.0-linux-x64.tar.xz | tar -xJ -C /usr/local --strip-components=1
npm config set registry https://registry.npmmirror.com
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
npm install -g @matte97p/demowright@0.1.2
unset PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD
export PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright
playwright install chromium
playwright install-deps chromium
```

## 7. 录制前检查

```bash
curl -s http://127.0.0.1:5000/api/gpu_status
```

`gpu_available` 必须为 `true` 且 `name` 显示 MR-100/MR-V100。

清理遗留终端会话（避免历史 tab 入画）：

```bash
curl -s http://127.0.0.1:5000/api/terminals | python3 -m json.tool
curl -s -X DELETE http://127.0.0.1:5000/api/terminals/<id>
```

确认无其他进程占用 GPU（`ixsmi` 里 util 应接近 0）。

## 8. 正式录制

```bash
cd demo
demowright run inference.config.js -o output/mr100-inference.mp4
```

脚本 94 步全自动（~4 分钟）：环境展示 → Copilot 生成 → 真实推理 → benchmark → AI Debug → AI 总结（/agent/ 页）→ 收尾同框。中途任一步超时会中止并打印失败步骤。

## 9. 交付与目检

```bash
ls -la demo/output/
```

抽帧目检关键幕（示例）：

```bash
FF=$(dirname $(readlink -f $(which demowright)))/../lib/node_modules/@matte97p/demowright/node_modules/ffmpeg-static/ffmpeg
$FF -y -ss 95 -i demo/output/mr100-inference.mp4 -frames:v 1 /tmp/check_inference.jpg
$FF -y -ss 125 -i demo/output/mr100-inference.mp4 -frames:v 1 /tmp/check_bench.jpg
```

重点确认：顶部遥测在推理时跳动、检测框结果图、P50/P95/FPS 表格与延迟曲线、AI Debug 修复后重跑成功、收尾同框画面。

## 故障排查

| 现象 | 排查 |
| --- | --- |
| 体检报告 GPU FAIL | `python3 -c "import torch; print(torch.cuda.is_available())"`，确认 torch-iluvatar 装在当前 python |
| ai_call 返回 401/鉴权失败 | litellm_config.yaml 的 api_base 是否指向 127.0.0.1:5055/v1；`ss -tlnp | grep 4000` 确认 proxy 进程配置新鲜，必要时 kill 后重启应用 |
| Copilot 无响应/弹 alert | mock_llm.py 是否在跑（`curl 127.0.0.1:5055/health`）；应用日志中 /api/ai_call 的报错 |
| 遥测不动 | ixsmi 可用性；`curl /api/gpu_status` 观察 utilization 是否变化 |
| 录制某步超时 | 看失败步骤号与 demowright 日志；手动浏览器走一遍该步骤定位 |
