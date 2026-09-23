from __future__ import annotations

import asyncio
from typing import AsyncIterator

import httpx
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.websockets import WebSocket

from .n8n_rewrite import rewrite_location

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
}


class N8nProxy:
    def __init__(self, upstream: str) -> None:
        self.upstream = upstream.rstrip("/")
        self._client = httpx.AsyncClient(timeout=None, follow_redirects=False)

    async def http(self, request: Request) -> Response:
        suffix = request.url.path
        if suffix.startswith("/n8n"):
            suffix = suffix[len("/n8n") :] or "/"
        url = self.upstream + suffix
        if request.url.query:
            url += "?" + request.url.query
        headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
        headers.pop("forwarded", None)
        headers["x-forwarded-host"] = request.headers.get("host", "")
        headers["x-forwarded-proto"] = request.url.scheme
        headers["host"] = self.upstream.split("://", 1)[-1]
        body = await request.body()
        try:
            req = self._client.build_request(request.method, url, headers=headers, content=body)
            upstream = await self._client.send(req, stream=True)
        except httpx.HTTPError as exc:
            return Response(f"n8n proxy error: {exc}", status_code=502)
        out_headers = [
            (k, v)
            for k, v in upstream.headers.multi_items()
            if k.lower() not in HOP_BY_HOP and k.lower() != "content-length"
        ]
        rewritten = []
        for key, value in out_headers:
            if key.lower() in {"location", "refresh"}:
                value = rewrite_location(value, self.upstream)
            rewritten.append((key, value))

        async def iterator() -> AsyncIterator[bytes]:
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()

        response = StreamingResponse(iterator(), status_code=upstream.status_code)
        response.raw_headers = [(key.encode("latin-1"), value.encode("latin-1")) for key, value in rewritten]
        return response

    async def websocket(self, websocket: WebSocket) -> None:
        await websocket.accept()
        suffix = websocket.url.path
        if suffix.startswith("/n8n"):
            suffix = suffix[len("/n8n") :] or "/"
        ws_url = self.upstream.replace("http://", "ws://").replace("https://", "wss://") + suffix
        if websocket.url.query:
            ws_url += "?" + websocket.url.query
        try:
            import websockets  # type: ignore
        except ImportError:
            await websocket.close(code=1011)
            return
        try:
            headers = _ws_headers(websocket)
            try:
                conn = websockets.connect(ws_url, additional_headers=headers)
            except TypeError:
                conn = websockets.connect(ws_url, extra_headers=headers)
            async with conn as upstream:
                async def client_to_up() -> None:
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            break
                        if "text" in message:
                            await upstream.send(message["text"])
                        elif "bytes" in message:
                            await upstream.send(message["bytes"])

                async def up_to_client() -> None:
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                tasks = {asyncio.create_task(client_to_up()), asyncio.create_task(up_to_client())}
                try:
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except Exception:
            try:
                await websocket.close(code=1011)
            except Exception:
                pass

    async def aclose(self) -> None:
        await self._client.aclose()


def _ws_headers(websocket: WebSocket) -> list[tuple[str, str]]:
    skip = {"host", "upgrade", "connection", "sec-websocket-key", "sec-websocket-version", "sec-websocket-extensions", "sec-websocket-protocol", "forwarded", "x-forwarded-host", "x-forwarded-proto"}
    return [(k, v) for k, v in websocket.headers.items() if k.lower() not in skip] + [("x-forwarded-host", websocket.headers.get("host", "")), ("x-forwarded-proto", "https" if websocket.url.scheme == "wss" else "http")]
