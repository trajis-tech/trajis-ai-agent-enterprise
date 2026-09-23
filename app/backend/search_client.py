"""A bounded, local MCP stdio client. Only the fixed bundled server is launched."""
import json
import os
import subprocess
import sys
from pathlib import Path


def search_via_mcp(config: Path, args: dict) -> str:
    requests = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-06-18', 'capabilities': {},
            'clientInfo': {'name': 'local-agent', 'version': '1.0.0'}}},
        {'jsonrpc': '2.0', 'method': 'notifications/initialized'},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/call', 'params': {'name': 'search_web', 'arguments': args}},
    ]
    import threading
    process = subprocess.Popen([sys.executable, str(Path(__file__).with_name('search_mcp.py')), '--config', str(config)],
                               cwd=str(Path(__file__).resolve().parents[1]), stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    timer = threading.Timer(25, lambda: process.kill() if process.poll() is None else None)
    timer.daemon = True
    timer.start()
    def send(request):
        process.stdin.write((json.dumps(request, ensure_ascii=False) + '\n').encode('utf-8'))
        process.stdin.flush()
    def receive(expected):
        line = process.stdout.readline(65537)
        if not line or len(line) > 65536:
            raise RuntimeError('本機 MCP 無回應、逾時或回應過大')
        response = json.loads(line)
        if response.get('jsonrpc') != '2.0' or response.get('id') != expected:
            raise RuntimeError('本機 MCP 回應識別碼不符')
        return response
    try:
        send(requests[0])
        hello = receive(1)
        if hello.get('result', {}).get('protocolVersion') != '2025-06-18':
            raise RuntimeError('本機 MCP 協定初始化失敗')
        send(requests[1])
        send(requests[2])
        reply = receive(2)
    finally:
        timer.cancel()
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdin.close()
        process.stdout.close()
    output = reply.get('result', {})
    if 'error' in reply or not output.get('content'):
        raise RuntimeError('本機 MCP 工具回應不完整')
    text = output['content'][0]['text']
    if output.get('isError'):
        raise ValueError(text)
    return text
