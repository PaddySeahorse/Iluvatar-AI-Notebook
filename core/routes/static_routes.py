"""Static asset and index page routes (方案三：FastAPI 版).

原 Flask 版用 ``send_from_directory`` 服务 ``/`` 与 ``/static/<path>``。
迁移后用 ``StaticFiles`` 挂载 ``/static``，``/`` 直接返回 ``index.html``。
其余 API 路由见同目录下的各 router 模块。
"""

import os

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# core/routes/../.. == 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
STATIC_DIR = os.path.join(_PROJECT_ROOT, 'static')


def register_static_routes(app):
    """Mount the static assets directory and the ``/`` index page."""
    os.makedirs(STATIC_DIR, exist_ok=True)
    app.mount('/static', StaticFiles(directory=STATIC_DIR))

    @app.get('/')
    async def index():
        return FileResponse(os.path.join(STATIC_DIR, 'index.html'))