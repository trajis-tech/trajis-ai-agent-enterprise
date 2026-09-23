from __future__ import annotations

import json
import asyncio
import threading
from urllib.parse import urlsplit
import os
import sys
import traceback
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "app") not in sys.path:
    sys.path.insert(0, str(ROOT / "app"))

from backend.agent_app import dispatch_tool, queue_publish_approval, queue_bundle_approval, file_ctx
from backend.hitl import reject_client_overrides
from backend.audit import AuditLog
from backend.deps import AppDeps
from backend.history import model_view, to_agent_prompt
from backend.jail import FilesystemJail, JailError, JailPolicy
from backend.locks import ProjectLock, ProjectLockBusy
from backend.n8n_client import N8nClient
from backend.n8n_lifecycle import cleanup_stale_pid, load_api_key, start_n8n, stop_n8n
from backend.n8n_proxy import N8nProxy
from backend.paths import (
    custom_api_path,
    filesystem_root,
    policy_path,
    product_root,
    projects_root,
    runtime_root,
    system_root,
)
from backend.policy import load_policy
from backend.projects import create_draft, list_projects, rename_title
from backend.snapshot import SnapshotStore, SnapshotConflict
from backend.atomic import atomic_write_text
from backend.workspace_files import visible_files, import_file, export_project, download_file
from backend.n8n_lifecycle import save_api_key
from backend.state import StateDB
from backend.tools_n8n import PublishConflict

from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket


FRONTEND = product_root() / "app" / "frontend"
RUNTIME = runtime_root()
POLICY = load_policy(policy_path())
DB = StateDB(RUNTIME / "state.db")
AUDIT = AuditLog(RUNTIME / "audit.jsonl")
SNAPSHOTS = SnapshotStore(RUNTIME / "snapshots")
LOCKS = ProjectLock(RUNTIME)
N8N_STATUS = {"ready": False, "reason": "not started", "url": f"http://{POLICY.n8n_host}:{POLICY.n8n_port}"}
AUTOMATION = None
BROKER_SERVER = None
N8N_CONTROL_LOCK = threading.Lock()
N8N_PROXY = N8nProxy(N8N_STATUS["url"])


def _jail(project_root: Path) -> FilesystemJail:
    return FilesystemJail(
        fs_root=filesystem_root(),
        system_root=system_root(),
        project_root=project_root,
        policy=JailPolicy(
            write_extensions=POLICY.write_extensions,
            forbidden_names=POLICY.forbidden_names,
            forbidden_suffixes=POLICY.forbidden_suffixes,
        ),
    )


def _load_custom_api() -> dict[str, Any]:
    path = custom_api_path()
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_templates", None)
    data.pop("_readme", None)
    return data


def _interpreter() -> Path:
    return system_root() / "python" / "python.exe"


def _make_deps(project: dict[str, str], session_id: str, turn_id: str) -> AppDeps:
    root = Path(project["path"])
    api_key = load_api_key(RUNTIME / "secrets")
    client = None
    if N8N_STATUS["ready"] and api_key:
        client = N8nClient(N8N_STATUS["url"], api_key)
    elif N8N_STATUS["ready"]:
        client = N8nClient(N8N_STATUS["url"], None)
    return AppDeps(
        fs_root=filesystem_root(),
        system_root=system_root(),
        project_root=root,
        jail=_jail(root),
        policy=POLICY,
        audit=AUDIT,
        snapshots=SNAPSHOTS,
        db=DB,
        project_id=project["id"],
        session_id=session_id,
        turn_id=turn_id,
        n8n=client,
        interpreter=_interpreter(),
        pythonhome=system_root() / "python",
        staging_root=RUNTIME / "run_staging",
        chat_mode=DB.mode_state(session_id)["mode"],
        mode_epoch=DB.mode_state(session_id)["epoch"],
        search_config=RUNTIME / "search.json",
        automation=AUTOMATION,
    )


class FrameAncestors(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        session_id = request.headers.get("x-agent-session", "")
        session = DB.session(session_id) if session_id else None
        project = None
        if session:
            project = next((p for p in list_projects(projects_root()) if p["id"] == session["project_id"]), None)
        request.state.workspace = {"project": project, "session": session_id if project else None}
        if request.url.path.startswith("/api/") and request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != str(request.base_url).rstrip("/")):
                return JSONResponse({"error": "拒絕跨來源操作"}, status_code=403)
        if session and request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path in {"/api/undo", "/api/files/import", "/api/gateway", "/api/n8n", "/api/search/settings", "/api/automation"}:
            if DB.mode_state(session_id)["mode"] != "general":
                return JSONResponse({"error": "請切換一般模式後再修改或執行"}, status_code=403)
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response


async def index(request: Request) -> FileResponse:
    return FileResponse(FRONTEND / "index.html")


async def api_status(request: Request) -> JSONResponse:
    from backend.knowledge import knowledge_path, knowledge_status
    from backend.search_mcp import read_config
    cfg = _load_custom_api()
    if N8N_STATUS["ready"] or str(N8N_STATUS.get("reason", "")).startswith("n8n startup timeout"):
        healthy = await asyncio.to_thread(N8nClient(N8N_STATUS["url"], None).health)
        if healthy:
            N8N_STATUS.update(ready=True, reason=None)
        elif N8N_STATUS["ready"]:
            N8N_STATUS.update(ready=False, reason="n8n 連線中斷，請重試啟動")
    search = read_config(RUNTIME / "search.json")
    return JSONResponse(
        {
            "automation": AUTOMATION.health() if AUTOMATION else {"installed": False, "running": False, "reason": "橋接服務未啟動"},
            "search": {"enabled": bool(search.get("enabled")), "configured": bool(search.get("url"))},
            "knowledge": knowledge_status(knowledge_path(system_root())),
            "n8n": {**N8N_STATUS, "hasKey": bool(load_api_key(RUNTIME / "secrets"))},
            "project": request.state.workspace["project"],
            "session": request.state.workspace["session"],
            "historyVersion": (DB.session(request.state.workspace["session"]) or {}).get("updated_at", ""),
            "gateway": {
                "displayName": cfg.get("displayName") or "",
                "hasKey": bool(cfg.get("apiKeyEncrypted")),
                "enabled": bool(cfg.get("enabled")),
                "requestUrl": cfg.get("requestUrl") or "",
            },
            "python": {
                "product": str(product_root() / "portable_python" / "python.exe"),
                "agent": str(_interpreter()),
            },
        }
    )


async def api_projects(request: Request) -> JSONResponse:
    return JSONResponse({"projects": list_projects(projects_root())})


async def api_create_project(request: Request) -> JSONResponse:
    body = await request.json()
    draft = create_draft(projects_root())
    request.state.workspace["project"] = draft
    session_id = str(uuid4())
    request.state.workspace["session"] = session_id
    DB.ensure_session(session_id, draft["id"])
    topic = (body or {}).get("topic") or ""
    if topic:
        try:
            renamed = rename_title(projects_root(), draft["id"], topic[:80])
            request.state.workspace["project"] = renamed
            draft = renamed
        except Exception:
            pass
    return JSONResponse({**draft, "session_id": session_id})


async def api_open_project(request: Request) -> JSONResponse:
    body = await request.json()
    folder = body.get("folder")
    matches = [p for p in list_projects(projects_root()) if p["folder"] == folder or p["id"] == folder]
    if not matches:
        return JSONResponse({"error": "not found"}, status_code=404)
    request.state.workspace["project"] = matches[0]
    session_id = DB.latest_session(matches[0]["id"]) or str(uuid4())
    request.state.workspace["session"] = session_id
    DB.ensure_session(session_id, matches[0]["id"])
    return JSONResponse({**matches[0], "session_id": session_id})


async def api_session(request: Request) -> JSONResponse:
    session_id = request.state.workspace["session"]
    if not session_id:
        return JSONResponse({"messages": [], "pending": []})
    pending = []
    for record in DB.pending_for_session(session_id):
        if _pending_expired(record):
            DB.resolve_pending(record["approval_id"], "expired")
            continue
        pending.append({"approval_id": record["approval_id"], "path": record["args"].get("path", ""),
                        "tool": record["tool_name"], "notice": record.get("display", "")})
    messages = DB.messages(session_id)
    undo_turn_id = None
    project = request.state.workspace["project"]
    for item in reversed(messages):
        turn_id = item.get("turn_id")
        if not turn_id:
            continue
        manifest = SNAPSHOTS.root / project["id"] / f"turn_{turn_id}" / "manifest.json"
        if manifest.is_file():
            data = json.loads(manifest.read_text(encoding="utf-8"))
            if data.get("files") and not data.get("restored"):
                undo_turn_id = turn_id
            break
    return JSONResponse({"messages": messages, "pending": pending, "undo_turn_id": undo_turn_id,
                         "historyVersion": (DB.session(session_id) or {}).get("updated_at", "")})


async def api_plans(request: Request) -> JSONResponse:
    session_id = request.state.workspace["session"]
    return JSONResponse({"plans": DB.plans(session_id) if session_id else []})


async def api_automation(request: Request) -> JSONResponse:
    project = request.state.workspace["project"]
    if AUTOMATION is None:
        return JSONResponse({"health": {"installed": False, "reason": "本機橋接未啟動；請確認 Port 8771 未被占用"}, "runs": []})
    if request.method == "POST":
        if not project or DB.mode_state(request.state.workspace["session"])["mode"] != "general":
            return JSONResponse({"error": "請在一般模式與目前專案中操作"}, status_code=403)
        body = await request.json()
        try:
            if body.get("action") == "recover":
                result = AUTOMATION.recover()
                AUDIT.write({"tool": "automation_recover", "project_id": project["id"], "result": "recovered"})
                return JSONResponse(result)
            return JSONResponse(AUTOMATION.cancel(body.get("run_id", ""), project["id"]))
        except (ValueError, RuntimeError) as exc: return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"health": AUTOMATION.health(), "runs": AUTOMATION.list_runs(project["id"]) if project else []})


async def api_search_settings(request: Request) -> JSONResponse:
    from backend.search_mcp import read_config, validate_config
    path = RUNTIME / "search.json"
    if request.method == "GET":
        return JSONResponse(read_config(path))
    try:
        config = validate_config(await request.json())
        if config["enabled"] and not config["url"]:
            raise ValueError("啟用搜尋前請設定 SearXNG 上游")
        atomic_write_text(path, json.dumps(config, ensure_ascii=False))
        return JSONResponse(config)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def api_search_test(request: Request) -> JSONResponse:
    from backend.search_client import search_via_mcp
    try:
        result = await asyncio.to_thread(search_via_mcp, RUNTIME / "search.json", {"query": "SearXNG documentation", "limit": 1})
        return JSONResponse({"ok": True, "result": json.loads(result)})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)


async def api_mode(request: Request) -> JSONResponse:
    session_id = request.state.workspace["session"]
    project = request.state.workspace["project"]
    if not session_id or not project:
        return JSONResponse({"error": "請先開啟專案"}, status_code=400)
    if request.method == "GET":
        return JSONResponse(DB.mode_state(session_id))
    body = await request.json()
    acquired = False
    try:
        LOCKS.acquire(project["id"], "mode-change", timeout=0)
        acquired = True
        result = DB.set_mode(session_id, body.get("mode"))
        return JSONResponse(result)
    except ProjectLockBusy:
        return JSONResponse({"error": "請先中止執行，待工具停止後再切換模式"}, status_code=409)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        if acquired:
            LOCKS.release(project["id"])


async def api_files(request: Request) -> JSONResponse:
    project = request.state.workspace["project"]
    if not project:
        return JSONResponse({"error": "no project"}, status_code=400)
    root = Path(project["path"])
    items = [{"path": rel, "type": "file", "size": path.stat().st_size}
             for rel, path in visible_files(root, _jail(root))]
    return JSONResponse({"files": items})


async def api_read_file(request: Request) -> JSONResponse:
    project = request.state.workspace["project"]
    if not project:
        return JSONResponse({"error": "no project"}, status_code=400)
    rel = request.query_params.get("path") or ""
    jail = _jail(Path(project["path"]))
    try:
        target = jail.resolve(rel, "read")
    except JailError as exc:
        return JSONResponse({"error": exc.message, "code": exc.code}, status_code=403)
    if not target.is_file():
        return JSONResponse({"error": "not a file"}, status_code=404)
    with target.open("rb") as handle:
        raw = handle.read(200001)
    try:
        text = raw[:200000].decode("utf-8")
        binary = chr(0) in text
    except UnicodeDecodeError:
        text, binary = "", True
    return JSONResponse({"path": rel, "content": "" if binary else text,
                         "binary": binary, "truncated": len(raw) > 200000,
                         "size": target.stat().st_size})


async def api_undo(request: Request) -> JSONResponse:
    project = request.state.workspace["project"]
    if not project:
        return JSONResponse({"error": "no project"}, status_code=400)
    body = await request.json()
    turn_id = body.get("turn_id")
    jail = _jail(Path(project["path"]))
    acquired = False
    try:
        LOCKS.acquire(project["id"], "undo-" + str(uuid4()), timeout=0)
        acquired = True
        restored = SNAPSHOTS.restore_turn(project["id"], turn_id, jail)
        AUDIT.write({"tool": "undo", "project_id": project["id"], "turn_id": turn_id,
                     "targets": restored, "result": "ok"})
        if restored:
            DB.append_message(request.state.workspace["session"], "system", {"content": "已復原本回合檔案變更。"}, turn_id)
        return JSONResponse({"restored": restored})
    except (ProjectLockBusy, SnapshotConflict) as exc:
        return JSONResponse({"error": str(exc), "code": "CONFLICT"}, status_code=409)
    except (ValueError, JailError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        if acquired:
            LOCKS.release(project["id"])


async def api_gateway(request: Request) -> JSONResponse:
    cfg = _load_custom_api()
    if request.method == "GET":
        public = {k: v for k, v in cfg.items() if k not in {"apiKeyEncrypted", "headers"}}
        public["hasKey"] = bool(cfg.get("apiKeyEncrypted"))
        public["enabled"] = bool(cfg.get("enabled"))
        return JSONResponse(public)
    body = await request.json()
    url = str(body.get("requestUrl", cfg.get("requestUrl", ""))).strip()
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return JSONResponse({"error": "請輸入完整 HTTP(S) 閘道網址，不含金鑰、查詢參數或帳密"}, status_code=400)
    model = str(body.get("model", (cfg.get("defaults") or {}).get("model", ""))).strip()
    if not model:
        return JSONResponse({"error": "請填寫模型名稱"}, status_code=400)
    cfg["requestUrl"] = url
    cfg["displayName"] = str(body.get("displayName", cfg.get("displayName", "公司閘道")))[:100]
    cfg.setdefault("defaults", {})["model"] = model
    cfg["enabled"] = True
    if body.get("apiKeyEncrypted"):
        cfg["apiKeyEncrypted"] = str(body["apiKeyEncrypted"]).strip()
    atomic_write_text(custom_api_path(), json.dumps(cfg, ensure_ascii=False, indent=2))
    return JSONResponse({"ok": True})


async def api_n8n_control(request: Request) -> JSONResponse:
    body = await request.json()
    action = body.get("action")
    if action == "key":
        key = str(body.get("key", "")).strip()
        if not key:
            return JSONResponse({"error": "請輸入 n8n API Key"}, status_code=400)
        save_api_key(RUNTIME / "secrets", key)
        return JSONResponse({"ok": True})
    if action not in {"stop", "restart"}:
        return JSONResponse({"error": "不支援的操作"}, status_code=400)
    if not N8N_CONTROL_LOCK.acquire(blocking=False):
        return JSONResponse({"error": "n8n 正在啟動或停止，請稍候"}, status_code=409)
    N8N_STATUS.update(ready=False, reason="stopping" if action == "stop" else "starting")
    def control():
        try:
            stop_n8n(RUNTIME / "n8n.pid")
            if action == "restart":
                _boot_n8n()
            else:
                N8N_STATUS.update(ready=False, reason="stopped")
        except Exception as exc:
            N8N_STATUS.update(ready=False, reason=str(exc))
        finally:
            N8N_CONTROL_LOCK.release()
    threading.Thread(target=control, name="n8n-control", daemon=True).start()
    return JSONResponse({"n8n": N8N_STATUS}, status_code=202)


async def api_chat(request: Request) -> StreamingResponse:
    body = await request.json()
    message = (body or {}).get("message") or ""
    session_id = request.state.workspace["session"] or str(uuid4())
    request.state.workspace["session"] = session_id
    project = request.state.workspace["project"]
    if not project:
        return JSONResponse({"error": "請先新增或開啟專案"}, status_code=400)
    if not isinstance(message, str) or not message.strip() or len(message) > 100000:
        return JSONResponse({"error": "訊息不可為空白，且不得超過 100000 字元"}, status_code=400)
    if DB.has_pending(session_id):
        return JSONResponse({"error": "請先批准或拒絕待處理的發佈"}, status_code=409)
    turn_id = str(uuid4())[:8]
    DB.ensure_session(session_id, project["id"])

    async def events() -> AsyncIterator[bytes]:
        def sse(event: str, data: dict[str, Any]) -> bytes:
            return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode("utf-8")

        yield sse("status", {"state": "running", "turn_id": turn_id})
        try:
            LOCKS.acquire(project["id"], turn_id, timeout=0.2)
        except ProjectLockBusy:
            yield sse("error", {"message": "此專案正在執行另一個變更回合"})
            yield sse("done", {"turn_id": turn_id})
            return
        deps = None
        task = None
        try:
            deps = _make_deps(project, session_id, turn_id)
            DB.append_message(session_id, "user", {"content": message}, turn_id=turn_id)
            sse_put = []
            deps.progress = lambda name: sse_put.append(("status", {"state": "running", "turn_id": turn_id, "message": "正在執行 " + name}))
            task = asyncio.create_task(_run_agent(deps, message, sse_put))
            while not task.done():
                await asyncio.wait({task}, timeout=1)
                while sse_put:
                    event, data = sse_put.pop(0)
                    yield sse(event, data)
                if not task.done():
                    yield b": keepalive\n\n"
            reply = await task
            while sse_put:
                event, data = sse_put.pop(0)
                yield sse(event, data)
            if reply:
                DB.append_message(session_id, "assistant", {"content": reply}, turn_id=turn_id)
                yield sse("token", {"text": reply})
        except asyncio.CancelledError:
            DB.append_message(session_id, "system", {"content": "回合已中止；已完成的變更保留，可使用復原。"}, turn_id=turn_id)
            raise
        except Exception as exc:
            AUDIT.write({"tool": "agent_run", "result": "error", "error": traceback.format_exc()[-2000:]})
            DB.append_message(session_id, "system", {"content": "執行失敗：" + str(exc)}, turn_id=turn_id)
            yield sse("error", {"message": str(exc)})
        finally:
            import anyio
            with anyio.CancelScope(shield=True):
                if deps:
                    deps.cancel_event.set()
                if task is not None and not task.done():
                    if deps:
                        deps.cancel_event.set()
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
                if deps:
                    await anyio.to_thread.run_sync(deps.wait_for_tools)
                LOCKS.release(project["id"])
        yield sse("done", {"turn_id": turn_id})

    return StreamingResponse(events(), media_type="text/event-stream")


async def _run_agent(deps: AppDeps, message: str, bucket: list) -> str:
    cfg = _load_custom_api()
    import_error = _pydantic_ai_import_error()
    has_key = bool(cfg.get("apiKeyEncrypted"))
    if not has_key:
        note = _heuristic_turn(deps, message, bucket)
        if import_error:
            return (
                f"本機 Agent 核心無法載入：{import_error}\n"
                "這不是前端問題；請先修好產品套件後再設閘道。\n"
                + note
            )
        return note
    if import_error:
        raise RuntimeError(f"pydantic_ai 無法載入：{import_error}")
    from backend.agent_app import build_pydantic_agent, usage_limits
    from backend.provider import load_gateway
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    gw = load_gateway(cfg)
    model_name = gw["model"]
    import httpx
    from pydantic_ai import DeferredToolResults
    from pydantic_ai.messages import ModelMessagesTypeAdapter

    saved = deps.db.agent_history(deps.session_id)
    history = ModelMessagesTypeAdapter.validate_json(saved["history_json"]) if saved else None
    if saved is None:
        # Preserve conversations created before canonical tool history was introduced.
        prior = deps.db.messages(deps.session_id)
        if prior and prior[-1]["role"] == "user" and prior[-1]["payload"].get("content") == message:
            prior = prior[:-1]
        prefix = to_agent_prompt(model_view(prior, deps.policy, False))
        if prefix:
            message = prefix + "\n\n" + message
    results = None
    if saved and json.loads(saved["pending_json"]):
        calls, approvals = {}, {}
        for approval_id in json.loads(saved["pending_json"]):
            record = deps.db.get_pending(approval_id)
            if record is None or record["status"] == "pending":
                raise RuntimeError("請先處理此對話的待批准項目")
            if record["status"] == "approve":
                calls[record["tool_call_id"]] = deps.db.approval_outcome(approval_id)
            else:
                approvals[record["tool_call_id"]] = False
        results = DeferredToolResults(calls=calls, approvals=approvals)
    headers = {str(k): str(v).replace("{{apiKey}}", cfg.get("apiKeyEncrypted", ""))
               for k, v in gw["headers"].items()}
    async with httpx.AsyncClient(timeout=gw["timeout"], verify=gw["verify"], headers=headers) as http_client:
        provider = OpenAIProvider(base_url=_base_url(gw["url"]), api_key=cfg.get("apiKeyEncrypted") or "sk-local", http_client=http_client)
        model = OpenAIChatModel(model_name, provider=provider)
        agent = build_pydantic_agent(model, mode=deps.chat_mode)
        result = await agent.run(message or None, deps=deps, usage_limits=usage_limits(deps),
                                 message_history=history, deferred_tool_results=results)
    output = result.output
    pending = []
    if type(output).__name__ == "DeferredToolRequests":
        calls = getattr(output, "approvals", None) or getattr(output, "calls", None) or []
        for call in calls:
            if call.tool_name not in {"publish_workflow", "publish_automation_bundle"}:
                raise RuntimeError("不支援的延期工具")
            args = call.args_as_dict()
            path = args.get("path") or ""
            queue = queue_bundle_approval if call.tool_name == "publish_automation_bundle" else queue_publish_approval
            approval_id = queue(deps, call.tool_call_id, path)
            pending.append(approval_id)
            bucket.append(("approval", {"approval_id": approval_id, "tool": call.tool_name, "path": path, "notice": deps.db.get_pending(approval_id).get("display", "")}))
    deps.db.save_agent_history(deps.session_id, result.all_messages_json(), pending)
    return "需要批准才能發佈到 n8n。" if pending else str(output)


def _pydantic_ai_import_error() -> str | None:
    try:
        import pydantic_ai  # noqa: F401
        return None
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


def _base_url(request_url: str) -> str:
    if not request_url:
        return "https://api.openai.com/v1"
    if "/chat/completions" in request_url:
        return request_url.split("/chat/completions", 1)[0]
    return request_url.rstrip("/")


def _heuristic_turn(deps: AppDeps, message: str, bucket: list) -> str:
    text = message.strip()
    if text.startswith("/deploy-automation "):
        path = text.split(" ", 1)[1].strip()
        approval_id = queue_bundle_approval(deps, str(uuid4()), path)
        bucket.append(("approval", {"approval_id": approval_id, "tool": "publish_automation_bundle", "path": path, "notice": deps.db.get_pending(approval_id).get("display", "")}))
        return "請檢查整合部署包並批准；部署不自動執行桌面動作。"
    if text.startswith("/publish "):
        path = text.split(" ", 1)[1].strip()
        approval_id = queue_publish_approval(deps, str(uuid4()), path)
        bucket.append(("approval", {"approval_id": approval_id, "tool": "publish_workflow", "path": path}))
        return f"請批准發佈 {path}"
    return (
        "尚未設定模型閘道，這則訊息未執行 AI 工作。"
        "設定公司閘道 API Key 後可使用完整模型迴圈。"
        "可用 /publish n8n/workflows/xxx.json 觸發 HITL 發佈。"
    )


def _fallback_reply(message: str, deps: AppDeps) -> str:
    return f"已處理專案 {deps.project_id}。"


async def api_approve(request: Request) -> JSONResponse:
    body = await request.json()
    approval_id = body.get("approval_id")
    decision = body.get("decision") or body.get("action")
    record = DB.get_pending(approval_id)
    if record is None:
        return JSONResponse({"error": "unknown approval_id"}, status_code=404)
    if record["session_id"] != request.state.workspace["session"]:
        return JSONResponse({"error": "此批准不屬於目前對話"}, status_code=403)
    if record.get("status") != "pending":
        return JSONResponse({"error": "already resolved"}, status_code=409)
    forbidden = reject_client_overrides(body)
    if forbidden:
        return JSONResponse({"error": forbidden}, status_code=400)
    if decision not in {"approve", "deny"}:
        return JSONResponse({"error": "decision must be approve or deny"}, status_code=400)
    if _pending_expired(record):
        DB.resolve_pending(approval_id, "expired")
        return JSONResponse({"error": "approval expired"}, status_code=410)
    if decision == "approve" and DB.mode_state(record["session_id"])["mode"] != "general":
        return JSONResponse({"error": "目前模式不允許發佈"}, status_code=403)
    if decision == "deny":
        DB.resolve_pending(approval_id, decision)
        DB.append_message(record["session_id"], "system", {"content": "已拒絕發佈 " + record["args"].get("path", "")})
        AUDIT.write({"tool": "publish_workflow", "result": "denied", "approved": False})
        return JSONResponse({"ok": True, "decision": "deny"})
    project = _project_for_approval(record)
    if not project:
        return JSONResponse({"error": "approval project is not open"}, status_code=400)
    turn_id = str(uuid4())[:8]
    deps = _make_deps(project, record["session_id"], turn_id)
    acquired = False
    try:
        LOCKS.acquire(project["id"], turn_id, timeout=1)
        acquired = True
        if DB.get_pending(approval_id)["status"] != "pending":
            return JSONResponse({"error": "此批准已處理"}, status_code=409)
        from backend.hashutil import sha256_file
        if record["tool_name"] == "publish_automation_bundle":
            from backend.tools_automation import read_bundle
            _, digest = read_bundle(file_ctx(deps), record["args"]["path"])
            if digest != record["args"].get("expected_bundle_sha256"):
                return JSONResponse({"error": "整合部署包已變更，請重新要求批准", "code": "CONFLICT"}, status_code=409)
        expected = record["args"].get("expected_sha256")
        target = deps.jail.resolve(record["args"]["path"], "read")
        if expected and (not target.is_file() or sha256_file(target) != expected):
            return JSONResponse({"error": "流程已變更，請拒絕舊批准並重新要求發佈", "code": "CONFLICT"}, status_code=409)
        result = await asyncio.to_thread(dispatch_tool, deps, record["tool_name"], record["args"], approved=True)
        DB.save_approval_outcome(approval_id, result)
        DB.resolve_pending(approval_id, decision)
        DB.append_message(record["session_id"], "tool", {"name": record["tool_name"], "result": result}, turn_id=turn_id)
        DB.append_message(record["session_id"], "system", {"content": "已批准發佈 " + record["args"].get("path", "")}, turn_id=turn_id)
        reply = ""
        if DB.agent_history(record["session_id"]) and not DB.has_pending(record["session_id"]):
            try:
                reply = await _run_agent(deps, "", [])
                DB.append_message(record["session_id"], "assistant", {"content": reply}, turn_id=turn_id)
            except Exception as exc:
                reply = "發佈已完成，但模型續跑失敗：" + str(exc)
                DB.append_message(record["session_id"], "system", {"content": reply}, turn_id=turn_id)
        return JSONResponse({"ok": True, "decision": "approve", "result": json.loads(result), "reply": reply})
    except PublishConflict as exc:
        return JSONResponse({"error": str(exc), "code": "CONFLICT"}, status_code=409)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    finally:
        import anyio
        with anyio.CancelScope(shield=True):
            if acquired:
                await anyio.to_thread.run_sync(deps.wait_for_tools)
                LOCKS.release(project["id"])


def _pending_expired(record: dict[str, Any]) -> bool:
    from datetime import datetime, timezone

    raw = record.get("expires_at")
    if not raw:
        return False
    try:
        exp = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp < datetime.now(timezone.utc)


def _project_for_approval(record: dict[str, Any]) -> dict[str, str] | None:
    wanted = record.get("project_id")
    matches = [p for p in list_projects(projects_root()) if p["id"] == wanted]
    if not matches:
        return None
    return matches[0]


async def n8n_http(request: Request):
    if not N8N_STATUS["ready"]:
        return JSONResponse({"error": N8N_STATUS.get("reason") or "n8n degraded"}, status_code=503)
    return await N8N_PROXY.http(request)


async def n8n_ws(websocket: WebSocket):
    if not N8N_STATUS["ready"]:
        await websocket.close(code=1013)
        return
    await N8N_PROXY.websocket(websocket)


def _boot_n8n() -> None:
    pid_path = RUNTIME / "n8n.pid"
    cleanup_stale_pid(pid_path)
    status = start_n8n(
        node_exe=system_root() / "node" / "node.exe",
        n8n_root=system_root() / "n8n",
        data_dir=RUNTIME / "n8n_data",
        secrets_dir=RUNTIME / "secrets",
        host=POLICY.n8n_host,
        port=POLICY.n8n_port,
        pid_path=pid_path,
    )
    N8N_STATUS.update(ready=status.ready, reason=status.degraded_reason, url=status.url)


def on_startup() -> None:
    import threading

    global AUTOMATION, BROKER_SERVER
    from backend.automation_runtime import AutomationRuntime, broker_app
    from backend.n8n_lifecycle import port_in_use
    import uvicorn
    RUNTIME.mkdir(parents=True, exist_ok=True)
    (RUNTIME / "secrets").mkdir(exist_ok=True)
    (RUNTIME / "snapshots").mkdir(exist_ok=True)
    (RUNTIME / "run_staging").mkdir(exist_ok=True)
    if not port_in_use("127.0.0.1", 8771):
        AUTOMATION = AutomationRuntime(RUNTIME, system_root() / "openrpa")
        BROKER_SERVER = uvicorn.Server(uvicorn.Config(broker_app(AUTOMATION), host="127.0.0.1", port=8771, log_level="warning"))
        threading.Thread(target=BROKER_SERVER.run, name="automation-broker", daemon=True).start()
    # Never block the HTTP server on n8n; UI must open immediately.
    N8N_STATUS.update(ready=False, reason="starting")
    def boot():
        with N8N_CONTROL_LOCK:
            try:
                _boot_n8n()
            except Exception as exc:
                N8N_STATUS.update(ready=False, reason=str(exc))
    threading.Thread(target=boot, name="n8n-boot", daemon=True).start()


def on_shutdown() -> None:
    if BROKER_SERVER: BROKER_SERVER.should_exit = True
    if AUTOMATION: AUTOMATION.close()
    with N8N_CONTROL_LOCK:
        stop_n8n(RUNTIME / "n8n.pid")


routes = [
    Route("/", index),
    Route("/api/status", api_status),
    Route("/api/session", api_session),
    Route("/api/mode", api_mode, methods=["GET", "POST"]),
    Route("/api/plans", api_plans),
    Route("/api/automation", api_automation, methods=["GET", "POST"]),
    Route("/api/search/settings", api_search_settings, methods=["GET", "POST"]),
    Route("/api/search/test", api_search_test, methods=["POST"]),
    Route("/api/projects", api_projects),
    Route("/api/projects/create", api_create_project, methods=["POST"]),
    Route("/api/projects/open", api_open_project, methods=["POST"]),
    Route("/api/files", api_files),
    Route("/api/files/import", import_file, methods=["POST"]),
    Route("/api/files/export", export_project),
    Route("/api/files/download", download_file),
    Route("/api/file", api_read_file),
    Route("/api/undo", api_undo, methods=["POST"]),
    Route("/api/gateway", api_gateway, methods=["GET", "POST"]),
    Route("/api/n8n", api_n8n_control, methods=["POST"]),
    Route("/api/chat", api_chat, methods=["POST"]),
    Route("/api/approve", api_approve, methods=["POST"]),
    Route("/n8n", n8n_http, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
    Route("/n8n/{path:path}", n8n_http, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
    WebSocketRoute("/n8n/{path:path}", n8n_ws),
    Mount("/frontend", StaticFiles(directory=str(FRONTEND)), name="frontend"),
]

app = Starlette(debug=False, routes=routes, on_startup=[on_startup], on_shutdown=[on_shutdown])
app.add_middleware(FrameAncestors)


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="info")


if __name__ == "__main__":
    main()
