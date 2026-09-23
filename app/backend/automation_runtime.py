"""Managed local OpenRPA execution and authenticated n8n loopback bridge."""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

from .atomic import atomic_write_text


def service_token(path: Path) -> str:
    if not path.exists():
        atomic_write_text(path, secrets.token_hex(32))
    return path.read_text(encoding='utf-8').strip()


class AutomationRuntime:
    def __init__(self, runtime: Path, binaries: Path):
        self.root, self.binaries = runtime / 'automation', binaries
        self.root.mkdir(parents=True, exist_ok=True)
        self.mutex = threading.RLock()
        self.db = sqlite3.connect(self.root / 'automation.db', check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS runtime_flags(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS deployments(id TEXT PRIMARY KEY, project_id TEXT NOT NULL, artifact TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0);
          CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, deployment_id TEXT NOT NULL, idempotency TEXT NOT NULL, payload_hash TEXT NOT NULL, state TEXT NOT NULL, result TEXT NOT NULL DEFAULT '{}', created REAL NOT NULL, UNIQUE(deployment_id,idempotency));
        ''')
        interrupted = self.db.execute("SELECT COUNT(*) FROM runs WHERE state IN ('starting','running','cancel_requested')").fetchone()[0]
        if interrupted:
            self.db.execute("INSERT OR REPLACE INTO runtime_flags VALUES ('quarantined',1)")
        self.db.execute("UPDATE runs SET state='interrupted',result=? WHERE state IN ('queued','starting','running','cancel_requested')", (json.dumps({'error': '服務曾中斷；不自動重跑，請檢查桌面狀態'}),))
        self.db.commit()
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='openrpa-desktop')
        self.robot = None
        self.robot_deployment = None
        self.cancellations = {}
        self.stopping = False
        flag = self.db.execute("SELECT value FROM runtime_flags WHERE key='quarantined'").fetchone()
        self.quarantined = bool(flag and flag[0])
        self.token_path = runtime / 'secrets' / 'openrpa_service_token.txt'
        self.token = service_token(self.token_path)

    def health(self):
        return {'installed': (self.binaries / 'OpenRPA.exe').is_file() and (self.binaries / 'LocalOpenRpaBridge.exe').is_file(),
                'running': self.robot is not None and self.robot.poll() is None,
                'quarantined': self.quarantined, 'version': '1.4.57.13', 'transport': 'loopback HTTP → .NET IPC',
                'reason': '前次執行狀態不明，請檢查桌面後停止執行器並解除暫停' if self.quarantined else ''}

    def _pause(self):
        with self.mutex:
            self.quarantined = True
            self.db.execute("INSERT OR REPLACE INTO runtime_flags VALUES ('quarantined',1)")
            self.db.commit()

    def recover(self):
        """Explicit operator recovery; never replay interrupted desktop work."""
        with self.mutex:
            if not self.quarantined:
                return self.health()
            pending = self.db.execute("SELECT COUNT(*) FROM runs WHERE state IN ('queued','starting','running','cancel_requested')").fetchone()[0]
            if pending:
                raise RuntimeError('佇列仍在收束，請稍後再解除暫停')
            if self.robot is not None and self.robot.poll() is None:
                self.robot.terminate()
                self.robot.wait(timeout=10)
            self.robot = None
            self.robot_deployment = None
            try:
                self._ipc('ping', timeout=2)
            except Exception:
                pass
            else:
                raise RuntimeError('另一個 OpenRPA 仍在運行，請先確認並關閉該執行器')
            self.db.execute("INSERT OR REPLACE INTO runtime_flags VALUES ('quarantined',0)")
            self.db.commit()
            self.quarantined = False
            return self.health()

    def register(self, project_id: str, artifact: dict) -> str:
        raw = json.dumps(artifact, sort_keys=True, ensure_ascii=False)
        ident = hashlib.sha256((project_id + '\n' + raw).encode()).hexdigest()[:32]
        with self.mutex:
            self.db.execute('INSERT OR IGNORE INTO deployments(id,project_id,artifact) VALUES (?,?,?)', (ident, project_id, raw))
            self.db.commit()
        return ident

    def enable(self, ident: str):
        with self.mutex:
            self.db.execute('UPDATE deployments SET enabled=1 WHERE id=?', (ident,))
            self.db.commit()

    def deployment(self, ident: str, project_id=None):
        with self.mutex:
            row = self.db.execute('SELECT * FROM deployments WHERE id=?', (ident,)).fetchone()
        if row is None or (project_id is not None and row['project_id'] != project_id):
            raise ValueError('找不到目前專案的已部署流程')
        return dict(row)

    def submit(self, ident: str, inputs: dict, key: str):
        if not isinstance(inputs, dict) or len(json.dumps(inputs)) > 100000:
            raise ValueError('輸入需為不超過 100 KB 的 JSON object')
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise ValueError('必須提供執行識別碼')
        dep = self.deployment(ident)
        if not dep['enabled']: raise PermissionError('整合流程尚未完成批准部署')
        digest = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
        with self.mutex:
            old = self.db.execute('SELECT * FROM runs WHERE deployment_id=? AND idempotency=?', (ident, key)).fetchone()
            if old:
                if old['payload_hash'] != digest: raise ValueError('執行識別碼已用於不同輸入')
                return self.get_run(old['id'])
            if self.stopping or self.quarantined: raise RuntimeError('OpenRPA 已停止或執行狀態待確認')
            pending = self.db.execute("SELECT count(*) FROM runs WHERE state IN ('queued','starting','running','cancel_requested')").fetchone()[0]
            if pending >= 16: raise RuntimeError('OpenRPA 佇列已滿')
            run_id = uuid4().hex
            self.db.execute('INSERT INTO runs(id,deployment_id,idempotency,payload_hash,state,created) VALUES (?,?,?,?,?,?)', (run_id, ident, key, digest, 'queued', time.time()))
            self.db.commit()
            self.cancellations[run_id] = threading.Event()
            self.pool.submit(self._run, run_id, dep, inputs)
        return self.get_run(run_id)

    def list_runs(self, project_id):
        with self.mutex:
            rows = self.db.execute('SELECT r.id FROM runs r JOIN deployments d ON d.id=r.deployment_id WHERE d.project_id=? ORDER BY r.created DESC LIMIT 30', (project_id,)).fetchall()
        return [self.get_run(row['id'], project_id) for row in rows]

    def get_run(self, run_id: str, project_id=None):
        with self.mutex:
            row = self.db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
        if row is None: raise ValueError('找不到執行記錄')
        self.deployment(row['deployment_id'], project_id)
        return {'run_id': row['id'], 'deployment_id': row['deployment_id'], 'status': row['state'],
                **json.loads(row['result'])}

    def _state(self, run_id, state, result=None):
        with self.mutex:
            self.db.execute('UPDATE runs SET state=?,result=? WHERE id=?', (state, json.dumps(result or {}, ensure_ascii=False), run_id))
            self.db.commit()

    def cancel(self, run_id: str, project_id=None):
        result = self.get_run(run_id, project_id)
        if result['status'] in {'succeeded', 'failed', 'cancelled', 'unknown', 'interrupted', 'blocked'}: return result
        with self.mutex:
            event = self.cancellations.get(run_id)
            if event: event.set()
        return self.get_run(run_id, project_id)

    def _ipc(self, operation, workflow=None, inputs=None, timeout=10):
        args = [str(self.binaries / 'LocalOpenRpaBridge.exe'), operation]
        if workflow: args.append(workflow)
        result = subprocess.run(args, input=json.dumps(inputs or {}).encode(), stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        data = json.loads(result.stdout.decode('utf-8-sig').strip())
        if result.returncode: raise RuntimeError(data.get('error', 'OpenRPA IPC 失敗'))
        return data

    def _profile(self, dep):
        profile = self.root / 'profiles' / dep['id']
        profile.mkdir(parents=True, exist_ok=True)
        artifact = json.loads(dep['artifact'])
        config = {'wsurl': '', 'isagent': True, 'showloadingscreen': False, 'enable_analytics': False, 'doupdatecheck': False,
                  'restore_dependencies_on_startup': False, 'autoupdateupdater': False,
                  'remote_allowed_killing_any': True, 'log_to_file': True,
                  'properties': {'StorageFileSystem_enabled': True, 'StorageFileSystem_strict': True,
                                 'StorageLiteDB_enabled': False}}
        atomic_write_text(profile / 'settings.json', json.dumps(config))
        project = {'_id': dep['id'], '_type': 'project', 'name': 'LocalAutomation', 'Filename': 'LocalAutomation.rpaproj', 'isDirty': False, 'isLocalOnly': True}
        workflow = {'_id': dep['id'], '_type': 'workflow', 'name': artifact['name'], 'projectid': dep['id'],
                    'Filename': 'Workflow.xaml', 'Xaml': artifact['xaml'], 'Parameters': artifact.get('parameters', []),
                    'isDirty': False, 'isLocalOnly': True, 'Serializable': True}
        atomic_write_text(profile / 'offline' / 'projects' / (dep['id'] + '.json'), json.dumps(project))
        atomic_write_text(profile / 'offline' / 'workflows' / (dep['id'] + '.json'), json.dumps(workflow))
        return profile

    def _ensure_robot(self, dep, cancel_event=None):
        if self.robot is not None and self.robot.poll() is None:
            if self.robot_deployment == dep['id']: return
            self.robot.terminate(); self.robot.wait(timeout=10)
        if not self.health()['installed']: raise RuntimeError('尚未安裝本機 OpenRPA runtime；請執行離線 runtime 建置/匯入')
        # OpenRPA's upstream settings resolution prefers existing Documents/AppData profiles.
        # Do not risk opening or modifying another OpenRPA installation.
        if os.name == 'nt':
            import ctypes
            buf = ctypes.create_unicode_buffer(32768)
            ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)
            candidates = [Path(buf.value) / 'OpenRPA/settings.json', Path(os.environ.get('APPDATA', '')) / 'OpenRPA/settings.json']
            if any(p.exists() for p in candidates):
                raise RuntimeError('偵測到既有 OpenRPA profile；為避免覆寫，請使用獨立 Windows 帳號或先完成 profile 遷移')
            import winreg
            for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
                try:
                    with winreg.OpenKey(hive, r'SOFTWARE\OpenRPA') as key:
                        if winreg.QueryInfoKey(key)[1]: raise RuntimeError('既有 OpenRPA 登錄設定可能覆蓋離線設定，請先完成隔離部署')
                except FileNotFoundError: pass
        try:
            self._ipc('ping', timeout=2)
        except Exception:
            pass
        else:
            raise RuntimeError('另一個 OpenRPA 已佔用此 Windows session；請關閉後再執行')
        profile = self._profile(dep)
        si = None
        if os.name == 'nt':
            si = subprocess.STARTUPINFO(); si.dwFlags |= subprocess.STARTF_USESHOWWINDOW; si.wShowWindow = 0
        with (profile / 'startup.log').open('ab') as log:
            self.robot = subprocess.Popen([str(self.binaries / 'OpenRPA.exe'), '/workingdir', str(profile)],
                                          cwd=profile, stdout=log, stderr=log, startupinfo=si)
        self.robot_deployment = dep['id']
        for _ in range(90):
            if self.stopping or (cancel_event and cancel_event.is_set()):
                raise InterruptedError('OpenRPA 啟動已中止')
            if self.robot.poll() is not None: raise RuntimeError('OpenRPA 啟動失敗，請查看本機診斷')
            try:
                self._ipc('ping', timeout=2)
                return  # Invocation itself waits until OpenRPA is ready for action.
            except Exception: time.sleep(1)
        raise RuntimeError('OpenRPA 啟動逾時')

    def _run(self, run_id, dep, inputs):
        event = self.cancellations[run_id]
        proc = None
        started = False
        try:
            if event.is_set() or self.stopping:
                self._state(run_id, 'cancelled'); return
            if self.quarantined:
                self._state(run_id, 'blocked', {'error': '前一個桌面執行狀態不明，本工作未啟動；請解除暫停後重新提出執行'})
                return
            self._state(run_id, 'starting')
            self._ensure_robot(dep, event)
            if event.is_set(): self._state(run_id, 'cancelled'); return
            self._state(run_id, 'running')
            proc = subprocess.Popen([str(self.binaries / 'LocalOpenRpaBridge.exe'), 'run', dep['id']],
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            started = True
            deadline = time.monotonic() + 120
            payload = json.dumps(inputs).encode()
            cancelling = False
            while True:
                try:
                    stdout, _ = proc.communicate(payload, timeout=0.3)
                    break
                except subprocess.TimeoutExpired:
                    payload = None
                    if event.is_set() and not cancelling:
                        cancelling = True
                        self._state(run_id, 'cancel_requested')
                        self._ipc('cancel', dep['id'])
                        deadline = min(deadline, time.monotonic() + 10)
                    if time.monotonic() > deadline:
                        self._pause()
                        self._state(run_id, 'unknown', {'error': '執行或取消逾時，無法確認桌面狀態；不自動重跑'})
                        return
            data = json.loads(stdout.decode('utf-8-sig').strip())
            succeeded = proc.returncode == 0 and data.get('status') == 'succeeded'
            was_cancelled = cancelling and 'Killed remotely by killworkflows command' in str(data.get('error', ''))
            state = 'succeeded' if succeeded else ('cancelled' if was_cancelled else 'failed')
            data.pop('status', None)
            self._state(run_id, state, data)
        except InterruptedError:
            self._state(run_id, 'cancelled')
        except Exception as exc:
            if started: self._pause()
            self._state(run_id, 'unknown' if started else 'failed', {'error': str(exc)[:2000]})
        finally:
            if proc is not None and proc.poll() is None:
                proc.kill(); proc.wait()
            with self.mutex: self.cancellations.pop(run_id, None)

    def close(self):
        self.stopping = True
        for event in list(self.cancellations.values()): event.set()
        self.pool.shutdown(wait=True)
        if self.robot is not None and self.robot.poll() is None:
            self.robot.terminate(); self.robot.wait(timeout=10)
        self.db.close()


def broker_app(runtime: AutomationRuntime):
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    async def endpoint(request):
        import hmac
        if not hmac.compare_digest(request.headers.get('authorization', ''), 'Bearer ' + runtime.token):
            return JSONResponse({'error': 'Unauthorized'}, status_code=401)
        if request.headers.get('origin') or request.url.hostname not in {'127.0.0.1', 'localhost'}:
            return JSONResponse({'error': 'Origin/Host rejected'}, status_code=403)
        try:
            path = request.url.path
            if path == '/v1/health': return JSONResponse(runtime.health())
            if request.method == 'POST' and path == '/v1/runs':
                raw = bytearray()
                async for chunk in request.stream():
                    raw.extend(chunk)
                    if len(raw) > 120000: raise ValueError('Request too large')
                body = json.loads(raw)
                return JSONResponse(runtime.submit(body['deployment_id'], body.get('input', {}), body['idempotency_key']), status_code=202)
            ident = request.path_params['run_id']
            if request.method == 'POST': return JSONResponse(runtime.cancel(ident))
            return JSONResponse(runtime.get_run(ident))
        except PermissionError as exc: return JSONResponse({'error': str(exc)}, status_code=403)
        except (ValueError, KeyError) as exc: return JSONResponse({'error': str(exc)}, status_code=400)
        except Exception as exc: return JSONResponse({'error': str(exc)}, status_code=503)
    return Starlette(routes=[Route('/v1/health', endpoint), Route('/v1/runs', endpoint, methods=['POST']),
                             Route('/v1/runs/{run_id}', endpoint), Route('/v1/runs/{run_id}/cancel', endpoint, methods=['POST'])])
