from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture()
def db_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "test.sqlite3"
    monkeypatch.setenv("DB_PATH", str(path))
    monkeypatch.setenv("SEED_DEMO", "1")
    monkeypatch.setenv("DEMO_MODE", "1")
    monkeypatch.setenv("STATIC_DIR", str(tmp_path / "no-static"))
    return path


@pytest.fixture()
def client(db_file: Path) -> Iterator[httpx.Client]:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def login(c: httpx.Client, username: str, password: str | None = None) -> dict[str, str]:
    from app.seed import DEMO_PASSWORD_ORG, DEMO_PASSWORD_PARTICIPANT

    pwd = password or (DEMO_PASSWORD_ORG if username == "organizer" else DEMO_PASSWORD_PARTICIPANT)
    r = c.post("/api/auth/login", json={"username": username, "password": pwd})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture()
def live_server(tmp_path: Path) -> Iterator[str]:
    """Настоящий uvicorn в отдельном процессе: для проверки параллельных запросов и перезапуска."""
    port = free_port()
    env = {**os.environ, "DB_PATH": str(tmp_path / "live.sqlite3"), "SEED_DEMO": "1", "DEMO_MODE": "1", "STATIC_DIR": str(tmp_path / "none")}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND,
        env=env,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        else:
            raise RuntimeError("сервер не поднялся")
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=10)
