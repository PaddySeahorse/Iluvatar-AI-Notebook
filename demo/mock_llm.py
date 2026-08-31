import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOST, PORT = "127.0.0.1", 5055

DEBUG_REPLY = (
    "错误原因：print() 中用 + 号把字符串与 numpy.ndarray 直接拼接，"
    "Python 不允许 str 与 ndarray 相加，因此抛出 TypeError。\n\n"
    "```python\n"
    "import numpy as np\n\n"
    "x = np.array([1, 2, 3])\n"
    "print(\"结果是：\", x)\n"
    "```\n"
)

FILE_DEBUG_REPLY = (
    "错误原因：model.predict() 的输入图片 assets/not-exist.jpg 在当前工作目录中"
    "不存在，ultralytics 读取文件时抛出 FileNotFoundError。\n\n"
    "修复建议：先用 os.path.exists() 对输入路径做前置检查，再改用已准备的\n"
    "assets/demo.jpg。\n\n"
    "```python\n"
    "import os\n\n"
    "image_path = \"assets/demo.jpg\"\n"
    "assert os.path.exists(image_path), f\"输入图片不存在: {image_path}\"\n"
    "results = model.predict(image_path, device=device, imgsz=640, conf=0.25,\n"
    "                        verbose=False)\n"
    "print(f\"检出目标: {len(results[0].boxes)} 个\")\n"
    "```\n"
)

CHAT_REPLY = (
    "你好！我是 Iluvatar AI Notebook 内置的 AI 助手。这个 Notebook 面向天数智芯"
    "（Iluvatar Corex）国产 AI 芯片，我在浏览器里就能帮你写代码、执行数据分析、"
    "诊断运行报错，也能直接调用工具查询内核变量、GPU 状态和工作区文件。"
    "当前演示环境跑在 CPU 上，你可以随时向我提问。"
)

KERNEL_REPLY = (
    "内核运行正常：Python 内核存活，watchdog 守护进程工作中。"
    "当前命名空间里保存着你最近定义的变量，需要的话我可以列出它们，"
    "也可以直接帮你执行一段代码验证。"
)

PLOT_CODE = (
    "import numpy as np\n"
    "import matplotlib.pyplot as plt\n\n"
    "x = np.linspace(0, 2 * np.pi, 200)\n"
    "y = np.sin(x)\n"
    "plt.figure(figsize=(6, 4))\n"
    "plt.plot(x, y, linewidth=2)\n"
    "plt.title('Sinusoidal Curve - Iluvatar AI Notebook')\n"
    "plt.grid(True)\n"
    "plt.show()"
)

AGENT_FINAL_REPLY = (
    "绘图代码已经在 Notebook 内核里执行完成，正弦曲线生成成功。"
    "你可以继续让我调整曲线样式、更换函数，或者查看内核当前的变量状态。"
)

SUMMARY_REPLY = (
    "本次实验在测试图片中检测出 5 个目标，包括公交巴士和多名行人，置信度整体较高。"
    "从延迟曲线看，预热完成后各次推理延迟稳定，P95 与平均延迟接近，没有明显毛刺，"
    "说明 MR-100 上的推理负载平稳。平均延迟代表典型单帧耗时，P95 反映最慢 5% 请求"
    "的上限，FPS 是每秒可处理的帧数。要进一步提升吞吐，可以开启 FP16/INT8 量化"
    "推理，或将多张图片组成 Batch 一次性提交。"
)

PLOT_KEYWORDS = ("画", "曲线", "绘图", "plot", "sin", "图")
KERNEL_KEYWORDS = ("内核", "变量", "状态", "kernel")

INFERENCE_PROMPT_KEYWORDS = ("目标检测推理代码", "YOLOv8")
BENCHMARK_PROMPT_KEYWORDS = ("复用已经加载的模型", "预热 10 次")
DEBUG_PROMPT_KEYWORD = "调试单元格代码"
SUMMARY_PROMPT_KEYWORDS = ("总结", "检测到了哪些目标")


def _cell_code(name):
    """Read a demo cell verbatim so the mock always returns validated code."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cells", name)
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().rstrip()
    except OSError:
        return f"# (demo cell {name} not found on the mock host)"


def route_plain_reply(user_text):
    """Pick the canned reply for a plain (non-tool) chat-completion call.

    Shared by the streaming and non-streaming paths so both stay in sync.
    """
    if DEBUG_PROMPT_KEYWORD in user_text:
        if "not-exist.jpg" in user_text:
            return FILE_DEBUG_REPLY
        return DEBUG_REPLY
    if any(k in user_text for k in INFERENCE_PROMPT_KEYWORDS):
        return _cell_code("inference_cell.py")
    if any(k in user_text for k in BENCHMARK_PROMPT_KEYWORDS):
        return _cell_code("benchmark_cell.py")
    if any(k in user_text for k in SUMMARY_PROMPT_KEYWORDS):
        return SUMMARY_REPLY
    return CHAT_REPLY


def _messages(payload):
    return payload.get("messages") or []


def _last_user_text(messages):
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(
                    p.get("text", "") for p in content if isinstance(p, dict)
                )
    return ""


def _has_tool_result(messages):
    return any(msg.get("role") == "tool" for msg in messages)


def _is_probe(payload, messages):
    return bool(payload.get("tools")) and _last_user_text(messages).strip() == "ping"


def _completion(payload, message, finish="stop"):
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": payload.get("model", "dsv4"),
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
    }


def _tool_call_completion(payload):
    arguments = json.dumps({"code": PLOT_CODE}, ensure_ascii=False)
    message = {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {
                "id": "call_mock_1",
                "type": "function",
                "function": {"name": "run_cell", "arguments": arguments},
            }
        ],
    }
    return _completion(payload, message, finish="tool_calls")


def _sse(payload_json):
    return f"data: {payload_json}\n\n"


def sse_stream_chunks(reply, model="dsv4", first_delay=0.7, chars_per_chunk=2,
                      chunk_delay=0.035):
    """Yield encoded SSE frames for ``reply`` (trailing ``[DONE]`` included).

    ``first_delay`` simulates time-to-first-token. Long replies (generated
    code) stream faster via larger ``chars_per_chunk`` so code generation
    finishes in a couple of seconds.
    """
    if first_delay:
        time.sleep(first_delay)
    for i in range(0, len(reply), chars_per_chunk):
        chunk = {
            "id": "chatcmpl-mock",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {"content": reply[i : i + chars_per_chunk]}}],
        }
        yield _sse(json.dumps(chunk, ensure_ascii=False)).encode("utf-8")
        if chunk_delay:
            time.sleep(chunk_delay)
    yield b"data: [DONE]\n\n"


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"[mock_llm] {self.address_string()} {fmt % args}", flush=True)

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/health", "/health/liveliness"):
            self._json({"ok": True, "status": "mock alive"})
            return
        self._json({"error": "not found"}, status=404)

    def _stream_sse(self, payload, reply, first_delay=0.7, chars_per_chunk=2,
                    chunk_delay=0.035):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for frame in sse_stream_chunks(reply, model=payload.get("model", "dsv4"),
                                           first_delay=first_delay,
                                           chars_per_chunk=chars_per_chunk,
                                           chunk_delay=chunk_delay):
                self.wfile.write(frame)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._json({"error": "bad json"}, status=400)
            return

        messages = _messages(payload)
        stream = bool(payload.get("stream"))

        if _is_probe(payload, messages):
            self._json(_completion(payload, {"role": "assistant", "content": ""}))
            return

        if payload.get("tools") and not _has_tool_result(messages):
            user_text = _last_user_text(messages)
            if any(k in user_text for k in PLOT_KEYWORDS):
                self._json(_tool_call_completion(payload))
            elif any(k in user_text for k in KERNEL_KEYWORDS):
                self._json(_completion(payload, {"role": "assistant", "content": KERNEL_REPLY}))
            else:
                self._json(_completion(payload, {"role": "assistant", "content": CHAT_REPLY}))
            return

        if _has_tool_result(messages):
            self._json(_completion(payload, {"role": "assistant", "content": AGENT_FINAL_REPLY}))
            return

        reply = route_plain_reply(_last_user_text(messages))

        if not stream:
            self._json(_completion(payload, {"role": "assistant", "content": reply}))
            return

        # Generated code is long: stream 20 chars per frame with a short gap
        # so the Copilot preview finishes typing in a few seconds.
        chars = 20 if "```" in reply or reply.startswith(("import", "from", "#")) else 2
        self._stream_sse(payload, reply, chars_per_chunk=chars,
                         chunk_delay=0.012 if chars > 2 else 0.035)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[mock_llm] listening on http://{HOST}:{PORT}/v1", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
