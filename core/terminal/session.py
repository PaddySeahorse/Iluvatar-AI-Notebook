import asyncio
import collections
import fcntl
import logging
import os
import pty
import signal
import struct
import termios
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

class TerminalSession:
    def __init__(self, profile: str, shell_cmd: list, cwd: str, cols: int = 80, rows: int = 24, title: str | None = None, buffer_limit: int = 64 * 1024):
        self.id = str(uuid.uuid4())
        self.profile = profile
        self.shell_cmd = shell_cmd
        self.cwd = cwd
        self.cols = cols
        self.rows = rows
        self.title = title or f"{profile} 1"
        self.status = "starting"
        self.exit_code: Optional[int] = None
        self.pid: Optional[int] = None
        self.master_fd: Optional[int] = None
        self.created_at = time.time()
        self.last_activity_at = time.time()
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._closing = False
        self._closed = False
        self._buffer = collections.deque()
        self._buffer_size = 0
        self._buffer_limit = buffer_limit
        self._ws = None
        self._lock = asyncio.Lock()

    def to_dict(self):
        return {
            "id": self.id,
            "title": self.title,
            "profile": self.profile,
            "cwd": self.cwd,
            "status": self.status,
            "cols": self.cols,
            "rows": self.rows,
            "exitCode": self.exit_code,
            "pid": self.pid,
        }

    async def start(self):
        master_fd, slave_fd = pty.openpty()
        try:
            winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
        except Exception:
            pass
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"

        def preexec():
            try:
                os.setsid()
            except Exception:
                pass

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self.shell_cmd,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=self.cwd,
                env=env,
                preexec_fn=preexec,
            )
            self.pid = self._proc.pid
            self.master_fd = master_fd
            self.status = "running"
            try:
                os.close(slave_fd)
            except Exception:
                pass
            slave_fd = -1
            self._reader_task = asyncio.create_task(self._read_loop())
        except Exception as e:
            self.status = "error"
            try:
                os.close(master_fd)
            except Exception:
                pass
            try:
                if slave_fd != -1:
                    os.close(slave_fd)
            except Exception:
                pass
            self.master_fd = None
            raise
        return self

    async def _read_loop(self):
        loop = asyncio.get_running_loop()
        buf_empty_count = 0
        while True:
            if self._closing or self._closed:
                break
            if self.master_fd is None:
                break
            try:
                data = await loop.run_in_executor(None, self._blocking_read)
            except Exception:
                break
            if data is None:
                await asyncio.sleep(0.01)
                continue
            if data == b"":
                break
            try:
                text = data.decode("utf-8", errors="replace")
            except Exception:
                text = data.decode("latin1", errors="replace")
            self.last_activity_at = time.time()
            self._append_buffer(text)
            if self._ws is not None:
                try:
                    await self._ws.send_text(f'{{"type":"output","data":{__import__("json").dumps(text)}}}')
                except Exception:
                    pass
        await self._handle_exit()

    def _blocking_read(self):
        if self.master_fd is None:
            return b""
        try:
            return os.read(self.master_fd, 8192)
        except BlockingIOError:
            return None
        except OSError as e:
            import errno
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EINTR):
                return None
            return b""

    def _append_buffer(self, text: str):
        self._buffer.append(text)
        self._buffer_size += len(text)
        while self._buffer_size > self._buffer_limit and len(self._buffer) > 1:
            removed = self._buffer.popleft()
            self._buffer_size -= len(removed)

    def get_buffer(self) -> str:
        return "".join(self._buffer)

    async def _handle_exit(self):
        if self.status == "exited":
            return
        exit_code = None
        if self._proc is not None:
            try:
                exit_code = self._proc.returncode
                if exit_code is None:
                    try:
                        await asyncio.wait_for(self._proc.wait(), timeout=0.5)
                        exit_code = self._proc.returncode
                    except asyncio.TimeoutError:
                        pass
            except Exception:
                pass
        self.exit_code = exit_code if exit_code is not None else 0
        prev = self.status
        if not self._closing:
            self.status = "exited"
        else:
            self.status = "exited"
        if self._ws is not None:
            try:
                await self._ws.send_text(f'{{"type":"exit","exitCode":{__import__("json").dumps(self.exit_code)}}}')
            except Exception:
                pass

    async def write(self, data: str):
        if self.status not in ("running", "starting"):
            return
        if self.master_fd is None:
            return
        if not isinstance(data, str):
            raise ValueError("data must be string")
        self.last_activity_at = time.time()
        loop = asyncio.get_running_loop()
        b = data.encode("utf-8", errors="replace")
        try:
            await loop.run_in_executor(None, lambda: os.write(self.master_fd, b))
        except OSError:
            pass

    async def resize(self, cols: int, rows: int):
        if not (10 <= cols <= 500 and 5 <= rows <= 200):
            raise ValueError("out of range")
        self.cols = cols
        self.rows = rows
        self.last_activity_at = time.time()
        if self.master_fd is not None:
            try:
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
                if self.pid:
                    try:
                        os.killpg(os.getpgid(self.pid), signal.SIGWINCH)
                    except Exception:
                        try:
                            os.kill(self.pid, signal.SIGWINCH)
                        except Exception:
                            pass
            except Exception:
                pass

    async def attach(self, ws):
        async with self._lock:
            if self._ws is not None:
                try:
                    await self._ws.close(code=1000)
                except Exception:
                    pass
            self._ws = ws
            self.last_activity_at = time.time()
            try:
                await ws.send_text(f'{{"type":"status","status":{__import__("json").dumps(self.status)}}}')
            except Exception:
                pass
            if self.exit_code is not None:
                try:
                    await ws.send_text(f'{{"type":"exit","exitCode":{__import__("json").dumps(self.exit_code)}}}')
                except Exception:
                    pass
            buf = self.get_buffer()
            if buf:
                try:
                    await ws.send_text(f'{{"type":"output","data":{__import__("json").dumps(buf)}}}')
                except Exception:
                    pass

    async def detach(self, ws):
        async with self._lock:
            if self._ws is ws:
                self._ws = None

    async def close(self):
        if self._closed:
            return
        if self._closing:
            while self._closing and not self._closed:
                await asyncio.sleep(0.05)
            return
        self._closing = True
        self.status = "closing"
        if self._ws is not None:
            try:
                await self._ws.close(code=1000)
            except Exception:
                pass
            self._ws = None
        if self.pid is not None:
            try:
                pgid = os.getpgid(self.pid)
                try:
                    os.killpg(pgid, signal.SIGHUP)
                except ProcessLookupError:
                    pass
                try:
                    os.killpg(pgid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            except ProcessLookupError:
                try:
                    os.kill(self.pid, signal.SIGTERM)
                except Exception:
                    pass
            except Exception:
                pass
            if self._proc is not None:
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    try:
                        pgid = os.getpgid(self.pid)
                        os.killpg(pgid, signal.SIGKILL)
                    except Exception:
                        try:
                            os.kill(self.pid, signal.SIGKILL)
                        except Exception:
                            pass
                    try:
                        await asyncio.wait_for(self._proc.wait(), timeout=2.0)
                    except Exception:
                        pass
                except Exception:
                    pass
        if self._reader_task is not None:
            try:
                self._reader_task.cancel()
                await self._reader_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        if self.master_fd is not None:
            try:
                os.close(self.master_fd)
            except Exception:
                pass
            self.master_fd = None
        if self.status != "exited":
            self.status = "exited"
        if self.exit_code is None:
            if self._proc and self._proc.returncode is not None:
                self.exit_code = self._proc.returncode
            else:
                self.exit_code = -1
        self._closed = True
        self._closing = False
