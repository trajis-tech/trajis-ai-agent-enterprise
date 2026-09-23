from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import time
from pathlib import Path

from .atomic import atomic_write_text
from .n8n_client import N8nClient, N8nSession, N8nStatus


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex((host, port)) == 0


def ensure_encryption_key(secrets_dir: Path) -> str:
    secrets_dir.mkdir(parents=True, exist_ok=True)
    path = secrets_dir / "n8n_encryption_key.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    key = secrets.token_hex(24)
    atomic_write_text(path, key)
    return key


def load_api_key(secrets_dir: Path) -> str | None:
    path = secrets_dir / "n8n_api_key.txt"
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        return text or None
    return None


def save_api_key(secrets_dir: Path, key: str) -> None:
    atomic_write_text(secrets_dir / "n8n_api_key.txt", key.strip())


def find_n8n_entry(n8n_root: Path) -> Path | None:
    candidates = [
        n8n_root / "node_modules" / "n8n" / "bin" / "n8n",
        n8n_root / "bin" / "n8n",
        n8n_root / "n8n",
    ]
    for item in candidates:
        if item.exists():
            return item
    return None


def start_n8n(
    *,
    node_exe: Path,
    n8n_root: Path,
    data_dir: Path,
    secrets_dir: Path,
    host: str,
    port: int,
    pid_path: Path,
    automation_port: int = 8771,
) -> N8nStatus:
    url = f"http://{host}:{port}"
    if not node_exe.exists():
        return N8nStatus(False, "node.exe missing", url)
    entry = find_n8n_entry(n8n_root)
    if entry is None:
        return N8nStatus(False, "n8n runtime bundle missing", url)
    if port_in_use(host, port) and not _pid_alive(pid_path):
        return N8nStatus(False, f"port {port} occupied", url)
    if _pid_alive(pid_path) and not port_in_use(host, port):
        stop_n8n(pid_path)
    if _pid_alive(pid_path) and port_in_use(host, port):
        return N8nStatus(True, None, url)

    data_dir.mkdir(parents=True, exist_ok=True)
    from .automation_runtime import service_token
    service_token(secrets_dir / "openrpa_service_token.txt")
    key = ensure_encryption_key(secrets_dir)
    env = os.environ.copy()
    env.update(
        {
            "N8N_CUSTOM_EXTENSIONS": str(Path(__file__).resolve().parents[1] / "integrations" / "n8n"),
            "LOCAL_OPENRPA_URL": f"http://127.0.0.1:{automation_port}",
            "LOCAL_OPENRPA_TOKEN_FILE": str(secrets_dir / "openrpa_service_token.txt"),
            "N8N_HOST": host,
            "N8N_PATH": "/n8n/",
            "N8N_PROXY_HOPS": "1",
            "N8N_PORT": str(port),
            "N8N_LISTEN_ADDRESS": host,
            "N8N_PROTOCOL": "http",
            "N8N_USER_FOLDER": str(data_dir),
            "N8N_ENCRYPTION_KEY": key,
            "N8N_DIAGNOSTICS_ENABLED": "false",
            "N8N_PERSONALIZATION_ENABLED": "false",
            "N8N_VERSION_NOTIFICATIONS_ENABLED": "false",
            "N8N_TEMPLATES_ENABLED": "false",
            "N8N_DISABLED_MODULES": "mcp-registry,community-packages",
            "N8N_HIRING_BANNER_ENABLED": "false",
            "N8N_ONBOARDING_FLOW_DISABLED": "true",
            "N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS": "false",
            "N8N_RUNNERS_ENABLED": "false",
            "NODES_EXCLUDE": '["n8n-nodes-base.code"]',
            "N8N_SECURE_COOKIE": "false",
        }
    )
    log = (data_dir / "startup.log").open("ab")
    try:
        proc = subprocess.Popen(
            [str(node_exe), str(entry)],
            cwd=str(n8n_root),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if sys_is_windows() else 0,
        )
    except OSError as exc:
        return N8nStatus(False, f"failed to start n8n: {exc}", url)
    finally:
        log.close()
    atomic_write_text(pid_path, str(proc.pid))
    deadline = time.time() + 120
    client = N8nClient(url, load_api_key(secrets_dir))
    while time.time() < deadline:
        if proc.poll() is not None:
            return N8nStatus(False, "n8n process crashed", url)
        if client.health():
            return N8nStatus(True, None if load_api_key(secrets_dir) else "請完成 n8n 帳號設定並儲存 API Key", url)
        time.sleep(0.5)
    return N8nStatus(False, "n8n startup timeout; see n8n_data/startup.log", url)


def ensure_owner_and_api_key(url: str, secrets_dir: Path) -> str:
    existing = load_api_key(secrets_dir)
    if existing:
        return existing
    pwd_path = secrets_dir / "n8n_owner_password.txt"
    email = "local-agent@localhost.local"
    if pwd_path.exists():
        password = pwd_path.read_text(encoding="utf-8").strip()
    else:
        password = secrets.token_urlsafe(18) + "Aa1!"
        atomic_write_text(pwd_path, password)
    atomic_write_text(secrets_dir / "n8n_owner.json", json.dumps({"email": email}, indent=2))
    session = N8nSession(url)
    try:
        session.request(
            "POST",
            "/rest/owner/setup",
            {
                "email": email,
                "firstName": "Local",
                "lastName": "Agent",
                "password": password,
            },
        )
    except RuntimeError as exc:
        if "HTTP 400" not in str(exc) and "HTTP 409" not in str(exc):
            raise
    session.request("POST", "/rest/login", {"emailOrLdapLoginId": email, "password": password, "email": email})
    created = session.request("POST", "/rest/api-keys", {"label": "portable-agent"})
    key = ""
    if isinstance(created, dict):
        key = str(created.get("rawApiKey") or created.get("apiKey") or created.get("key") or "")
        if not key and isinstance(created.get("data"), dict):
            key = str(created["data"].get("rawApiKey") or created["data"].get("apiKey") or "")
    if not key:
        raise RuntimeError("n8n API key missing from setup response")
    save_api_key(secrets_dir, key)
    return key


def stop_n8n(pid_path: Path) -> None:
    if not pid_path.exists():
        return
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        pid_path.unlink(missing_ok=True)
        return
    if sys_is_windows():
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        try:
            os.kill(pid, 15)
        except OSError:
            pass
    pid_path.unlink(missing_ok=True)


def cleanup_stale_pid(pid_path: Path) -> None:
    if pid_path.exists() and not _pid_alive(pid_path):
        pid_path.unlink(missing_ok=True)


def _pid_alive(pid_path: Path) -> bool:
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text(encoding="utf-8").strip())
    except ValueError:
        return False
    if sys_is_windows():
        result = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True)
        return str(pid) in (result.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def sys_is_windows() -> bool:
    import sys

    return sys.platform == "win32"
