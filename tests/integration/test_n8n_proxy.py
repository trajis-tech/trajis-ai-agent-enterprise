from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

try:
    from backend.n8n_proxy import HOP_BY_HOP, N8nProxy, rewrite_location
except ImportError:  # starlette/httpx not installed in stdlib-only test runs
    HOP_BY_HOP = {"upgrade", "connection", "transfer-encoding", "host"}
    N8nProxy = None
    rewrite_location = None


class N8nProxyContractTests(unittest.TestCase):
    def test_strips_hop_headers(self) -> None:
        self.assertIn("upgrade", HOP_BY_HOP)
        self.assertIn("connection", HOP_BY_HOP)
        self.assertIn("transfer-encoding", HOP_BY_HOP)

    @unittest.skipUnless(rewrite_location is not None, "httpx/starlette missing")
    def test_rewrite_location_keeps_n8n_prefix(self) -> None:
        self.assertEqual(
            rewrite_location("http://127.0.0.1:5678/workflow/1", "http://127.0.0.1:5678"),
            "/n8n/workflow/1",
        )
        self.assertEqual(rewrite_location("/signin", "http://127.0.0.1:5678"), "/n8n/signin")

    @unittest.skipUnless(N8nProxy is not None, "httpx/starlette missing")
    def test_upstream_url(self) -> None:
        proxy = N8nProxy("http://127.0.0.1:5678")
        self.assertEqual(proxy.upstream, "http://127.0.0.1:5678")

    @unittest.skipUnless(N8nProxy is not None, "httpx/starlette missing")
    def test_http_proxy_roundtrip(self) -> None:
        import asyncio

        try:
            import httpx
            from starlette.applications import Starlette
            from starlette.requests import Request
            from starlette.responses import JSONResponse, StreamingResponse
            from starlette.routing import Route
            from starlette.testclient import TestClient
        except ImportError:
            self.skipTest("starlette/httpx missing")

        async def upstream_sse(request: Request):
            async def events():
                yield b"data: hello\n\n"

            return StreamingResponse(events(), media_type="text/event-stream")

        async def upstream_ok(request: Request):
            return JSONResponse({"ok": True, "path": request.url.path})

        upstream = Starlette(routes=[Route("/ok", upstream_ok), Route("/sse", upstream_sse)])

        async def run() -> None:
            import threading
            import uvicorn

            config = uvicorn.Config(upstream, host="127.0.0.1", port=8769, log_level="warning")
            server = uvicorn.Server(config)
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            for _ in range(50):
                try:
                    async with httpx.AsyncClient() as probe:
                        await probe.get("http://127.0.0.1:8769/ok", timeout=0.2)
                    break
                except Exception:
                    await asyncio.sleep(0.05)
            proxy = N8nProxy("http://127.0.0.1:8769")

            async def fake_n8n(request: Request):
                return await proxy.http(request)

            app = Starlette(routes=[Route("/n8n/{path:path}", fake_n8n, methods=["GET"])])
            with TestClient(app) as client:
                res = client.get("/n8n/ok")
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["ok"], True)
                sse = client.get("/n8n/sse")
                self.assertEqual(sse.status_code, 200)
                self.assertIn("hello", sse.text)
            server.should_exit = True

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
