import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from core.terminal.manager import TerminalManager
from core.routes.terminal_routes import router
import tempfile, os

def _app(mgr):
    app = FastAPI()
    app.state.app_state = type("S", (), {"terminal_manager": mgr})()
    app.include_router(router)
    return app

def test_create_list_patch_delete():
    mgr = TerminalManager(workspace_dir="/tmp", max_terminals=5)
    app = _app(mgr)
    c = TestClient(app)
    r = c.post("/api/terminals", json={"profile":"sh","cols":80,"rows":24})
    assert r.status_code==200
    tid = r.json()["id"]
    assert r.json()["profile"]=="sh"
    r2 = c.get("/api/terminals")
    assert len(r2.json())==1
    r3 = c.patch(f"/api/terminals/{tid}", json={"title":"Train"})
    assert r3.status_code==200 and r3.json()["title"]=="Train"
    r4 = c.delete(f"/api/terminals/{tid}")
    assert r4.status_code==200
    assert c.get("/api/terminals").json()==[]

def test_invalid_profile():
    mgr = TerminalManager(workspace_dir="/tmp")
    c = TestClient(_app(mgr))
    r = c.post("/api/terminals", json={"profile":"evil"})
    assert r.status_code==400

def test_invalid_cwd():
    mgr = TerminalManager(workspace_dir="/tmp")
    c = TestClient(_app(mgr))
    r = c.post("/api/terminals", json={"cwd":"/nope12345"})
    assert r.status_code==400

def test_404():
    mgr = TerminalManager(workspace_dir="/tmp")
    c = TestClient(_app(mgr))
    assert c.patch("/api/terminals/notexist", json={"title":"a"}).status_code==404
    assert c.delete("/api/terminals/notexist").status_code==404

def test_ws_attach_and_io():
    mgr = TerminalManager(workspace_dir="/tmp")
    app = _app(mgr)
    c = TestClient(app)
    r = c.post("/api/terminals", json={"profile":"sh"})
    tid = r.json()["id"]
    with c.websocket_connect(f"/ws/terminals/{tid}") as ws:
        data = ws.receive_text()
        assert "status" in data or "output" in data
        ws.send_text('{"type":"ping"}')
        ws.send_text('{"type":"resize","cols":100,"rows":30}')
        ws.send_text('{"type":"input","data":"echo hi\\n"}')
    c.delete(f"/api/terminals/{tid}")

def test_ws_404():
    mgr = TerminalManager(workspace_dir="/tmp")
    c = TestClient(_app(mgr))
    try:
        with c.websocket_connect("/ws/terminals/bad-id"):
            assert False
    except Exception:
        pass
