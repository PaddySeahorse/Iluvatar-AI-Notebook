# Iluvatar AI Notebook 内核重构详细设计

> 基于《Iluvatar AI Notebook 是否应该复用 Jupyter 的库？》分析报告，制定从手写 KernelManager 到分层复用 Jupyter 生态的详细技术设计。

---

## 1. 设计目标

### 1.1 核心原则

1. **分层解耦**：执行层（ipykernel）、管理层（jupyter_client）、差异化层（Flask + AI Copilot + GPU）各司其职
2. **向后兼容**：现有 API 端点（`/api/run_cell`、`/api/interrupt_kernel`、`/api/kernel_status`、`/api/get_variables`）的响应格式不变
3. **渐进迁移**：支持配置开关控制新旧内核，允许双轨运行
4. **最小引入**：仅引入 jupyter_client + ipykernel + pyzmq，不引入 jupyter_server/Tornado 到 Web 层

### 1.2 不做的事

- 不引入 `jupyter_server`（Flask 保留）
- 不引入 `jupyterlab` 前端（Vanilla JS 保留）
- 不改变 Notebook 文件格式（仍用 `.ipynb`，通过 nbformat 读写）
- 不改变 AI Copilot 架构

---

## 2. 目标架构

```
┌─────────────────────────────────────────────────────────────────┐
│                    Iluvatar 差异化层（保留）                       │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │  static/     │ │ core/gpu.py  │ │ core/routes/ai_routes.py │ │
│  │  Vanilla JS  │ │ IXUCA SDK    │ │ AI Copilot 代理          │ │
│  │  前端        │ │ GPU 遥测     │ │ 上下文注入/流式输出      │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │                    app.py (Flask 装配)                       │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Jupyter 复用层（新增，替换 kernel.py）          │
│  ┌──────────────────┐  ┌──────────────────┐  ┌───────────────┐ │
│  │ jupyter_client   │  │ ipykernel        │  │ nbformat      │ │
│  │ KernelManager    │  │ IPython 内核     │  │ .ipynb 读写   │ │
│  │ KernelClient     │  │ 补全/内省/Magics │  │               │ │
│  │ 5 通道通信       │  │ 富媒体/调试      │  │               │ │
│  └──────────────────┘  └──────────────────┘  └───────────────┘ │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │          IluvatarProvisioner (自定义)                        │ │
│  │          GPU 资源分配 / 环境注入 / GPU 中断                  │ │
│  └──────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       底层运行时                                 │
│  Python 子进程 (ipykernel)  +  torch-iluvatar  +  GPU 硬件      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心组件设计

### 3.1 新版 KernelManager 封装层

**文件**: `core/kernel.py`（重写）

**设计原则**：封装 jupyter_client 的 KernelManager 和 KernelClient，对外暴露与旧 API 兼容的接口。

```python
"""
Iluvatar AI Notebook — 内核管理模块（基于 jupyter_client）
"""
import os
import json
import threading
import logging
from typing import Optional, Generator, Dict, Any

from jupyter_client import KernelManager as JupyterKernelManager
from jupyter_client import find_connection_file
from jupyter_client.kernelspec import KernelSpecManager

logger = logging.getLogger(__name__)


class KernelManager:
    """
    内核管理器 — 封装 jupyter_client.KernelManager

    对外提供与旧实现兼容的接口，内部使用 jupyter_client 的
    ZMQ 五通道协议进行内核通信。
    """

    def __init__(self, kernel_name: str = "python3"):
        self._kernel_name = kernel_name
        self._km: Optional[JupyterKernelManager] = None
        self._kc = None
        self._lock = threading.Lock()
        self._warm_started = False

    # ── 生命周期管理 ─────────────────────────────────

    def start(self) -> None:
        """启动内核"""
        with self._lock:
            if self._km is not None and self._km.is_alive():
                return
            self._km = JupyterKernelManager(kernel_name=self._kernel_name)
            self._km.start_kernel()
            self._kc = self._km.client()
            self._kc.start_channels()
            self._kc.wait_for_ready()
            logger.info("Kernel started: %s", self._km.kernel_id)

    def warm_start(self) -> None:
        """预热启动（应用启动时调用）"""
        if self._warm_started:
            return
        self.start()
        self._warm_started = True

    def shutdown(self) -> None:
        """关闭内核"""
        with self._lock:
            if self._kc is not None:
                self._kc.stop_channels()
            if self._km is not None:
                self._km.shutdown_kernel(now=True)
            self._km = None
            self._kc = None

    def restart(self) -> None:
        """重启内核"""
        with self._lock:
            if self._km is not None:
                self._km.restart_kernel()
                self._kc = self._km.client()
                self._kc.start_channels()
                self._kc.wait_for_ready()

    def is_alive(self) -> bool:
        """检查内核是否存活"""
        if self._km is None:
            return False
        return self._km.is_alive()

    # ── 代码执行 ─────────────────────────────────────

    def execute(self, code: str) -> Dict[str, Any]:
        """
        同步执行代码（兼容旧 API）

        返回格式与旧实现一致：
        {
            "stdout": "...",
            "stderr": "...",
            "plots": ["base64..."],
            "html": ["..."],
            "error": None | str
        }
        """
        result = {
            "stdout": "",
            "stderr": "",
            "results": [],
            "plots": [],
            "html": [],
            "error": None,
        }

        if self._kc is None:
            result["error"] = "Kernel not started"
            return result

        msg_id = self._kc.execute(code)

        # 收集所有 IOPub 消息直到 idle
        for msg in self._kc.iopub_channel():
            self._handle_execution_message(msg, result, msg_id)

        return result

    def execute_stream(self, code: str) -> Generator[Dict[str, Any], None, None]:
        """
        流式执行代码（新增 API）

        Yields 消息字典，用于 SSE 推送到前端。
        消息类型：
        - {"type": "stream", "name": "stdout", "text": "..."}
        - {"type": "stream", "name": "stderr", "text": "..."}
        - {"type": "display_data", "data": {...}}
        - {"type": "execute_result", "data": {...}, "execution_count": N}
        - {"type": "error", "ename": "...", "evalue": "...", "traceback": [...]}
        - {"type": "status", "execution_state": "busy"|"idle"}
        - {"type": "execute_input", "code": "...", "execution_count": N}
        """
        if self._kc is None:
            yield {"type": "error", "evalue": "Kernel not started"}
            return

        msg_id = self._kc.execute(code)

        for msg in self._kc.iopub_channel():
            parent_id = msg.get("parent_header", {}).get("msg_id", "")
            if parent_id != msg_id:
                continue

            msg_type = msg.get("msg_type", "")
            content = msg.get("content", {})

            if msg_type == "stream":
                yield {
                    "type": "stream",
                    "name": content.get("name", "stdout"),
                    "text": content.get("text", ""),
                }
            elif msg_type == "display_data":
                yield {
                    "type": "display_data",
                    "data": content.get("data", {}),
                    "metadata": content.get("metadata", {}),
                }
            elif msg_type == "execute_result":
                yield {
                    "type": "execute_result",
                    "data": content.get("data", {}),
                    "execution_count": content.get("execution_count"),
                }
            elif msg_type == "error":
                yield {
                    "type": "error",
                    "ename": content.get("ename", ""),
                    "evalue": content.get("evalue", ""),
                    "traceback": content.get("traceback", []),
                }
            elif msg_type == "status":
                yield {
                    "type": "status",
                    "execution_state": content.get("execution_state", ""),
                }
                if content.get("execution_state") == "idle":
                    break

    def _handle_execution_message(self, msg, result, msg_id):
        """处理单条 IOPub 消息（同步模式）"""
        parent_id = msg.get("parent_header", {}).get("msg_id", "")
        if parent_id != msg_id:
            return

        msg_type = msg.get("msg_type", "")
        content = msg.get("content", {})

        if msg_type == "stream":
            if content.get("name") == "stderr":
                result["stderr"] += content.get("text", "")
            else:
                result["stdout"] += content.get("text", "")
        elif msg_type == "display_data":
            data = content.get("data", {})
            if "image/png" in data:
                result["plots"].append(data["image/png"])
            if "text/html" in data:
                result["html"].append(data["text/html"])
        elif msg_type == "execute_result":
            data = content.get("data", {})
            if "text/plain" in data:
                result["results"].append(data["text/plain"])
        elif msg_type == "error":
            result["error"] = "\n".join(content.get("traceback", []))

    # ── 中断 ─────────────────────────────────────────

    def interrupt(self) -> bool:
        """中断内核执行"""
        if self._km is None:
            return False
        try:
            self._km.interrupt_kernel()
            return True
        except Exception as e:
            logger.error("Failed to interrupt kernel: %s", e)
            return False

    # ── 代码补全 ─────────────────────────────────────

    def complete(self, code: str, cursor_pos: int) -> Dict[str, Any]:
        """
        代码补全

        Returns:
            {
                "matches": ["candidate1", "candidate2", ...],
                "cursor_start": int,
                "cursor_end": int,
                "metadata": {}
            }
        """
        if self._kc is None:
            return {"matches": [], "cursor_start": 0, "cursor_end": cursor_pos}

        try:
            reply = self._kc.complete(code, cursor_pos)
            content = reply.get("content", {})
            return {
                "matches": content.get("matches", []),
                "cursor_start": content.get("cursor_start", 0),
                "cursor_end": content.get("cursor_end", cursor_pos),
                "metadata": content.get("metadata", {}),
            }
        except Exception as e:
            logger.error("Complete failed: %s", e)
            return {"matches": [], "cursor_start": 0, "cursor_end": cursor_pos}

    # ── 内省 ─────────────────────────────────────────

    def inspect(self, code: str, cursor_pos: int, detail_level: int = 0) -> Dict[str, Any]:
        """
        对象内省（? 和 ?? 功能）

        Args:
            code: 当前代码
            cursor_pos: 光标位置
            detail_level: 0 = 普通（?），1 = 详细（??）

        Returns:
            {"found": bool, "data": {"text/plain": "..."}}
        """
        if self._kc is None:
            return {"found": False, "data": {}}

        try:
            reply = self._kc.inspect(code, cursor_pos, detail_level)
            content = reply.get("content", {})
            return {
                "found": content.get("found", False),
                "data": content.get("data", {}),
            }
        except Exception as e:
            logger.error("Inspect failed: %s", e)
            return {"found": False, "data": {}}

    # ── 变量查看 ─────────────────────────────────────

    def get_variables(self) -> Dict[str, Any]:
        """
        获取当前命名空间中的变量（兼容旧 API）

        通过执行 %who 和 %whos 获取变量列表，
        通过 inspect 获取变量值。
        """
        # 使用同步执行获取变量列表
        result = self.execute("%who_ls")
        if result["error"]:
            return {"variables": [], "error": result["error"]}

        # 解析变量名列表
        var_names = []
        for line in result["stdout"].strip().split("\n"):
            for name in line.strip("[]").replace("'", "").split(","):
                name = name.strip()
                if name:
                    var_names.append(name)

        variables = []
        for name in var_names[:50]:  # 限 50 个变量
            inspect_result = self.inspect(name, len(name))
            if inspect_result["found"]:
                variables.append({
                    "name": name,
                    "type": "variable",
                    "doc": inspect_result["data"].get("text/plain", ""),
                })

        return {"variables": variables}
```

### 3.2 路由层改造

**文件**: `core/routes/kernel_routes.py`（改造）

```python
"""
内核相关路由 — 基于 jupyter_client 的新实现
"""
import json
import time
from flask import Blueprint, request, Response, jsonify, stream_with_context

from core.kernel import KernelManager

kernel_bp = Blueprint("kernel", __name__, url_prefix="/api")

# 从 app 工厂获取 kernel_manager 实例
# 在 app.py 中: kernel_manager = KernelManager(); kernel_manager.warm_start()


def register_kernel_routes(app, kernel_manager: KernelManager):
    """注册内核路由（替代全局 Blueprint 模式）"""

    @app.route("/api/run_cell", methods=["POST"])
    def run_cell():
        """
        同步执行代码（兼容旧 API）

        请求: {"code": "...", "settings": {...}}
        响应: {"stdout": "...", "stderr": "...", "plots": [...], "html": [...], "error": null}
        """
        data = request.get_json()
        code = data.get("code", "")

        if not code.strip():
            return jsonify({"stdout": "", "stderr": "", "plots": [], "html": [], "error": None})

        result = kernel_manager.execute(code)
        return jsonify(result)

    @app.route("/api/run_cell_stream", methods=["POST"])
    def run_cell_stream():
        """
        流式执行代码（新增 API）

        通过 SSE 推送执行过程中的实时输出。

        请求: {"code": "..."}
        响应: text/event-stream
        """
        data = request.get_json()
        code = data.get("code", "")

        if not code.strip():
            return jsonify({"error": "Empty code"}), 400

        def generate():
            for msg in kernel_manager.execute_stream(code):
                yield f"data: {json.dumps(msg)}\n\n"
            yield "data: [DONE]\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    @app.route("/api/interrupt_kernel", methods=["POST"])
    def interrupt_kernel():
        """中断内核"""
        success = kernel_manager.interrupt()
        if success:
            return jsonify({"status": "interrupted", "message": "Kernel interrupted"})
        else:
            return jsonify({"status": "error", "message": "Failed to interrupt"}), 500

    @app.route("/api/kernel_status", methods=["GET"])
    def kernel_status():
        """查询内核状态"""
        alive = kernel_manager.is_alive()
        return jsonify({
            "alive": alive,
            "kernel_name": kernel_manager._kernel_name if alive else None,
        })

    @app.route("/api/complete", methods=["POST"])
    def complete():
        """代码补全（新增）"""
        data = request.get_json()
        code = data.get("code", "")
        cursor_pos = data.get("cursor_pos", len(code))

        result = kernel_manager.complete(code, cursor_pos)
        return jsonify(result)

    @app.route("/api/inspect", methods=["POST"])
    def inspect():
        """对象内省（新增）"""
        data = request.get_json()
        code = data.get("code", "")
        cursor_pos = data.get("cursor_pos", len(code))
        detail_level = data.get("detail_level", 0)

        result = kernel_manager.inspect(code, cursor_pos, detail_level)
        return jsonify(result)

    @app.route("/api/get_variables", methods=["GET"])
    def get_variables():
        """获取变量列表（兼容旧 API）"""
        result = kernel_manager.get_variables()
        return jsonify(result)
```

### 3.3 IluvatarProvisioner 设计

**文件**: `core/iluvatar_provisioner.py`

```python
"""
Iluvatar GPU 专用内核启动器

基于 Jupyter Kernel Provisioner API 实现，
为天数智芯 GPU 芯片提供专用资源管理。
"""
import os
import signal
import asyncio
import logging
from typing import Any, Dict

from jupyter_client.provisioning import KernelProvisionerBase

logger = logging.getLogger(__name__)


class IluvatarProvisioner(KernelProvisionerBase):
    """
    天数智芯 GPU 专用内核启动器

    功能：
    1. 自动注入 Iluvatar SDK 环境变量
    2. GPU 资源分配与隔离
    3. GPU 专用中断（优于 SIGINT）
    """

    # ── 配置 ─────────────────────────────────────────

    @property
    def has_process(self) -> bool:
        """Provisiner 是否管理进程"""
        return True

    # ── 启动前 ───────────────────────────────────────

    async def pre_launch(self, **kwargs: Any) -> Dict[str, Any]:
        """
        内核启动前的准备工作

        - 设置 GPU 环境变量
        - 分配 GPU 设备
        """
        env = kwargs.setdefault("env", os.environ.copy())

        # Iluvatar SDK 环境变量
        env.setdefault("ILUVATAR_KERNEL_TYPE", "ai-optimized")
        env.setdefault("IXUCA_VISIBLE_DEVICES", self._get_assigned_gpu())

        # 确保 IXUCA SDK 库路径可用
        ixuca_lib = os.environ.get("IXUCA_LIB_PATH", "/usr/local/ixuca/lib")
        existing_ld = env.get("LD_LIBRARY_PATH", "")
        if ixuca_lib not in existing_ld:
            env["LD_LIBRARY_PATH"] = f"{ixuca_lib}:{existing_ld}".strip(":")

        # 设置 GPU 缓存目录
        env.setdefault("ILUVATAR_CACHE_DIR", "/tmp/iluvatar-cache")

        kwargs["env"] = env

        logger.info(
            "IluvatarProvisioner pre_launch: GPU=%s",
            env.get("IXUCA_VISIBLE_DEVICES"),
        )

        return kwargs

    def _get_assigned_gpu(self) -> str:
        """
        获取分配的 GPU 设备 ID

        策略：
        1. 检查 ILUVATAR_GPU_ASSIGNMENT 环境变量（外部调度器设置）
        2. 检查 ILUVATAR_GPU_POOL 中的可用设备
        3. 默认返回 "0"
        """
        # 外部调度器已分配
        assignment = os.environ.get("ILUVATAR_GPU_ASSIGNMENT")
        if assignment:
            return assignment

        # 简单策略：返回第一个可用 GPU
        # 生产环境应替换为更复杂的调度逻辑
        try:
            import subprocess
            result = subprocess.run(
                ["ixuca-smi", "--query-gpu=index", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                gpus = [g.strip() for g in result.stdout.strip().split("\n") if g.strip()]
                if gpus:
                    return gpus[0]  # 返回第一个可用 GPU
        except Exception:
            pass

        return "0"

    # ── 启动 ─────────────────────────────────────────

    async def launch_kernel(self, cmd: list, **kwargs: Any) -> Any:
        """
        启动内核进程

        使用父类默认的进程启动逻辑，但可以在此处添加：
        - 容器化启动（Docker/Singularity）
        - 资源限制（cgroup）
        - GPU 亲和性绑定
        """
        logger.info("IluvatarProvisioner launching kernel: %s", cmd)
        return await super().launch_kernel(cmd, **kwargs)

    # ── 中断 ─────────────────────────────────────────

    async def send_signal(self, signum: int) -> None:
        """
        发送信号到内核进程

        对于 SIGINT，优先尝试 Iluvatar GPU 专用中断，
        如果不可用，回退到标准 SIGINT。
        """
        if signum == signal.SIGINT:
            await self._iluvatar_gpu_interrupt()

        await super().send_signal(signum)

    async def _iluvatar_gpu_interrupt(self) -> None:
        """
        Iluvatar GPU 专用中断

        尝试通过 IXUCA 驱动中断 GPU 计算，
        如果 IXUCA 不可用，回退到普通 SIGINT。
        """
        try:
            # 尝试通过 ixuca-smi 终止 GPU 计算
            gpu_id = self._get_assigned_gpu()
            proc = await asyncio.create_subprocess_exec(
                "ixuca-smi", "--gpu", gpu_id, "--kill-compute",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if proc.returncode == 0:
                logger.info("GPU compute interrupted via ixuca-smi for GPU %s", gpu_id)
                return
        except Exception:
            pass

        # 回退：尝试通过 torch-iluvatar 中断
        try:
            proc = await asyncio.create_subprocess_exec(
                "python", "-c",
                "import torch; torch.cuda.set_device(torch.cuda.current_device()); "
                "print('GPU interrupt attempted')",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:
            logger.warning("GPU interrupt fallback failed")

    # ── 清理 ─────────────────────────────────────────

    async def cleanup(self, restart: bool = False) -> None:
        """
        清理 GPU 资源

        释放 GPU 显存、清理临时文件等。
        """
        gpu_id = self._get_assigned_gpu()
        try:
            proc = await asyncio.create_subprocess_exec(
                "ixuca-smi", "--gpu", gpu_id, "--reset-memory",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
        except Exception:
            pass

        await super().cleanup(restart)
```

### 3.4 kernel.json 配置

**文件**: `kernels/iluvatar_python/kernel.json`

```json
{
  "argv": [
    "python",
    "-m",
    "ipykernel_launcher",
    "-f",
    "{connection_file}"
  ],
  "display_name": "Iluvatar AI Python 3",
  "language": "python",
  "metadata": {
    "kernel_provisioner": {
      "provisioner_name": "iluvatar-provisioner"
    },
    "debugger": true
  },
  "env": {
    "ILUVATAR_KERNEL_TYPE": "ai-optimized"
  }
}
```

**entry_points 注册**（`setup.py` 或 `pyproject.toml`）：

```python
# setup.py
entry_points={
    "jupyter_client.kernel_provisioners": [
        "iluvatar-provisioner = core.iluvatar_provisioner:IluvatarProvisioner",
    ],
}
```

---

## 4. 数据流设计

### 4.1 同步执行流程（兼容旧 API）

```
POST /api/run_cell {"code": "print('hello')"}
  │
  ▼
kernel_routes.run_cell()
  │
  ▼
KernelManager.execute(code)
  │
  ├─► kc.execute(code) ──► shell 通道发送 execute_request
  │
  ├─► for msg in kc.iopub_channel():  ← 阻塞直到 idle
  │     ├─ stream (stdout) → result["stdout"] += text
  │     ├─ stream (stderr) → result["stderr"] += text
  │     ├─ display_data    → result["plots"].append(png)
  │     ├─ execute_result  → result["results"].append(text)
  │     ├─ error           → result["error"] = traceback
  │     └─ status: idle    → break
  │
  ▼
返回 JSON {"stdout": "hello\n", "stderr": "", "plots": [], ...}
```

### 4.2 流式执行流程（新 API）

```
POST /api/run_cell_stream {"code": "for i in range(100):\n  print(i); time.sleep(0.1)"}
  │
  ▼
kernel_routes.run_cell_stream()
  │
  ▼
KernelManager.execute_stream(code) → Generator
  │
  ├─► yield {"type": "status", "execution_state": "busy"}
  ├─► yield {"type": "stream", "name": "stdout", "text": "0\n"}
  ├─► yield {"type": "stream", "name": "stdout", "text": "1\n"}
  ├─► ...
  ├─► yield {"type": "stream", "name": "stdout", "text": "99\n"}
  └─► yield {"type": "status", "execution_state": "idle"}
  │
  ▼
SSE Response (text/event-stream):
  data: {"type":"status","execution_state":"busy"}

  data: {"type":"stream","name":"stdout","text":"0\n"}

  data: {"type":"stream","name":"stdout","text":"1\n"}

  ...

  data: {"type":"status","execution_state":"idle"}

  data: [DONE]
```

### 4.3 中断流程

```
POST /api/interrupt_kernel
  │
  ▼
KernelManager.interrupt()
  │
  ├─► km.interrupt_kernel()
  │     │
  │     ├─► control 通道发送 interrupt_request 消息
  │     │   （即使 shell 通道被 GPU 计算阻塞，control 通道仍可工作）
  │     │
  │     └─► IluvatarProvisioner.send_signal(SIGINT)
  │           │
  │           ├─► ixuca-smi --kill-compute (GPU 专用中断)
  │           └─► os.kill(SIGINT) (fallback)
  │
  ▼
返回 {"status": "interrupted"}
```

---

## 5. 接口契约

### 5.1 对外 API 兼容性保证

| 端点 | 方法 | 请求格式 | 响应格式 | 变更 |
|------|------|---------|---------|------|
| `/api/run_cell` | POST | `{"code": "..."}` | `{"stdout": "...", "stderr": "...", "plots": [...], "html": [...], "error": null}` | **不变** |
| `/api/interrupt_kernel` | POST | 无 | `{"status": "interrupted"}` | **不变** |
| `/api/kernel_status` | GET | 无 | `{"alive": true/false}` | **不变** |
| `/api/get_variables` | GET | 无 | `{"variables": [...]}` | **不变** |
| `/api/run_cell_stream` | POST | `{"code": "..."}` | SSE 流 | **新增** |
| `/api/complete` | POST | `{"code": "...", "cursor_pos": N}` | `{"matches": [...], ...}` | **新增** |
| `/api/inspect` | POST | `{"code": "...", "cursor_pos": N, "detail_level": 0}` | `{"found": bool, "data": {...}}` | **新增** |

### 5.2 内部接口

```
KernelManager
├── start() -> None
├── warm_start() -> None
├── shutdown() -> None
├── restart() -> None
├── is_alive() -> bool
├── execute(code: str) -> Dict
├── execute_stream(code: str) -> Generator[Dict]
├── interrupt() -> bool
├── complete(code: str, cursor_pos: int) -> Dict
├── inspect(code: str, cursor_pos: int, detail_level: int) -> Dict
└── get_variables() -> Dict

IluvatarProvisioner (KernelProvisionerBase)
├── pre_launch(**kwargs) -> Dict
├── launch_kernel(cmd: list, **kwargs) -> Any
├── send_signal(signum: int) -> None
├── cleanup(restart: bool) -> None
└── has_process -> bool
```

---

## 6. ZMQ 通道说明

| 通道 | 方向 | 协议 | 用途 |
|------|------|------|------|
| **Shell** | 请求 → 内核 | ROUTER/DEALER | execute_request, complete_request, inspect_request, kernel_info_request |
| **IOPub** | 内核 → 广播 | PUB/SUB | stream（stdout/stderr）, display_data, execute_result, error, status |
| **Control** | 请求 → 内核 | ROUTER/DEALER | interrupt_request, shutdown_request（独立于 Shell，不被阻塞） |
| **Stdin** | 请求 → 内核 | ROUTER/DEALER | input_request 响应（`input()` 函数支持） |
| **Heartbeat** | 双向 | REQ/REP | 心跳检测（检测内核僵尸进程） |

---

## 7. 错误处理策略

| 场景 | 处理方式 |
|------|---------|
| 内核未启动 | 返回 `{"error": "Kernel not started"}`，HTTP 503 |
| 内核崩溃 | 自动重启（watchdog 机制），返回 `{"error": "Kernel crashed and restarted"}` |
| 执行超时 | 可配置超时时间，超时后 interrupt + 返回部分结果 |
| GPU 不可用 | Provisioner 捕获异常，回退到 CPU 模式，记录 warning |
| ZMQ 连接断开 | 重连机制（最多 3 次），失败后内核重启 |
| 补全超时 | 3 秒超时，返回空结果 |

---

## 8. 配置项

```python
# core/config.py 新增配置

KERNEL_CONFIG = {
    # 内核名称（对应 kernel.json 中的 display_name）
    "kernel_name": "python3",

    # 执行超时（秒），0 表示不限制
    "execution_timeout": 0,

    # 补全超时（秒）
    "completion_timeout": 3,

    # 心跳间隔（毫秒）
    "heartbeat_interval": 3000,

    # 是否启用 GPU Provisioner
    "use_iluvatar_provisioner": True,

    # 启动延迟容忍（秒）
    "kernel_start_timeout": 60,

    # 内核缓存目录
    "connection_file_dir": "/tmp/iluvatar-kernels",

    # 是否启用新旧内核双轨
    "use_legacy_kernel": False,
}
```

---

**文档版本**: v1.0
**最后更新**: 2026-07-08
**负责人**: 待指定