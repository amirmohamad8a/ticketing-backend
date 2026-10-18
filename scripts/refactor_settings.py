"""Shared helpers for the refactor settings snapshot/compare scripts.

The snapshot captures ``manage.py diffsettings --all`` for every settings
module.  The compare script re-runs the same capture in memory and diffs it
against the saved snapshot.  Keeping the environment in one place means both
scripts always use exactly the same inputs.

The production values below are the same throwaway values the CI deploy check
uses in ``.github/workflows/ci.yml``.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_DIR = ROOT / ".refactor" / "settings"

BASE_ENVIRONMENT = {
    "SECRET_KEY": "refactor-settings-snapshot-secret-key",
    "JWT_SIGNING_KEY": "refactor-settings-snapshot-jwt-signing-key",
    "DEBUG": "True",
    "ALLOWED_HOSTS": "localhost,127.0.0.1",
    "DATABASE_URL": "postgres://ticketing:ticketing@localhost:5432/ticketing",
    "REDIS_URL": "redis://localhost:6379/0",
    "NUM_PROXIES": "0",
    "STORAGE_BACKEND": "local",
    "LOG_LEVEL": "INFO",
    "METRICS_TOKEN": "",
    "WIDGET_POW_DIFFICULTY": "0",
}

PROD_ENVIRONMENT = {
    "SECRET_KEY": "ci-deploy-check-secret-key-0123456789-abcdefghijklmnopqrstuvwxyz",
    "JWT_SIGNING_KEY": "ci-deploy-check-jwt-signing-key-9876543210-zyxwvutsrqponmlk",
    "ALLOWED_HOSTS": "support.example.com",
    "DATABASE_URL": "postgres://ticketing:ticketing@localhost:5432/ticketing",
    "NUM_PROXIES": "1",
    "REDIS_URL": "redis://localhost:6379/0",
    "STORAGE_BACKEND": "local",
    "LOG_LEVEL": "INFO",
    "METRICS_TOKEN": "",
}

SETTINGS_MODULES = ("config.settings.dev", "config.settings.test", "config.settings.prod")


def _environment(settings_module):
    environment = os.environ.copy()
    environment.update(BASE_ENVIRONMENT)
    if settings_module == "config.settings.prod":
        environment.update(PROD_ENVIRONMENT)
    environment["DJANGO_SETTINGS_MODULE"] = settings_module
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    return environment


def capture(settings_module):
    """Return the ``diffsettings --all`` output for one settings module."""
    process = subprocess.run(
        [sys.executable, str(ROOT / "manage.py"), "diffsettings", "--all"],
        cwd=ROOT,
        env=_environment(settings_module),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    if process.returncode != 0:
        raise RuntimeError(
            f"diffsettings failed for {settings_module} (exit {process.returncode}):\n"
            f"{process.stderr}"
        )
    return process.stdout


def snapshot_path(settings_module):
    return SNAPSHOT_DIR / f"{settings_module}.txt"


def capture_all():
    return {module: capture(module) for module in SETTINGS_MODULES}
