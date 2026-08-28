import asyncio
import logging
import time
from typing import Dict, List, Optional

from .security import SHELL_PROFILES, get_default_profile, resolve_cwd, resolve_shell, validate_title, validate_size
from .session import TerminalSession

logger = logging.getLogger(__name__)

class TerminalManager:
    def __init__(self, workspace_dir: str, max_terminals: int = 10, buffer_limit: int = 64 * 1024):
        self.workspace_dir = workspace_dir
        self.max_terminals = max_terminals
        self.buffer_limit = buffer_limit
        self._sessions: Dict[str, TerminalSession] = {}
        self._lock = asyncio.Lock()
        self._counter = 0
        self._shutting_down = False

    async def create_session(self, profile: str | None = None, cwd: str | None = None, cols: int = 80, rows: int = 24) -> TerminalSession:
        async with self._lock:
            if self._shutting_down:
                raise RuntimeError("manager shutting down")
            if len(self._sessions) >= self.max_terminals:
                raise ValueError(f"max terminals reached ({self.max_terminals})")
            profile = profile or get_default_profile()
            if profile not in SHELL_PROFILES:
                raise ValueError(f"invalid profile: {profile}")
            shell_cmd = resolve_shell(profile)
            if shell_cmd is None:
                raise ValueError(f"shell not available: {profile}")
            try:
                cols, rows = validate_size(cols, rows)
            except ValueError:
                cols, rows = 80, 24
            cwd_resolved = resolve_cwd(self.workspace_dir, cwd)
            self._counter += 1
            title = f"{profile} {self._counter}"
            sess = TerminalSession(profile=profile, shell_cmd=shell_cmd, cwd=cwd_resolved, cols=cols, rows=rows, title=title, buffer_limit=self.buffer_limit)
            await sess.start()
            self._sessions[sess.id] = sess
            logger.info("terminal created %s pid=%s", sess.id, sess.pid)
            return sess

    def get_session(self, tid: str) -> Optional[TerminalSession]:
        return self._sessions.get(tid)

    def list_sessions(self) -> List[TerminalSession]:
        return list(self._sessions.values())

    async def rename_session(self, tid: str, title: str) -> TerminalSession:
        sess = self._sessions.get(tid)
        if not sess:
            raise KeyError(tid)
        title = validate_title(title)
        sess.title = title
        sess.last_activity_at = time.time()
        return sess

    async def close_session(self, tid: str):
        async with self._lock:
            sess = self._sessions.pop(tid, None)
        if sess is None:
            raise KeyError(tid)
        await sess.close()
        logger.info("terminal closed %s", tid)

    async def shutdown_all(self):
        self._shutting_down = True
        async with self._lock:
            sessions = list(self._sessions.values())
            self._sessions.clear()
        for s in sessions:
            try:
                await s.close()
            except Exception as e:
                logger.warning("shutdown session %s failed: %s", s.id, e)
        self._shutting_down = False
        logger.info("terminal manager shutdown done")

    async def reap_idle_sessions(self, idle_seconds: int = 3600):
        now = time.time()
        to_close = []
        for tid, s in list(self._sessions.items()):
            if s._ws is not None:
                continue
            if s.status == "exited":
                continue
            if now - s.last_activity_at > idle_seconds:
                to_close.append(tid)
        for tid in to_close:
            try:
                await self.close_session(tid)
            except Exception:
                pass
