"""Shared utility helpers."""

import os


def is_safe_path(workspace_dir: str, path: str) -> bool:
    """Return True if *path* stays within *workspace_dir* after resolving symlinks.

    Uses :func:`os.path.realpath` (ISSUE-006) so symlink chains that escape the
    workspace are rejected.
    """
    target_path = os.path.realpath(os.path.join(workspace_dir, path))
    return os.path.commonpath([workspace_dir, target_path]) == workspace_dir
