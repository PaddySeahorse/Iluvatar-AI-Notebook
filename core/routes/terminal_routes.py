import json
import logging
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from core.errors import AppError
from core.routes import state, json_body
from core.terminal.protocol import parse_client_message
from core.terminal.security import validate_title

logger = logging.getLogger(__name__)

router = APIRouter()

def _sess_to_api(s):
    return {
        "id": s.id,
        "title": s.title,
        "profile": s.profile,
        "cwd": s.cwd,
        "status": s.status,
        "cols": s.cols,
        "rows": s.rows,
        "exitCode": s.exit_code,
    }

@router.post("/api/terminals")
async def create_terminal(request: Request):
    mgr = state(request).terminal_manager
    data = await json_body(request)
    profile = data.get("profile")
    cwd = data.get("cwd")
    cols = data.get("cols", 80)
    rows = data.get("rows", 24)
    try:
        cols = int(cols) if cols is not None else 80
        rows = int(rows) if rows is not None else 24
    except Exception:
        return JSONResponse({"error": True, "error_code": "INVALID_PARAMS", "message": "cols/rows must be integers"}, status_code=400)
    if profile is not None and not isinstance(profile, str):
        return JSONResponse({"error": True, "error_code": "INVALID_PROFILE", "message": "invalid profile"}, status_code=400)
    if cwd is not None and not isinstance(cwd, str):
        return JSONResponse({"error": True, "error_code": "INVALID_CWD", "message": "invalid cwd"}, status_code=400)
    try:
        sess = await mgr.create_session(profile=profile, cwd=cwd, cols=cols, rows=rows)
    except ValueError as e:
        msg = str(e)
        if "max terminals" in msg:
            return JSONResponse({"error": True, "error_code": "LIMIT_REACHED", "message": msg}, status_code=429)
        if "invalid profile" in msg.lower() or "shell not available" in msg.lower():
            return JSONResponse({"error": True, "error_code": "INVALID_PROFILE", "message": msg}, status_code=400)
        if "cwd" in msg.lower():
            return JSONResponse({"error": True, "error_code": "INVALID_CWD", "message": msg}, status_code=400)
        return JSONResponse({"error": True, "error_code": "INVALID_PARAMS", "message": msg}, status_code=400)
    except RuntimeError as e:
        return JSONResponse({"error": True, "error_code": "SHUTTING_DOWN", "message": str(e)}, status_code=503)
    return _sess_to_api(sess)

@router.get("/api/terminals")
async def list_terminals(request: Request):
    mgr = state(request).terminal_manager
    return [_sess_to_api(s) for s in mgr.list_sessions()]

@router.patch("/api/terminals/{terminal_id}")
async def patch_terminal(terminal_id: str, request: Request):
    mgr = state(request).terminal_manager
    sess = mgr.get_session(terminal_id)
    if not sess:
        return JSONResponse({"error": True, "error_code": "NOT_FOUND", "message": "terminal not found"}, status_code=404)
    data = await json_body(request)
    if "title" not in data:
        return JSONResponse({"error": True, "error_code": "INVALID_PARAMS", "message": "title required"}, status_code=400)
    try:
        title = validate_title(data["title"])
    except ValueError as e:
        return JSONResponse({"error": True, "error_code": "INVALID_TITLE", "message": str(e)}, status_code=400)
    sess.title = title
    import time
    sess.last_activity_at = time.time()
    return _sess_to_api(sess)

@router.delete("/api/terminals/{terminal_id}")
async def delete_terminal(terminal_id: str, request: Request):
    mgr = state(request).terminal_manager
    try:
        await mgr.close_session(terminal_id)
    except KeyError:
        return JSONResponse({"error": True, "error_code": "NOT_FOUND", "message": "terminal not found"}, status_code=404)
    return {"success": True}

@router.websocket("/ws/terminals/{terminal_id}")
async def ws_terminal(websocket: WebSocket, terminal_id: str):
    mgr = websocket.app.state.app_state.terminal_manager
    sess = mgr.get_session(terminal_id)
    if not sess:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    await sess.attach(websocket)
    try:
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break
            msg = parse_client_message(raw)
            if msg is None:
                continue
            if msg.get("type") == "error":
                try:
                    await websocket.send_text(json.dumps(msg))
                except Exception:
                    break
                continue
            t = msg["type"]
            if t == "input":
                if sess.status not in ("running", "starting"):
                    try:
                        await websocket.send_text(json.dumps({"type": "error", "message": "terminal not running"}))
                    except Exception:
                        pass
                    continue
                try:
                    await sess.write(msg["data"])
                except Exception as e:
                    try:
                        await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
                    except Exception:
                        pass
            elif t == "resize":
                try:
                    await sess.resize(msg["cols"], msg["rows"])
                except Exception as e:
                    try:
                        await websocket.send_text(json.dumps({"type": "error", "message": str(e)}))
                    except Exception:
                        pass
            elif t == "ping":
                try:
                    await websocket.send_text(json.dumps({"type": "pong"}))
                except Exception:
                    break
    finally:
        await sess.detach(websocket)
