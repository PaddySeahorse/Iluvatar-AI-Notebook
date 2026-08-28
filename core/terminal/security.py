import os
import shutil
import re

SHELL_PROFILES = {
    "bash": ["/bin/bash", "--login"],
    "sh": ["/bin/sh"],
}

MAX_TITLE_LEN = 64
MAX_COLS = 500
MAX_ROWS = 200
MIN_COLS = 10
MIN_ROWS = 5
MAX_INPUT_LEN = 65536

def get_default_profile() -> str:
    cfg = os.environ.get("TERMINAL_DEFAULT_PROFILE", "").strip()
    if cfg and cfg in SHELL_PROFILES:
        cmd = SHELL_PROFILES[cfg][0]
        if os.path.exists(cmd) and os.access(cmd, os.X_OK):
            return cfg
    for name in ("bash", "sh"):
        p = SHELL_PROFILES[name][0]
        if os.path.exists(p) and os.access(p, os.X_OK):
            return name
    return "sh"

def resolve_shell(profile: str):
    if profile not in SHELL_PROFILES:
        return None
    cmd = SHELL_PROFILES[profile]
    exe = cmd[0]
    if not os.path.exists(exe) or not os.access(exe, os.X_OK):
        found = shutil.which(os.path.basename(exe))
        if found and os.access(found, os.X_OK):
            return [found] + cmd[1:]
        return None
    return cmd

def resolve_cwd(workspace_dir: str, cwd: str | None) -> str:
    if not cwd or cwd.strip() == "" or cwd.strip() == ".":
        return os.path.realpath(workspace_dir)
    cwd = cwd.strip()
    if os.path.isabs(cwd):
        target = os.path.realpath(cwd)
    else:
        target = os.path.realpath(os.path.join(workspace_dir, cwd))
    if not os.path.exists(target) or not os.path.isdir(target):
        raise ValueError(f"cwd does not exist or not a directory: {cwd}")
    return target

def validate_title(title: str) -> str:
    if not isinstance(title, str):
        raise ValueError("title must be string")
    title = title.strip()
    if not title:
        raise ValueError("title must not be empty")
    if len(title) > MAX_TITLE_LEN:
        title = title[:MAX_TITLE_LEN]
    title = re.sub(r"[\x00-\x1f\x7f]", "", title)
    if not title:
        raise ValueError("title must not be empty")
    return title

def validate_size(cols, rows):
    try:
        c = int(cols)
        r = int(rows)
    except Exception:
        raise ValueError("cols/rows must be integers")
    if not (MIN_COLS <= c <= MAX_COLS):
        raise ValueError(f"cols out of range [{MIN_COLS},{MAX_COLS}]")
    if not (MIN_ROWS <= r <= MAX_ROWS):
        raise ValueError(f"rows out of range [{MIN_ROWS},{MAX_ROWS}]")
    return c, r
