import json
import threading
import tempfile
import unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from backend.search_client import search_via_mcp
from backend.search_mcp import StdioSession, search, validate_config


class SearchMcpTests(unittest.TestCase):
    def test_stdio_to_real_http_upstream(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_POST(self):
                received.append((self.path, self.rfile.read(int(self.headers['Content-Length'])).decode()))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({'results': [
                    {'title': '<b>說明</b>', 'url': 'https://example.org/docs', 'content': '文件摘要'},
                    {'title': 'bad', 'url': 'javascript:alert(1)'},
                ]}).encode())
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        with tempfile.TemporaryDirectory() as tmp:
            config = Path(tmp) / 'search.json'
            config.write_text(json.dumps({'enabled': True, 'url': 'http://127.0.0.1:' + str(httpd.server_port)}))
            result = json.loads(search_via_mcp(config, {'query': 'OpenRPA 中文'}))
            self.assertEqual(len(result['results']), 1)
            self.assertEqual(result['results'][0]['title'], '說明')
            self.assertEqual(received[0][0], '/search')
            self.assertIn('format=json', received[0][1])

    def test_initialization_and_tool_catalog(self):
        session = StdioSession(Path('absent-search-config.json'))
        self.assertIn('error', session.handle({'jsonrpc': '2.0', 'id': 0, 'method': 'tools/list'}))
        init = session.handle({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18'}})
        self.assertEqual(init['result']['protocolVersion'], '2025-06-18')
        session.handle({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        catalog = session.handle({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        self.assertEqual(catalog['result']['tools'][0]['name'], 'search_web')
        result = session.handle({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'search_web', 'arguments': {'query': 'test'}}})
        self.assertTrue(result['result']['isError'])

    def test_arbitrary_upstream_and_invalid_args_rejected(self):
        cfg = {'enabled': True, 'url': 'https://example.invalid'}
        for args in ({'query': 'x', 'url': 'http://evil.invalid'}, {'query': ''}, {'query': 'x', 'page': True}, {'query': 'x', 'limit': 21}):
            with self.assertRaises(ValueError): search(cfg, args)
        for url in ('file:///etc/passwd', 'https://user:secret@example.org', 'https://example.org/?key=secret'):
            with self.assertRaises(ValueError): validate_config({'url': url})
