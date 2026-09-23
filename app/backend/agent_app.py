from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .deps import AppDeps
from .hashutil import sha256_text, sha256_file
from .history import model_view
from .jail import JailError
from .tools_file import (
    FileContext,
    delete_file,
    edit_file,
    glob_files,
    grep_files,
    ls,
    read_file,
    write_file,
)
from .tools_n8n import PublishConflict, publish_workflow, validate_workflow_file, write_workflow_json
from .tools_file import ToolConflict
from .tools_run import run_python

try:
    from pydantic_ai import RunContext
except Exception:  # product UI must still import this module if pydantic_ai is broken
    RunContext = Any  # type: ignore[misc,assignment]

SYSTEM_PROMPT = """你是企業本機 AI Agent。只在目前專案內工作。
filesystem/system 唯讀。不可提及其他專案、不可 pip/npm、不可讀 .runtime。
寫檔與 run_python 會自動執行並稽核。publish_workflow 與 publish_automation_bundle 需要人工批准。
不要啟用 n8n workflow，不要建立憑證，不要自動執行桌面流程。
一次完成 n8n + OpenRPA 時，使用 write_automation_bundle 產生兩端部署包，驗證後再要求整包批准。
n8n 的 Local OpenRPA 節點已預載本機連線（127.0.0.1:8771）；那是本產品自製 Broker，不是 OpenRPA 官方 REST。
OpenRPA 以目前 Windows 使用者權限操作桌面，不是專案 jail 或 OS 沙箱。
網頁搜尋只經本機 SearXNG MCP 與已設定上游。依賴說明先用 search_dependency_docs；知識庫未匯入時據實說明，不要編造文件。
先 inspect_automation_environment 再規劃本機自動化。
"""


def file_ctx(deps: AppDeps) -> FileContext:
    return FileContext(
        jail=deps.jail,
        snapshots=deps.snapshots,
        audit=deps.audit,
        project_id=deps.project_id,
        turn_id=deps.turn_id,
        project_root=deps.project_root,
        cancel_event=deps.cancel_event,
    )


MODE_INSTRUCTIONS = {
    "general": "一般模式：可按既有政策修改目前專案及執行；發佈仍需批准。",
    "plan": "計畫模式：只能讀取、分析、靜態驗證與保存計畫。不可寫專案、跑程式、部署、啟停服務。請提出步驟、依賴、驗收與待補資訊；save_plan 可保存計畫。",
    "ask": "唯讀模式：只可讀取、分析及靜態驗證，不可修改檔案、保存計畫、執行程式或部署。",
}


def mode_allows(mode: str, name: str) -> bool:
    if mode not in MODE_INSTRUCTIONS:
        return False
    readonly = {
        "ls", "read_file", "glob", "grep", "validate_workflow", "validate_automation_bundle",
        "search_web", "get_automation_run", "inspect_automation_environment",
        "search_dependency_docs", "get_dependency_doc", "get_recipe",
    }
    return name in readonly or (name == "save_plan" and mode in {"general", "plan"}) or (mode == "general" and name in {"write_file", "edit_file", "delete_file", "run_python", "write_workflow_json", "publish_workflow", "write_automation_bundle", "publish_automation_bundle", "cancel_automation_run"})


def check_mode(deps: AppDeps, name: str) -> None:
    if not mode_allows("general", name):
        raise KeyError(name)
    current = deps.db.mode_state(deps.session_id)
    if current["epoch"] != deps.mode_epoch or current["mode"] != deps.chat_mode:
        raise PermissionError("模式已變更，請開始新回合")
    if not mode_allows(deps.chat_mode, name):
        raise PermissionError("目前對話模式不允許此操作：" + name)


def dispatch_tool(deps: AppDeps, name: str, args: dict[str, Any], approved: bool = False) -> str:
    check_mode(deps, name)
    with deps.tool_condition:
        if deps.cancel_event.is_set():
            raise RuntimeError("回合已中止")
        deps.active_tools += 1
    try:
        if deps.progress:
            deps.progress(name)
        return _dispatch_tool(deps, name, args, approved)
    finally:
        with deps.tool_condition:
            deps.active_tools -= 1
            deps.tool_condition.notify_all()


def _dispatch_tool(deps: AppDeps, name: str, args: dict[str, Any], approved: bool = False) -> str:
    ctx = file_ctx(deps)
    if name == "write_automation_bundle":
        from .tools_automation import write_bundle
        return write_bundle(ctx, args["path"], args["artifact"], args.get("inputs") or {}, deps.policy)
    if name == "validate_automation_bundle":
        from .tools_automation import read_bundle
        manifest, digest = read_bundle(ctx, args["path"])
        return json.dumps({"ok": True, "hash": digest, "name": manifest["openrpa"]["name"], "validation": "static_only"})
    if name == "publish_automation_bundle":
        from .tools_automation import publish_bundle
        return publish_bundle(ctx, args["path"], deps.policy, deps.n8n, deps.db, deps.automation, approved)
    if name in {"get_automation_run", "cancel_automation_run"}:
        if deps.automation is None: raise RuntimeError("本機 OpenRPA 服務未啟動")
        fn = deps.automation.cancel if name == "cancel_automation_run" else deps.automation.get_run
        return json.dumps(fn(args["run_id"], deps.project_id), ensure_ascii=False)
    if name == "inspect_automation_environment":
        from .knowledge import knowledge_path, knowledge_status
        from .search_mcp import read_config
        search = read_config(deps.search_config) if deps.search_config else {"enabled": False, "url": ""}
        auto = deps.automation.health() if deps.automation else {
            "installed": False, "running": False, "reason": "橋接服務未啟動",
        }
        return json.dumps({
            "mode": deps.chat_mode,
            "n8n_client": deps.n8n is not None,
            "openrpa": auto,
            "broker": "127.0.0.1:8771",
            "search": {"enabled": bool(search.get("enabled")), "upstream_configured": bool(search.get("url"))},
            "knowledge": knowledge_status(knowledge_path(deps.system_root)),
            "notices": [
                "OpenRPA 以目前 Windows 使用者權限執行桌面動作，不是專案資料夾隔離或 OS 沙箱。",
                "127.0.0.1:8771 是本產品自製 Broker，不是 OpenRPA 官方 REST API。",
                "批准整合部署不會自動啟用 n8n，也不會立刻執行桌面流程。",
            ],
        }, ensure_ascii=False)
    if name == "search_dependency_docs":
        from .knowledge import knowledge_path, search_dependency_docs
        return json.dumps(search_dependency_docs(
            knowledge_path(deps.system_root), args["query"], args.get("component"), args.get("version"),
            int(args.get("limit") or 8),
        ), ensure_ascii=False)
    if name == "get_dependency_doc":
        from .knowledge import knowledge_path, get_dependency_doc
        return json.dumps(get_dependency_doc(knowledge_path(deps.system_root), int(args["chunk_id"])), ensure_ascii=False)
    if name == "get_recipe":
        from .knowledge import knowledge_path, get_recipe
        return json.dumps(get_recipe(knowledge_path(deps.system_root), args["recipe_id"]), ensure_ascii=False)
    if name == "search_web":
        from .search_client import search_via_mcp
        if deps.search_config is None:
            raise ValueError("本機搜尋尚未設定")
        return search_via_mcp(deps.search_config, args)
    if name == "save_plan":
        return json.dumps({"plan_id": deps.db.save_plan(deps.session_id, args["content"]), "status": "saved"})
    if name == "ls":
        return ls(ctx, args.get("path") or ".")
    if name == "read_file":
        return read_file(ctx, args["path"], int(args.get("max_chars") or 80000))
    if name == "write_file":
        return write_file(ctx, args["path"], args.get("content") or "")
    if name == "edit_file":
        return edit_file(ctx, args["path"], args["old_text"], args["new_text"], args["expected_sha256"])
    if name == "delete_file":
        return delete_file(ctx, args["path"])
    if name == "glob":
        return glob_files(ctx, args.get("pattern") or "**/*")
    if name == "grep":
        return grep_files(ctx, args["query"], args.get("pattern") or "**/*")
    if name == "run_python":
        return run_python(
            ctx,
            args["script_path"],
            args.get("args") or [],
            deps.policy,
            deps.interpreter,
            deps.staging_root,
            deps.pythonhome,
        )
    if name == "write_workflow_json":
        return write_workflow_json(ctx, args["path"], args["workflow"], deps.policy)
    if name == "validate_workflow":
        return validate_workflow_file(ctx, args["path"], deps.policy)
    if name == "publish_workflow":
        return publish_workflow(ctx, args["path"], deps.policy, deps.n8n, deps.db, approved=approved)
    raise KeyError(name)


READ_TOOLS = {
    "ls", "read_file", "glob", "grep", "validate_workflow", "validate_automation_bundle",
    "search_web", "get_automation_run", "inspect_automation_environment",
    "search_dependency_docs", "get_dependency_doc", "get_recipe",
}
SEQUENTIAL_TOOLS = {
    "write_file", "edit_file", "delete_file", "run_python", "write_workflow_json",
    "publish_workflow", "write_automation_bundle", "publish_automation_bundle",
    "cancel_automation_run", "save_plan",
}
DEFERRED_TOOLS = {"publish_workflow", "publish_automation_bundle"}


def tool_specs() -> list[dict[str, Any]]:
    return [
        {"name": "ls", "parallel": True, "retries": 1},
        {"name": "read_file", "parallel": True, "retries": 1},
        {"name": "grep", "parallel": True, "retries": 1},
        {"name": "glob", "parallel": True, "retries": 1},
        {"name": "inspect_automation_environment", "parallel": True, "retries": 1},
        {"name": "search_dependency_docs", "parallel": True, "retries": 1},
        {"name": "get_dependency_doc", "parallel": True, "retries": 1},
        {"name": "get_recipe", "parallel": True, "retries": 1},
        {"name": "search_web", "parallel": False, "retries": 1},
        {"name": "save_plan", "parallel": False, "retries": 1},
        {"name": "write_file", "parallel": False, "retries": 1},
        {"name": "edit_file", "parallel": False, "retries": 1},
        {"name": "delete_file", "parallel": False, "retries": 0},
        {"name": "run_python", "parallel": False, "retries": 0},
        {"name": "write_workflow_json", "parallel": False, "retries": 1},
        {"name": "validate_workflow", "parallel": True, "retries": 1},
        {"name": "write_automation_bundle", "parallel": False, "retries": 1},
        {"name": "validate_automation_bundle", "parallel": True, "retries": 1},
        {"name": "publish_workflow", "parallel": False, "retries": 0, "deferred": True},
        {"name": "publish_automation_bundle", "parallel": False, "retries": 0, "deferred": True},
        {"name": "get_automation_run", "parallel": True, "retries": 1},
        {"name": "cancel_automation_run", "parallel": False, "retries": 0},
    ]


def build_pydantic_agent(model: Any | None = None, mode: str = "general") -> Any:
    if mode not in MODE_INSTRUCTIONS:
        raise ValueError("不支援的對話模式")
    from pydantic_ai import Agent, RunContext as _RunContext

    globals()["RunContext"] = _RunContext

    try:
        from pydantic_ai import DeferredToolRequests
    except ImportError:  # pragma: no cover
        from pydantic_ai.output import DeferredToolRequests  # type: ignore

    agent = Agent(
        model,
        deps_type=AppDeps,
        output_type=[str, DeferredToolRequests],
        instructions=SYSTEM_PROMPT + "\n當前模式限制優先於以上一般能力說明：" + MODE_INSTRUCTIONS[mode],
    )

    def _tool(name: str, retries: int, sequential: bool, deferred: bool = False):
        kwargs: dict[str, Any] = {"name": name, "retries": retries}
        if sequential:
            kwargs["sequential"] = True

        def deco(fn: Callable[..., Any]) -> Any:
            if not mode_allows(mode, name):
                return fn
            if not deferred:
                return agent.tool(**kwargs)(fn)
            try:
                return agent.tool(requires_approval=True, **kwargs)(fn)
            except TypeError:
                return agent.tool(require_approval=True, **kwargs)(fn)

        return deco

    @_tool("inspect_automation_environment", 1, False)
    def tool_inspect_env(ctx: RunContext[AppDeps]) -> str:
        """回報本機 n8n、OpenRPA Broker、SearXNG 與依賴知識庫狀態。不執行流程、不修改檔案。"""
        return dispatch_tool(ctx.deps, "inspect_automation_environment", {})

    @_tool("search_dependency_docs", 1, False)
    def tool_search_docs(ctx: RunContext[AppDeps], query: str, component: str | None = None, version: str | None = None, limit: int = 8) -> str:
        """唯讀檢索本機依賴知識庫。知識庫未匯入時會明確回報，不可改查外網或編造內容。"""
        return dispatch_tool(ctx.deps, "search_dependency_docs", {"query": query, "component": component, "version": version, "limit": limit})

    @_tool("get_dependency_doc", 1, False)
    def tool_get_doc(ctx: RunContext[AppDeps], chunk_id: int) -> str:
        """依 chunk_id 讀取知識庫片段，含來源與驗證狀態。"""
        return dispatch_tool(ctx.deps, "get_dependency_doc", {"chunk_id": chunk_id})

    @_tool("get_recipe", 1, False)
    def tool_get_recipe(ctx: RunContext[AppDeps], recipe_id: str) -> str:
        """讀取依賴操作 recipe。沒有來源證據時不要當成已驗證步驟。"""
        return dispatch_tool(ctx.deps, "get_recipe", {"recipe_id": recipe_id})

    @_tool("write_automation_bundle", 0, True)
    def tool_write_bundle(ctx: RunContext[AppDeps], path: str, artifact: dict[str, Any], inputs: dict[str, Any] | None = None) -> str:
        """一次產生 OpenRPA 與預配置 n8n 流程。artifact 必含 name/xaml，可含 parameters。只保存，不執行；生成後驗證並要求整包批准。"""
        return dispatch_tool(ctx.deps, "write_automation_bundle", {"path": path, "artifact": artifact, "inputs": inputs or {}})

    @_tool("validate_automation_bundle", 1, False)
    def tool_validate_bundle(ctx: RunContext[AppDeps], path: str) -> str:
        """只進行部署包 XML/JSON 與兩端連結的靜態驗證，不執行 XAML。"""
        return dispatch_tool(ctx.deps, "validate_automation_bundle", {"path": path})

    @_tool("publish_automation_bundle", 0, True, deferred=True)
    def tool_publish_bundle(ctx: RunContext[AppDeps], path: str) -> str:
        """需要批准：部署 OpenRPA 與 inactive n8n。批准後可由 n8n 手動觸發桌面流程；不自動啟用或執行。"""
        return dispatch_tool(ctx.deps, "publish_automation_bundle", {"path": path}, approved=bool(getattr(ctx, "tool_call_approved", False)))

    @_tool("get_automation_run", 0, False)
    def tool_get_run(ctx: RunContext[AppDeps], run_id: str) -> str:
        return dispatch_tool(ctx.deps, "get_automation_run", {"run_id": run_id})

    @_tool("cancel_automation_run", 0, True)
    def tool_cancel_run(ctx: RunContext[AppDeps], run_id: str) -> str:
        return dispatch_tool(ctx.deps, "cancel_automation_run", {"run_id": run_id})

    @_tool("search_web", 0, True)
    def tool_search(ctx: RunContext[AppDeps], query: str, language: str = "zh-TW", time_range: str = "", page: int = 1, limit: int = 8) -> str:
        """經本機 SearXNG MCP 搜尋；query 會送到設定的上游。勿帶入秘密或檔案全文。"""
        return dispatch_tool(ctx.deps, "search_web", {"query": query, "language": language, "time_range": time_range, "page": page, "limit": limit})

    @_tool("save_plan", 0, True)
    def tool_save_plan(ctx: RunContext[AppDeps], content: str) -> str:
        """保存包含步驟、依賴與驗收的計畫，僅寫入服務端計畫記錄。"""
        return dispatch_tool(ctx.deps, "save_plan", {"content": content})

    @_tool("ls", 1, False)
    def tool_ls(ctx: RunContext[AppDeps], path: str = ".") -> str:
        return dispatch_tool(ctx.deps, "ls", {"path": path})

    @_tool("read_file", 1, False)
    def tool_read(ctx: RunContext[AppDeps], path: str, max_chars: int = 80000) -> str:
        return dispatch_tool(ctx.deps, "read_file", {"path": path, "max_chars": max_chars})

    @_tool("write_file", 1, True)
    def tool_write(ctx: RunContext[AppDeps], path: str, content: str) -> str:
        return dispatch_tool(ctx.deps, "write_file", {"path": path, "content": content})

    @_tool("edit_file", 1, True)
    def tool_edit(ctx: RunContext[AppDeps], path: str, old_text: str, new_text: str, expected_sha256: str) -> str:
        return dispatch_tool(
            ctx.deps,
            "edit_file",
            {"path": path, "old_text": old_text, "new_text": new_text, "expected_sha256": expected_sha256},
        )

    @_tool("delete_file", 0, True)
    def tool_delete(ctx: RunContext[AppDeps], path: str) -> str:
        return dispatch_tool(ctx.deps, "delete_file", {"path": path})

    @_tool("glob", 1, False)
    def tool_glob(ctx: RunContext[AppDeps], pattern: str) -> str:
        return dispatch_tool(ctx.deps, "glob", {"pattern": pattern})

    @_tool("grep", 1, False)
    def tool_grep(ctx: RunContext[AppDeps], query: str, pattern: str = "**/*") -> str:
        return dispatch_tool(ctx.deps, "grep", {"query": query, "pattern": pattern})

    @_tool("run_python", 0, True)
    def tool_run(ctx: RunContext[AppDeps], script_path: str, args: list[str] | None = None) -> str:
        return dispatch_tool(ctx.deps, "run_python", {"script_path": script_path, "args": args or []})

    @_tool("write_workflow_json", 1, True)
    def tool_wjson(ctx: RunContext[AppDeps], path: str, workflow: dict[str, Any]) -> str:
        return dispatch_tool(ctx.deps, "write_workflow_json", {"path": path, "workflow": workflow})

    @_tool("validate_workflow", 1, False)
    def tool_val(ctx: RunContext[AppDeps], path: str) -> str:
        return dispatch_tool(ctx.deps, "validate_workflow", {"path": path})

    @_tool("publish_workflow", 0, True, deferred=True)
    def tool_pub(ctx: RunContext[AppDeps], path: str) -> str:
        approved = bool(getattr(ctx, "tool_call_approved", False))
        return dispatch_tool(ctx.deps, "publish_workflow", {"path": path}, approved=approved)

    return agent


def usage_limits(deps: AppDeps) -> Any:
    import inspect

    from pydantic_ai.usage import UsageLimits

    params = inspect.signature(UsageLimits).parameters
    mapping = {
        "request_limit": deps.policy.request_limit,
        "tool_calls_limit": deps.policy.tool_calls_limit,
        "total_tokens_limit": deps.policy.total_tokens_limit,
        "request_tokens_limit": deps.policy.per_request_input_tokens_limit,
        "input_tokens_limit": deps.policy.per_request_input_tokens_limit,
    }
    kwargs = {key: value for key, value in mapping.items() if key in params}
    return UsageLimits(**kwargs)


def pending_expires() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=12)).isoformat()


def queue_publish_approval(deps: AppDeps, tool_call_id: str, path: str) -> str:
    check_mode(deps, "publish_workflow")
    target = deps.jail.resolve(path, "read")
    if not target.is_file():
        raise FileNotFoundError(path)
    args = {"path": path, "expected_sha256": sha256_file(target)}
    return deps.db.put_pending(
        {
            "session_id": deps.session_id,
            "project_id": deps.project_id,
            "tool_call_id": tool_call_id,
            "tool_name": "publish_workflow",
            "args_hash": sha256_text(json.dumps(args, sort_keys=True)),
            "args": args,
            "display": f"Publish {path} to local n8n",
            "expires_at": pending_expires(),
        }
    )


def queue_bundle_approval(deps: AppDeps, tool_call_id: str, path: str) -> str:
    from .tools_automation import read_bundle
    check_mode(deps, "publish_automation_bundle")
    _, digest = read_bundle(file_ctx(deps), path)
    args = {"path": path, "expected_bundle_sha256": digest}
    return deps.db.put_pending({"session_id": deps.session_id, "project_id": deps.project_id,
        "tool_call_id": tool_call_id, "tool_name": "publish_automation_bundle",
        "args_hash": sha256_text(json.dumps(args, sort_keys=True)), "args": args,
        "display": "整合部署：" + path + "；批准後可由 n8n 手動執行桌面流程，不自動啟用或執行。",
        "expires_at": pending_expires()})
