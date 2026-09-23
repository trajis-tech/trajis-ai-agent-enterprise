"""Isolated preview server for browser smoke tests; no model or n8n requests."""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from backend import server
from backend.state import StateDB
from backend.snapshot import SnapshotStore
from backend.locks import ProjectLock
from backend.audit import AuditLog
import uvicorn

if __name__ == '__main__':
    if '--reuse' in sys.argv:
        from types import SimpleNamespace
        reuse = Path(sys.argv[sys.argv.index('--reuse') + 1]).resolve()
        if not reuse.is_relative_to((ROOT / 'tests').resolve()) or not reuse.name.startswith('ui-test-'):
            raise ValueError('reuse must be an isolated test directory')
        temporary = SimpleNamespace(name=str(reuse))
    else:
        temporary = tempfile.TemporaryDirectory(prefix='ui-test-', dir=ROOT / 'tests')
    fs = Path(temporary.name) / 'filesystem'
    (fs / 'projects').mkdir(parents=True, exist_ok=True)
    runtime = fs / '.runtime'
    server.DB = StateDB(runtime / 'state.db')
    server.SNAPSHOTS = SnapshotStore(runtime / 'snapshots')
    server.LOCKS = ProjectLock(runtime)
    server.AUDIT = AuditLog(runtime / 'audit.jsonl')
    server.RUNTIME = runtime
    server.filesystem_root = lambda: fs
    server.projects_root = lambda: fs / 'projects'
    server.system_root = lambda: fs / 'system'
    config = Path(temporary.name) / 'gateway.json'
    if not config.exists():
        config.write_text('{}', encoding='utf-8')
    server.custom_api_path = lambda: config
    server.app.router.on_startup.clear()
    server.app.router.on_shutdown.clear()
    if '--automation' in sys.argv:
        import threading
        from backend.automation_runtime import AutomationRuntime, broker_app
        server.AUTOMATION = AutomationRuntime(runtime, ROOT / 'filesystem/system/openrpa')
        server.BROKER_SERVER = uvicorn.Server(uvicorn.Config(broker_app(server.AUTOMATION), host='127.0.0.1', port=8871, log_level='warning'))
        threading.Thread(target=server.BROKER_SERVER.run, daemon=True).start()
    if '--n8n' in sys.argv:
        import threading
        from backend.n8n_lifecycle import start_n8n
        from backend.n8n_proxy import N8nProxy
        url = 'http://127.0.0.1:5688'
        server.N8N_PROXY = N8nProxy(url)
        server.N8N_STATUS.update(ready=False, reason='starting', url=url)
        def boot_n8n_test():
            status = start_n8n(node_exe=ROOT / 'filesystem/system/node/node.exe',
                n8n_root=ROOT / 'filesystem/system/n8n', data_dir=runtime / 'n8n_data',
                secrets_dir=runtime / 'secrets', host='127.0.0.1', port=5688, pid_path=runtime / 'n8n.pid', automation_port=8871)
            server.N8N_STATUS.update(ready=status.ready, reason=status.degraded_reason, url=url)
        threading.Thread(target=boot_n8n_test, daemon=True).start()
    print('ISOLATED_TEST_ROOT=' + str(temporary.name), flush=True)
    uvicorn.run(server.app, host='127.0.0.1', port=8766)
