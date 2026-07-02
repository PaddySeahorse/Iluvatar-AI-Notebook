"""Notebook (.ipynb) file management routes."""

import os
import json

from flask import Blueprint, request, jsonify

from core.errors import FileStorageError
from core.routes import state

bp = Blueprint('files', __name__)


def _workspace_dir():
    return state().WORKSPACE_DIR


def _is_safe_path(path):
    return state().is_safe_path(path)


@bp.route('/api/files/list', methods=['GET'])
def list_files():
    workspace = _workspace_dir()
    try:
        files = []
        for f in os.listdir(workspace):
            if f.endswith('.ipynb') and os.path.isfile(os.path.join(workspace, f)):
                files.append(f)
        files.sort()
        return jsonify({
            'success': True,
            'files': files
        })
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


@bp.route('/api/files/read', methods=['GET'])
def read_file():
    workspace = _workspace_dir()
    filename = request.args.get('filename', '')
    if not filename:
        return jsonify({'success': False, 'message': 'Missing filename'}), 400

    if not filename.endswith('.ipynb') or not _is_safe_path(filename):
        return jsonify({'success': False, 'message': 'Invalid filename'}), 400

    filepath = os.path.join(workspace, filename)
    if not os.path.exists(filepath):
        return jsonify({'success': False, 'message': 'File not found'}), 404

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = json.load(f)
        return jsonify({
            'success': True,
            'content': content
        })
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


@bp.route('/api/files/save', methods=['POST'])
def save_file():
    workspace = _workspace_dir()
    data = request.json or {}
    filename = data.get('filename', '')
    content = data.get('content')

    if not filename or content is None:
        return jsonify({'success': False, 'message': 'Missing filename or content'}), 400

    if not filename.endswith('.ipynb') or not _is_safe_path(filename):
        return jsonify({'success': False, 'message': 'Invalid filename'}), 400

    filepath = os.path.join(workspace, filename)
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(content, f, indent=2, ensure_ascii=False)
        return jsonify({
            'success': True,
            'message': 'Saved successfully'
        })
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


@bp.route('/api/files/create', methods=['POST'])
def create_file():
    workspace = _workspace_dir()
    base_name = 'Untitled'
    ext = '.ipynb'
    filename = f"{base_name}{ext}"
    counter = 1
    while os.path.exists(os.path.join(workspace, filename)):
        filename = f"{base_name}{counter}{ext}"
        counter += 1

    filepath = os.path.join(workspace, filename)

    default_notebook = {
        "cells": [],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3 (天数智芯 BI-150)",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "name": "python"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 2
    }

    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(default_notebook, f, indent=2, ensure_ascii=False)
        return jsonify({
            'success': True,
            'filename': filename
        })
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


@bp.route('/api/files/rename', methods=['POST'])
def rename_file():
    workspace = _workspace_dir()
    data = request.json or {}
    old_name = data.get('old_name', '')
    new_name = data.get('new_name', '')

    if not old_name or not new_name:
        return jsonify({'success': False, 'message': 'Missing filenames'}), 400

    if not old_name.endswith('.ipynb') or not new_name.endswith('.ipynb'):
        return jsonify({'success': False, 'message': 'Invalid filename format'}), 400

    if not _is_safe_path(old_name) or not _is_safe_path(new_name):
        return jsonify({'success': False, 'message': 'Path traversal detected'}), 400

    old_path = os.path.join(workspace, old_name)
    new_path = os.path.join(workspace, new_name)

    if not os.path.exists(old_path):
        return jsonify({'success': False, 'message': 'Source file not found'}), 404

    if os.path.exists(new_path):
        return jsonify({'success': False, 'message': 'Target file already exists'}), 400

    try:
        os.rename(old_path, new_path)
        return jsonify({
            'success': True,
            'message': 'Renamed successfully'
        })
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


@bp.route('/api/files/delete', methods=['POST'])
def delete_file_api():
    workspace = _workspace_dir()
    data = request.json or {}
    filename = data.get('filename', '')

    if not filename:
        return jsonify({'success': False, 'message': 'Missing filename'}), 400

    if not filename.endswith('.ipynb') or not _is_safe_path(filename):
        return jsonify({'success': False, 'message': 'Invalid filename'}), 400

    filepath = os.path.join(workspace, filename)
    if not os.path.exists(filepath):
        return jsonify({'success': False, 'message': 'File not found'}), 404

    try:
        os.remove(filepath)
        return jsonify({
            'success': True,
            'message': 'Deleted successfully'
        })
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
