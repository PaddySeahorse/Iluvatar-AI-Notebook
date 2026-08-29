# AGENTS.md — Iluvatar AI Notebook

## Stack & Entry
- FastAPI ASGI unified entry: `app_fastapi.py` (single uvicorn process serves Notebook `/` + `/api/*` + Chainlit `/agent`). `app.py` is only a thin compat wrapper — always use `python app_fastapi.py` or `uvicorn app_fastapi:app --host 0.0.0.0 --port 5000`.
- Flat layout, no build step: `core/` + `static/` (Vanilla JS, no `package.json`). All static assets vendored under `static/vendor/`.
- `LITELLM_PROXY_URL` defaults to `http://localhost:4000` — transport in `core/llm.py` is **hard-pinned** there; `url` param is upstream config for the proxy's `model_list`, never dialed directly.

## Run & Config
- Install: `pip install -r requirements.txt` then `pip install -e . --no-deps` for `iluvatar_python` provisioner entry point.
- Env seeds on first boot into `~/.Iluvatar-AI-Notebook/config.yaml` (0600): `OPENI_API_URL` / `OPENI_API_TOKEN` / `OPENI_API_MODEL`; later edits via UI or `LITELLM_PROXY_URL`, `USE_OPENAI_SDK`, `ALLOWED_ORIGINS`, `USE_ILUVATAR_PROVISIONER=true`, `LOG_LEVEL`.
- Lifecycle in `app_fastapi.lifespan`: `warm_start` kernel, bootstrap litellm config from env, `ensure_running` proxy, `atexit` cleanup of watchdog/kernel/terminal/proxy. Port via `OPENI_SELF_PORT` (default 5000). Chainlit auto-redirects `/agent` → `/agent/` (307).
- **Startup must be Python**: `python app_fastapi.py` (or `uvicorn app_fastapi:app`) — do not switch to node/npm or other runtimes.
- **Single exposed port**: only `OPENI_SELF_PORT` is user-accessible; do not bind auxiliary services to other ports — frontend must proxy `/api/*` through the same FastAPI process.

## Routes & State
- Shared singleton `core.state.app_state` (kernel_manager, terminal_manager, WORKSPACE_DIR, DEFAULT_API_*). Routes read via `request.app.state.app_state` (`core/routes/__init__.py:state()` + `json_body()` tolerance for empty POST) — never `import app`.
- Registration order matters: `register_static_routes` + `mount_chainlit` first, then `gpu/kernel/ai/lint/file/agent/metrics/terminal`, **`litellm_routes` catch-all `/{subpath:path}` last** or it 404s everything. See `core/routes/__init__.py:91`.

## Tests
- `pytest -m "not iluvatar"` (default, skips GPU hardware). `-m iluvatar` requires `jupyter kernelspec install kernels/iluvatar_python` + IXUCA SDK. Markers: `integration` (real ipykernel, slower), `iluvatar`, `e2e` in `pytest.ini`.
- Single test: `pytest tests/unit/test_kernel_manager.py -k TestFoo` or `pytest tests/unit/test_llm.py::test_name`.
- `tests/conftest.py` redirects `HOME` to tmpdir before `user_config` import — do not read real `~/.Iluvatar-AI-Notebook` in tests.
- Frontend: no runner, invoke directly `node --test tests/js/completion.test.mjs` (similarly `inspect|sse-client|kernel-indicator|output-renderer|agent-stream|terminal-*`). E2E `npx playwright test e2e/p2-streaming.spec.mjs` needs `app_fastapi.py` running.

## Gotchas
- Litellm proxy requires `pip install "litellm[proxy]"`; if missing, `ensure_running` warns and notebook still boots. Config at `~/.Iluvatar-AI-Notebook/litellm_config.yaml`, log `litellm_proxy.log`.
- OpenAI SDK is optional: `USE_OPENAI_SDK=0` forces `requests` fallback, `=1` forces SDK; unset = auto-detect. Both backends return same `{"content","tool_calls"}` shape.
- `pyproject.toml` registers `iluvatar-provisioner`; without `pip install -e .` the GPU path needs `register_provisioner()` programmatically.
- No `docs/` — removed in e395752, history in `CHANGELOG.md`. Do not recreate.
