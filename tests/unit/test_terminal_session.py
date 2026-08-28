import asyncio
import pytest
from core.terminal.session import TerminalSession
from core.terminal.security import SHELL_PROFILES

@pytest.mark.asyncio
async def test_create_and_echo():
    cmd = SHELL_PROFILES["sh"]
    s = TerminalSession(profile="sh", shell_cmd=cmd, cwd="/tmp", cols=80, rows=24)
    await s.start()
    assert s.status=="running"
    assert s.pid is not None
    await asyncio.sleep(0.3)
    await s.write("echo hello\n")
    await asyncio.sleep(0.5)
    buf = s.get_buffer()
    assert "hello" in buf
    await s.close()
    assert s.status=="exited"

@pytest.mark.asyncio
async def test_resize():
    s = TerminalSession(profile="sh", shell_cmd=SHELL_PROFILES["sh"], cwd="/tmp")
    await s.start()
    await s.resize(100, 30)
    assert s.cols==100 and s.rows==30
    await s.close()

@pytest.mark.asyncio
async def test_double_close():
    s = TerminalSession(profile="sh", shell_cmd=SHELL_PROFILES["sh"], cwd="/tmp")
    await s.start()
    await s.close()
    await s.close()
    assert s.status=="exited"

@pytest.mark.asyncio
async def test_exit_detection():
    s = TerminalSession(profile="sh", shell_cmd=SHELL_PROFILES["sh"], cwd="/tmp")
    await s.start()
    await s.write("exit 42\n")
    for _ in range(20):
        await asyncio.sleep(0.2)
        if s.status=="exited":
            break
    assert s.status=="exited"
    assert s.exit_code==42
    await s.close()

@pytest.mark.asyncio
async def test_buffer_limit():
    s = TerminalSession(profile="sh", shell_cmd=SHELL_PROFILES["sh"], cwd="/tmp", buffer_limit=1024)
    await s.start()
    for _ in range(5):
        await s.write("echo " + "x"*500 + "\n")
        await asyncio.sleep(0.2)
    assert len(s.get_buffer()) <= 4096
    await s.close()
