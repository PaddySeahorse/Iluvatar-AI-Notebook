"""Chainlit 应用：AI 助手聊天（方案三，挂载到 FastAPI 统一入口的 /agent）。

本文件是 ``chainlit.utils.mount_chainlit`` 的 target：由 :mod:`app_fastapi`
在构造时加载（``app.mount("/agent", chainlit_app)``），无需独立进程。

架构（单进程、单端口 ``OPENI_SELF_PORT``）：

* FastAPI（ASGI）作为主进程，监听 ``OPENI_SELF_PORT``。
  Notebook 主界面走 ``/``，聊天界面走 ``/agent``（由本文件提供 UI 逻辑）。
* FastAPI 路由与 Chainlit 共享同一个 ``kernel_manager``
  （``core.state.app_state``，由 ``app_fastapi`` 的 lifespan 负责启动/停止），
  因此聊天里执行代码与 Notebook 里执行代码落到同一内核，变量互通。

本模块完全复用 ``core.agent.agent_loop`` 与 ``core.tools``，只负责把
SSE 事件映射到 Chainlit UI 原语。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
from typing import Dict, List

# 项目根目录入 sys.path，保证 ``core.*`` 可导入（mount_chainlit 也会注入，
# 幂等无副作用）。
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import chainlit as cl  # noqa: E402

from core.agent import agent_loop  # noqa: E402
from core.state import app_state  # noqa: E402

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LLM 配置（env 优先，回退到共享运行时默认值；save_config / apply_saved_config
# 都会同步 env 与 app_state，因此两条链路的取值始终一致）
# ---------------------------------------------------------------------------

def _llm_config() -> Dict[str, str]:
    """返回当前 LLM 连接三元组（环境变量优先，已由 app_fastapi 恢复配置）。"""
    return {
        "url": os.environ.get("OPENI_API_URL", "") or app_state.DEFAULT_API_URL or "",
        "token": os.environ.get("OPENI_API_TOKEN", "") or app_state.DEFAULT_API_TOKEN or "",
        "model": os.environ.get("OPENI_API_MODEL", "") or app_state.DEFAULT_API_MODEL or "dsv4",
    }


# ---------------------------------------------------------------------------
# Chainlit 生命周期钩子
# ---------------------------------------------------------------------------

@cl.set_starters
async def starters() -> List[cl.Starter]:
    """首页快捷提问。"""
    return [
        cl.Starter(
            label="查询 GPU 状态",
            message="当前天数智芯 GPU 的状态如何？",
            description="查询 Iluvatar GPU 遥测（利用率/显存/温度/功耗）",
        ),
        cl.Starter(
            label="列出工作区笔记本",
            message="列出工作区里的所有 notebook 文件",
            description="浏览可用的 .ipynb 文件",
        ),
        cl.Starter(
            label="运行一段代码",
            message='在内核里运行：print("Hello from Iluvatar AI Notebook")',
            description="执行 Python 代码单元",
        ),
        cl.Starter(
            label="检查内核状态",
            message="Python 内核是否存活？",
            description="检查内核与 watchdog 状态",
        ),
    ]


@cl.on_chat_start
async def on_chat_start() -> None:
    """初始化会话状态并提示 Notebook 位置。"""
    cl.user_session.set("history", [])
    cl.user_session.set("include_context", True)
    cl.user_session.set("max_steps", 6)

    cfg = _llm_config()
    if not (cfg["url"] and cfg["model"]):
        await cl.Message(
            content=(
                "**上游模型 API 未配置。**\n\n"
                "请先在 Notebook（左侧面板 → 设置）里保存模型配置，"
                "应用会自启动本地 LiteLLM Proxy 并自动路由到该模型。"
            ),
        ).send()


# ---------------------------------------------------------------------------
# 事件映射：把 agent_loop 的事件实时转为 Chainlit UI
# ---------------------------------------------------------------------------

def _run_agent_in_thread(
    loop: asyncio.AbstractEventLoop, queue: asyncio.Queue, **kwargs
) -> None:
    """在后台线程运行同步 generator，把事件投递到 asyncio 队列。

    ``agent_loop`` 是同步 generator，直接在主线程迭代会阻塞事件循环；
    这里放到线程里逐条产出，通过 ``call_soon_threadsafe`` 桥接回事件循环，
    实现实时流式（工具 Step 即时出现、最终回答打字机式输出）。
    """
    try:
        for event in agent_loop(**kwargs):
            loop.call_soon_threadsafe(queue.put_nowait, event)
    except Exception as exc:  # noqa: BLE001 - 兜底，把异常交给 UI
        loop.call_soon_threadsafe(
            queue.put_nowait, {"type": "error", "message": f"{exc.__class__.__name__}: {exc}"}
        )
    finally:
        loop.call_soon_threadsafe(queue.put_nowait, None)  # 结束哨兵


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """处理用户消息：运行 ReAct agent 并流式渲染结果。"""
    history: List[Dict] = cl.user_session.get("history", [])
    include_context: bool = cl.user_session.get("include_context", True)
    max_steps: int = cl.user_session.get("max_steps", 6)

    cfg = _llm_config()
    if not (cfg["url"] and cfg["model"]):
        await cl.Message(
            content="上游模型 API 未配置，请先在 Notebook 里保存模型配置。"
        ).send()
        return

    thinking_msg = cl.Message(content="思考中…")
    await thinking_msg.send()

    # 后台线程运行 agent_loop，事件实时桥接回事件循环。
    loop = asyncio.get_running_loop()
    event_queue: asyncio.Queue = asyncio.Queue()
    threading.Thread(
        target=_run_agent_in_thread,
        args=(loop, event_queue),
        kwargs={
            "url": cfg["url"],
            "token": cfg["token"],
            "model": cfg["model"],
            "history": history,
            "query": message.content,
            "include_context": include_context,
            # 与 Notebook 共享同一内核：agent_loop 经 state_module 读取
            # kernel_manager / WORKSPACE_DIR / is_safe_path。
            "state_module": app_state,
            "max_steps": max_steps,
        },
        daemon=True,
    ).start()

    final_answer = ""
    current_step: cl.Step | None = None
    streaming_msg: cl.Message | None = None
    thinking_active = True

    while True:
        event = await event_queue.get()
        if event is None:
            break

        etype = event.get("type")

        if etype == "status":
            continue

        if etype == "tool_call":
            label = event.get("label") or event.get("name", "工具")
            current_step = cl.Step(name=label, type="tool")
            args = event.get("arguments", {})
            current_step.input = (
                args if isinstance(args, str) else json.dumps(args, ensure_ascii=False, indent=2)
            )
            current_step.show_input = "json"
            await current_step.send()

        elif etype == "tool_result":
            if current_step is not None:
                current_step.output = event.get("summary", "")
                current_step.is_error = not event.get("ok", False)
                await current_step.update()
                current_step = None

        elif etype == "content":
            token = event.get("text", "")
            if not token:
                continue
            if thinking_active:
                await thinking_msg.remove()
                thinking_active = False
                streaming_msg = cl.Message(content="")
            if streaming_msg is not None:
                final_answer += token
                await streaming_msg.stream_token(token)

        elif etype == "done":
            done_text = event.get("final", "")
            if done_text and not final_answer:
                if thinking_active:
                    await thinking_msg.remove()
                    thinking_active = False
                await cl.Message(content=done_text).send()
                final_answer = done_text

        elif etype == "error":
            if thinking_active:
                await thinking_msg.remove()
                thinking_active = False
            await cl.Message(content=f"**出错了：** {event.get('message', '未知错误')}").send()

    # 若全程无输出，清掉占位提示。
    if thinking_active:
        await thinking_msg.remove()

    # 更新多轮对话历史。
    history.append({"role": "user", "content": message.content})
    if final_answer:
        history.append({"role": "assistant", "content": final_answer})
    cl.user_session.set("history", history)


if __name__ == "__main__":
    # 方案三：chainlit_app.py 只作为 mount target，不应独立运行。
    print(
        "chainlit_app.py 现已作为 /agent 挂载到 FastAPI 统一入口（方案三）。\n"
        "请通过 `python app_fastapi.py` 或 "
        "`uvicorn app_fastapi:app --host 0.0.0.0 --port $OPENI_SELF_PORT` 启动，"
        "然后在浏览器访问 /agent。"
    )