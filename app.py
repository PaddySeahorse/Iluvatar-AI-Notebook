"""Iluvatar AI Notebook — application entry point (方案三：FastAPI).

本文件由 Flask 版迁移而来，现作为 :mod:`app_fastapi` 的兼容薄壳：保持
``python app.py`` / ``uvicorn app:app`` 命令不变，并按原名转发
``kernel_manager`` / ``WORKSPACE_DIR`` / ``is_safe_path`` /
``DEFAULT_API_*`` 等模块级符号，避免依赖这些符号的既有代码与测试需要改写。

真正的 FastAPI 应用、lifespan（内核预启动/收尾）与 Chainlit 挂载
（``/agent``）都在 :mod:`app_fastapi` 中实现。新代码请直接面向
``app_fastapi`` / ``core.state``。
"""

import os

from app_fastapi import (  # noqa: F401  # 兼容符号再导出，供外部按原名引用
    DEFAULT_API_MODEL,
    DEFAULT_API_TOKEN,
    DEFAULT_API_URL,
    WORKSPACE_DIR,
    app,
    is_safe_path,
    kernel_manager,
)

if __name__ == '__main__':
    import uvicorn

    port = int(os.environ.get('OPENI_SELF_PORT', 5000))
    host = os.environ.get('OPENI_SELF_HOST', '0.0.0.0')
    uvicorn.run(app, host=host, port=port, log_level='info')