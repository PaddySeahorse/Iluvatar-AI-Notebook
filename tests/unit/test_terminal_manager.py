import asyncio
import pytest
from core.terminal.manager import TerminalManager
import tempfile, os

@pytest.mark.asyncio
async def test_create_and_list():
    mgr = TerminalManager(workspace_dir="/tmp", max_terminals=5)
    s = await mgr.create_session(profile="sh")
    assert s.id in [x.id for x in mgr.list_sessions()]
    assert s.profile=="sh"
    await mgr.shutdown_all()

@pytest.mark.asyncio
async def test_invalid_profile():
    mgr = TerminalManager(workspace_dir="/tmp")
    with pytest.raises(ValueError):
        await mgr.create_session(profile="bad")

@pytest.mark.asyncio
async def test_cwd_validation():
    mgr = TerminalManager(workspace_dir="/tmp")
    with pytest.raises(ValueError):
        await mgr.create_session(cwd="/nonexistent_xyz_123")
    s = await mgr.create_session(cwd=".")
    assert s.cwd == os.path.realpath("/tmp")
    await mgr.shutdown_all()

@pytest.mark.asyncio
async def test_rename():
    mgr = TerminalManager(workspace_dir="/tmp")
    s = await mgr.create_session()
    await mgr.rename_session(s.id, "MyTerm")
    assert mgr.get_session(s.id).title=="MyTerm"
    await mgr.shutdown_all()

@pytest.mark.asyncio
async def test_limit():
    mgr = TerminalManager(workspace_dir="/tmp", max_terminals=1)
    await mgr.create_session()
    with pytest.raises(ValueError, match="max terminals"):
        await mgr.create_session()
    await mgr.shutdown_all()

@pytest.mark.asyncio
async def test_close_isolation():
    mgr = TerminalManager(workspace_dir="/tmp")
    s1 = await mgr.create_session()
    s2 = await mgr.create_session()
    await mgr.close_session(s1.id)
    assert mgr.get_session(s1.id) is None
    assert mgr.get_session(s2.id) is not None
    await mgr.shutdown_all()

@pytest.mark.asyncio
async def test_shutdown_all_closes():
    mgr = TerminalManager(workspace_dir="/tmp")
    s1 = await mgr.create_session()
    s2 = await mgr.create_session()
    await mgr.shutdown_all()
    assert len(mgr.list_sessions())==0

@pytest.mark.asyncio
async def test_repeated_close():
    mgr = TerminalManager(workspace_dir="/tmp")
    s = await mgr.create_session()
    await mgr.close_session(s.id)
    with pytest.raises(KeyError):
        await mgr.close_session(s.id)

@pytest.mark.asyncio
async def test_default_profile():
    mgr = TerminalManager(workspace_dir="/tmp")
    s = await mgr.create_session(profile=None)
    assert s.profile in ("bash","sh")
    await mgr.shutdown_all()
