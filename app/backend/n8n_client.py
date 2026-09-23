from __future__ import annotations

import json
from dataclasses import dataclass
from http.cookiejar import CookieJar
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


@dataclass
class N8nStatus:
    ready: bool
    degraded_reason: str | None = None
    url: str = ""


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload and isinstance(payload["data"], (dict, list)):
        return payload["data"]
    return payload


class N8nClient:
    def __init__(self, base: str, api_key: str | None) -> None:
        self.base = base.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self.api_key:
            headers["X-N8N-API-KEY"] = self.api_key
        return headers

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, timeout: int = 20) -> dict[str, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(self.base + path, data=data, method=method, headers=self._headers())
        try:
            with urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                payload = json.loads(raw) if raw else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"n8n HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"n8n unreachable: {exc}") from exc
        payload = _unwrap(payload)
        return payload if isinstance(payload, dict) else {"value": payload}

    def health(self) -> bool:
        for path in ("/healthz/readiness",):
            try:
                req = Request(self.base + path, method="GET", headers={"Accept": "application/json"})
                with urlopen(req, timeout=5) as resp:
                    if 200 <= getattr(resp, "status", 200) < 300:
                        return True
            except Exception:
                continue
        return False

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self.request("GET", f"/api/v1/workflows/{workflow_id}")

    def create_workflow(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = {key: payload[key] for key in ("name", "nodes", "connections", "settings") if key in payload}
        body["nodes"] = [{key: value for key, value in node.items() if value is not None}
                         for node in body.get("nodes", [])]
        return self.request("POST", "/api/v1/workflows", body)

    def update_workflow(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = {key: payload[key] for key in ("name", "nodes", "connections", "settings") if key in payload}
        body["nodes"] = [{key: value for key, value in node.items() if value is not None}
                         for node in body.get("nodes", [])]
        return self.request("PUT", f"/api/v1/workflows/{workflow_id}", body)


class N8nSession:
    """Cookie session for first-run owner setup (not used by Agent tools)."""

    def __init__(self, base: str) -> None:
        self.base = base.rstrip("/")
        self._jar = CookieJar()
        self._opener = build_opener(HTTPCookieProcessor(self._jar))

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, timeout: int = 20) -> Any:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                return _unwrap(json.loads(raw) if raw else {})
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"n8n HTTP {exc.code}: {detail}") from exc
