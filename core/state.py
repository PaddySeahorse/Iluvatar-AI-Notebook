"""Shared mutable runtime state (方案三：Flask → FastAPI 统一入口).

原 Flask 版（``app.py``）把 ``kernel_manager`` / ``WORKSPACE_DIR`` /
``DEFAULT_API_*`` 等作为入口模块的模块级状态暴露给 Blueprints，并通过
``app.config['_STATE_MODULE']`` 在请求时读取。迁移到 FastAPI 后，两条
链路需要共享同一份状态：

* FastAPI 路由（``core/routes/*``）在请求时经 ``request.app.state`` 读取
  :data:`app_state`（由 ``app_fastapi`` 挂载），语义与 Flask 的 request-time
  读取一致，测试仍可 monkeypatch。
* Chainlit 聊天（``chainlit_app.py``）把同一实例作为
  ``agent_loop(..., state_module=app_state)`` 的上下文，与 Notebook 共享
  同一个 ``kernel_manager``，聊天里执行的代码与 Notebook 单元落在同一内核、
  变量互通。

``KernelManager`` 在 import 时创建实例，熔点很低（不启动内核子进程）；
真正的启动 / 停止（``warm_start`` / ``shutdown``）由 ``app_fastapi`` 的
``lifespan`` 负责，保证 uvicorn 平滑退出。
"""

import os

from core.kernel import KernelManager
from core.startup_flags import apply_startup_flags
from core.utils import is_safe_path as _is_safe_path_impl

# Hardware/transport flags must be pinned before KERNEL_NAME is decided:
# the probe detects Iluvatar GPUs (ixuca-smi/ixsmi), persists setting.json
# and forces USE_OPENAI_SDK=1 unless the deployment set 0 explicitly.
apply_startup_flags()

DEFAULT_API_URL = os.environ.get(
    'OPENI_API_URL', 'https://token.openi.org.cn/v1/chat/completions'
)
DEFAULT_API_TOKEN = os.environ.get('OPENI_API_TOKEN', '')
DEFAULT_API_MODEL = os.environ.get('OPENI_API_MODEL', 'dsv4')

_USE_ILUVATAR_PROVISIONER = os.environ.get(
    'USE_ILUVATAR_PROVISIONER', 'false'
).lower() == 'true'
KERNEL_NAME = 'iluvatar_python' if _USE_ILUVATAR_PROVISIONER else 'python3'


class AppState:
    """Runtime state shared by the FastAPI routes and the Chainlit app.

    Kept intentionally small and monkeypatch-friendly: routes read attributes
    at request time, so tests can replace ``kernel_manager`` / ``WORKSPACE_DIR``
    on the singleton without touching the HTTP layer.
    """

    def __init__(self) -> None:
        self.kernel_manager = KernelManager(
            kernel_name=KERNEL_NAME,
            use_iluvatar_provisioner=_USE_ILUVATAR_PROVISIONER,
        )
        from core.terminal.manager import TerminalManager
        self.terminal_manager = TerminalManager(workspace_dir=os.path.realpath('.'))
        self.WORKSPACE_DIR = os.path.realpath('.')
        self.DEFAULT_API_URL = DEFAULT_API_URL
        self.DEFAULT_API_TOKEN = DEFAULT_API_TOKEN
        self.DEFAULT_API_MODEL = DEFAULT_API_MODEL

    def is_safe_path(self, path: str) -> bool:
        """Workspace-confined path check against the current WORKSPACE_DIR."""
        return _is_safe_path_impl(self.WORKSPACE_DIR, path)


app_state = AppState()