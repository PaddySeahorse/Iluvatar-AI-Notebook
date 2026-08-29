"""Raw ``config.yaml`` read/write routes backing the settings "高级模式".

Advanced mode exposes ``~/.Iluvatar-AI-Notebook/config.yaml`` as raw text in
the settings panel so users can edit keys beyond the basic ``OPENI_API_*``
triple. ``GET`` returns the file verbatim; ``POST`` validates the payload is
parseable YAML carrying a ``config`` mapping, persists the raw text (mode
``0600``), then applies the ``OPENI_API_*`` triple to the runtime defaults +
``os.environ`` and syncs the local LiteLLM Proxy route so changes take effect
without a restart. ``USE_*`` style toggles are saved but only take effect on
next startup — the frontend tells users this.
"""

import os

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from core.litellm_manager import litellm_manager
from core.routes import json_body, state
from core.user_config import (
    get_config_path,
    read_raw_config_content,
    write_raw_config_content,
)

router = APIRouter()


@router.get('/api/config_file')
async def get_config_file(request: Request):
    content = read_raw_config_content()
    return {
        'path': get_config_path(),
        'exists': bool(content),
        'content': content,
    }


@router.post('/api/config_file')
async def save_config_file(request: Request):
    s = state(request)
    data = await json_body(request)
    content = str(data.get('content') or '')
    if not content.strip():
        return JSONResponse(
            status_code=400,
            content={
                'error': True,
                'error_code': 'INVALID_CONFIG',
                'message': 'config.yaml 内容不能为空',
            },
        )

    try:
        payload = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return JSONResponse(
            status_code=400,
            content={
                'error': True,
                'error_code': 'INVALID_CONFIG',
                'message': f'YAML 解析失败: {e}',
            },
        )
    if not isinstance(payload, dict) or not isinstance(payload.get('config'), dict):
        return JSONResponse(
            status_code=400,
            content={
                'error': True,
                'error_code': 'INVALID_CONFIG',
                'message': 'config.yaml 必须包含 config 映射',
            },
        )

    try:
        await run_in_threadpool(write_raw_config_content, content)
    except OSError as e:
        return JSONResponse(
            status_code=500,
            content={
                'error': True,
                'error_code': 'CONFIG_WRITE_ERROR',
                'message': f'写入配置文件失败: {e}',
            },
        )

    cfg = payload['config']
    url = str(cfg.get('OPENI_API_URL') or '').strip()
    token = str(cfg.get('OPENI_API_TOKEN') or '')
    model = str(cfg.get('OPENI_API_MODEL') or '').strip()

    s.DEFAULT_API_URL = url
    s.DEFAULT_API_TOKEN = token
    s.DEFAULT_API_MODEL = model
    os.environ['OPENI_API_URL'] = url
    os.environ['OPENI_API_TOKEN'] = token
    os.environ['OPENI_API_MODEL'] = model

    if url and model:
        await run_in_threadpool(litellm_manager.sync_config, url, token, model)

    return {'ok': True, 'message': 'config.yaml 已保存并应用'}