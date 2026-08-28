import json

ALLOWED_CLIENT_TYPES = {"input", "resize", "ping"}

def parse_client_message(raw: str | bytes, max_len: int = 65536) -> dict | None:
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except Exception:
            return {"type": "error", "message": "invalid encoding"}
    if len(raw) > max_len:
        return {"type": "error", "message": "message too large"}
    try:
        msg = json.loads(raw)
    except Exception:
        return {"type": "error", "message": "invalid json"}
    if not isinstance(msg, dict):
        return {"type": "error", "message": "message must be object"}
    t = msg.get("type")
    if t not in ALLOWED_CLIENT_TYPES:
        return {"type": "error", "message": f"unknown message type: {t}"}
    if t == "input":
        data = msg.get("data")
        if not isinstance(data, str):
            return {"type": "error", "message": "input data must be string"}
        if len(data) > 65536:
            return {"type": "error", "message": "input too large"}
        return {"type": "input", "data": data}
    if t == "resize":
        try:
            cols = int(msg.get("cols"))
            rows = int(msg.get("rows"))
        except Exception:
            return {"type": "error", "message": "invalid resize params"}
        if not (10 <= cols <= 500 and 5 <= rows <= 200):
            return {"type": "error", "message": "resize out of range"}
        return {"type": "resize", "cols": cols, "rows": rows}
    if t == "ping":
        return {"type": "ping"}
    return {"type": "error", "message": "unknown"}

def server_output(data: str) -> str:
    return json.dumps({"type": "output", "data": data})

def server_status(status: str) -> str:
    return json.dumps({"type": "status", "status": status})

def server_exit(exit_code) -> str:
    return json.dumps({"type": "exit", "exitCode": exit_code})

def server_pong() -> str:
    return json.dumps({"type": "pong"})

def server_error(message: str) -> str:
    return json.dumps({"type": "error", "message": message})
