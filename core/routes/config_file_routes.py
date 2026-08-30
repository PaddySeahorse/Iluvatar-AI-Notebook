"""Raw LiteLLM proxy config read/write routes backing the settings "高级模式".

Advanced mode exposes ``~/.Iluvatar-AI-Notebook/litellm_config.yaml`` — the
single source of truth for LLM routing — as raw text in the settings panel.
``GET`` returns the file verbatim (or a preview generated from the current
environment triple when the file does not exist yet). ``POST`` validates the
payload parses as YAML with a mapping at the top level, then hands off to
``litellm_manager.apply_config_with_rollback``: the content is written
verbatim (mode ``0600``), the local proxy is restarted, and the proxy health
endpoint decides success; failures roll the file back and surface the proxy
log tail to the user.
"""

import os

import yaml
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from core.litellm_manager import (
    build_litellm_config,
    get_litellm_config_path,
    is_manually_managed,
    litellm_manager,
    read_first_route,
)
from core.routes import json_body, state

router = APIRouter()


@router.get('/api/config_file')
async def get_config_file(request: Request):
    path = get_litellm_config_path()
    s = state(request)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            content = f.read()
        exists = True
    except OSError:
        content = ''
        exists = bool(content)
    preview = False
    if not content:
        preview = True
        content = yaml.safe_dump(
            build_litellm_config(s.DEFAULT_API_URL, s.DEFAULT_API_TOKEN, s.DEFAULT_API_MODEL),
            allow_unicode=True,
            default_flow_style=False,
            sort_keys=False,
        )
    return {
        'path': path,
        'exists': exists,
        'content': content,
        'preview': preview,
        'managed_manually': is_manually_managed(),
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
                'message': 'litellm_config.yaml 内容不能为空',
            },
        )

    try:
        payload = yaml.safe_load(content)
    except yaml.YAMLError as e:
        return JSONResponse(
            status_code=400,
            content={
                'error': True,
                'error_code': 'INVALID_LITELLM_CONFIG',
                'message': f'YAML 解析失败: {e}',
            },
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            status_code=400,
            content={
                'error': True,
                'error_code': 'INVALID_LITELLM_CONFIG',
                'message': 'litellm_config.yaml 顶层必须是映射',
            },
        )

    ok, detail = await run_in_threadpool(
        litellm_manager.apply_config_with_rollback, content
    )
    if not ok:
        return JSONResponse(
            status_code=502,
            content={
                'error': True,
                'error_code': 'LITELLM_RESTART_FAILED',
                'message': (
                    'LiteLLM 代理重启失败，已回滚到原配置。代理日志摘要:\n'
                    + (detail or '（无日志输出）')
                ),
            },
        )

    api_base, model_name = read_first_route()
    if api_base:
        s.DEFAULT_API_URL = api_base
        os.environ['OPENI_API_URL'] = api_base
    if model_name:
        s.DEFAULT_API_MODEL = model_name
        os.environ['OPENI_API_MODEL'] = model_name

    return {'ok': True, 'message': 'LiteLLM 配置已保存，代理已重启生效'}
