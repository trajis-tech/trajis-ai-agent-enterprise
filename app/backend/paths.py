from __future__ import annotations

from pathlib import Path


def product_root() -> Path:
    return Path(__file__).resolve().parents[2]


def app_dir() -> Path:
    return product_root() / "app"


def config_dir() -> Path:
    return app_dir() / "config"


def filesystem_root() -> Path:
    return product_root() / "filesystem"


def system_root() -> Path:
    return filesystem_root() / "system"


def projects_root() -> Path:
    return filesystem_root() / "projects"


def runtime_root() -> Path:
    return filesystem_root() / ".runtime"


def portable_python() -> Path:
    return product_root() / "portable_python"


def lockfile_path() -> Path:
    return product_root() / "build.lock.json"


def policy_path() -> Path:
    return config_dir() / "policy.yaml"


def custom_api_path() -> Path:
    return config_dir() / "custom_api.json"


def manifests_path() -> Path:
    return system_root() / "manifests.json"
