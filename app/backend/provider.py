from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RETRY_STATUS = {429, 502, 503, 504}


class TransportError(RuntimeError):
    pass


def request_with_retry(
    url: str,
    data: bytes | None,
    headers: dict[str, str],
    method: str = "POST",
    timeout: int = 60,
    attempts: int = 4,
    verify: bool = True,
) -> bytes:
    import ssl
    import time

    ctx = None if verify else ssl._create_unverified_context()
    last: Exception | None = None
    for i in range(attempts):
        req = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                return resp.read()
        except HTTPError as exc:
            last = exc
            if exc.code not in RETRY_STATUS or i == attempts - 1:
                raise TransportError(f"HTTP {exc.code}") from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 0.5 * (2**i)
            time.sleep(delay)
        except URLError as exc:
            last = exc
            if i == attempts - 1:
                raise TransportError(str(exc)) from exc
            time.sleep(0.5 * (2**i))
    raise TransportError(str(last) if last else "transport failed")


def load_gateway(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": config.get("requestUrl"),
        "headers": dict(config.get("headers") or {}),
        "timeout": int(config.get("timeoutSeconds") or 240),
        "verify": bool((config.get("tls") or {}).get("verify", True)),
        "model": (config.get("defaults") or {}).get("model") or "gpt-4o-mini",
        "api_key": "",
    }
