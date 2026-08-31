"""Notebook (.ipynb) file management routes (方案三：FastAPI 版).

与 Flask 版保持完全相同的 URL 与响应格式。版本检查通过
:func:`core.routes.state` 读取 request-time 状态，``WORKSPACE_DIR`` /
``is_safe_path`` 迁移后可被测试 monkeypatch。
"""

import json
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.errors import FileStorageError
from core.routes import json_body, state

router = APIRouter()


def _state(request: Request):
    return state(request)


@router.get('/api/files/list')
async def list_files(request: Request):
    workspace = _state(request).WORKSPACE_DIR
    try:
        files = []
        for f in os.listdir(workspace):
            if f.endswith('.ipynb') and os.path.isfile(os.path.join(workspace, f)):
                files.append(f)
        files.sort()
        return {'success': True, 'files': files}
    except PermissionError as e:
        raise FileStorageError(
            f"Permission denied reading workspace directory: {e}",
            error_code='FILE_PERMISSION_DENIED',
            status_code=403,
        ) from e
    except OSError as e:
        raise FileStorageError(
            f"OS error listing workspace: {e}",
            error_code='FILE_OS_ERROR',
        ) from e


@router.get('/api/files/read')
async def read_file(request: Request):
    s = _state(request)
    workspace = s.WORKSPACE_DIR
    filename = request.query_params.get('filename', '')
    if not filename:
        return JSONResponse({'success': False, 'message': 'Missing filename'}, status_code=400)

    if not filename.endswith('.ipynb') or not s.is_safe_path(filename):
        return JSONResponse({'success': False, 'message': 'Invalid filename'}, status_code=400)

    filepath = os.path.join(workspace, filename)
    if not os.path.exists(filepath):
        return JSONResponse({'success': False, 'message': 'File not found'}, status_code=404)

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = json.load(f)
        return {'success': True, 'content': content}
    except PermissionError as e:
        raise FileStorageError(
            f"Permission denied reading '{filename}': {e}",
            error_code='FILE_PERMISSION_DENIED',
            status_code=403,
        ) from e
    except json.JSONDecodeError as e:
        raise FileStorageError(
            f"Notebook '{filename}' contains invalid JSON at line {e.lineno}: {e.msg}",
            error_code='FILE_INVALID_JSON',
            status_code=422,
        ) from e
    except OSError as e:
        raise FileStorageError(
            f"Failed to read '{filename}': {e}",
            error_code='FILE_OS_ERROR',
        ) from e


@router.post('/api/files/save')
async def save_file(request: Request):
    s = _state(request)
    workspace = s.WORKSPACE_DIR
    data = await json_body(request)
    filename = data.get('filename', '')
    content = data.get('content')

    if not filename or content is None:
        return JSONResponse(
            {'success': False, 'message': 'Missing filename or content'},
            status_code=400,
        )

    if not filename.endswith('.ipynb') or not s.is_safe_path(filename):
        return JSONResponse({'success': False, 'message': 'Invalid filename'}, status_code=400)

    filepath = os.path.join(workspace, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
        return {'success': True, 'message': 'Saved successfully'}
    except PermissionError as e:
        raise FileStorageError(
            f"Permission denied writing '{filename}': {e}",
            error_code='FILE_PERMISSION_DENIED',
            status_code=403,
        ) from e
    except (TypeError, ValueError) as e:
        raise FileStorageError(
            f"Notebook content for '{filename}' is not JSON-serializable: {e}",
            error_code='FILE_SERIALIZE_ERROR',
            status_code=422,
        ) from e
    except OSError as e:
        raise FileStorageError(
            f"Failed to write '{filename}': {e}",
            error_code='FILE_OS_ERROR',
        ) from e


@router.post('/api/files/create')
async def create_file(request: Request):
    workspace = _state(request).WORKSPACE_DIR
    base_name = 'Untitled'
    ext = '.ipynb'
    filename = f"{base_name}{ext}"
    counter = 1
    while os.path.exists(os.path.join(workspace, filename)):
        filename = f"{base_name}{counter}{ext}"
        counter += 1

    filepath = os.path.join(workspace, filename)

    try:
        from core.gpu import get_real_gpu_state
        _gpu = get_real_gpu_state()
        _display = f"Python 3 ({_gpu['name']})" if _gpu.get('gpu_available') and _gpu.get('name') else "Python 3"
    except Exception:
        _display = "Python 3"
    default_notebook = {
        "cells": [],
        "metadata": {
            "kernelspec": {
                "display_name": _display,
                "language": "python",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 2,
    }

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(default_notebook, f, indent=2, ensure_ascii=False)
        return {'success': True, 'filename': filename}
    except PermissionError as e:
        raise FileStorageError(
            f"Permission denied creating notebook '{filename}': {e}",
            error_code='FILE_PERMISSION_DENIED',
            status_code=403,
        ) from e
    except OSError as e:
        raise FileStorageError(
            f"Failed to create notebook '{filename}': {e}",
            error_code='FILE_OS_ERROR',
        ) from e


@router.post('/api/files/rename')
async def rename_file(request: Request):
    s = _state(request)
    workspace = s.WORKSPACE_DIR
    data = await json_body(request)
    old_name = data.get('old_name', '')
    new_name = data.get('new_name', '')

    if not old_name or not new_name:
        return JSONResponse({'success': False, 'message': 'Missing filenames'}, status_code=400)

    if not old_name.endswith('.ipynb') or not new_name.endswith('.ipynb'):
        return JSONResponse({'success': False, 'message': 'Invalid filename format'}, status_code=400)

    if not s.is_safe_path(old_name) or not s.is_safe_path(new_name):
        return JSONResponse({'success': False, 'message': 'Path traversal detected'}, status_code=400)

    old_path = os.path.join(workspace, old_name)
    new_path = os.path.join(workspace, new_name)

    if not os.path.exists(old_path):
        return JSONResponse({'success': False, 'message': 'Source file not found'}, status_code=404)

    if os.path.exists(new_path):
        return JSONResponse({'success': False, 'message': 'Target file already exists'}, status_code=400)

    try:
        os.rename(old_path, new_path)
        return {'success': True, 'message': 'Renamed successfully'}
    except PermissionError as e:
        raise FileStorageError(
            f"Permission denied renaming '{old_name}': {e}",
            error_code='FILE_PERMISSION_DENIED',
            status_code=403,
        ) from e
    except OSError as e:
        raise FileStorageError(
            f"Failed to rename '{old_name}' to '{new_name}': {e}",
            error_code='FILE_OS_ERROR',
        ) from e


@router.post('/api/files/delete')
async def delete_file_api(request: Request):
    s = _state(request)
    workspace = s.WORKSPACE_DIR
    data = await json_body(request)
    filename = data.get('filename', '')

    if not filename:
        return JSONResponse({'success': False, 'message': 'Missing filename'}, status_code=400)

    if not filename.endswith('.ipynb') or not s.is_safe_path(filename):
        return JSONResponse({'success': False, 'message': 'Invalid filename'}, status_code=400)

    filepath = os.path.join(workspace, filename)
    if not os.path.exists(filepath):
        return JSONResponse({'success': False, 'message': 'File not found'}, status_code=404)

    try:
        os.remove(filepath)
        return {'success': True, 'message': 'Deleted successfully'}
    except PermissionError as e:
        raise FileStorageError(
            f"Permission denied deleting '{filename}': {e}",
            error_code='FILE_PERMISSION_DENIED',
            status_code=403,
        ) from e
    except OSError as e:
        raise FileStorageError(
            f"Failed to delete '{filename}': {e}",
            error_code='FILE_OS_ERROR',
        ) from e