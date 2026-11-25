"""Повтор действий, чужие права, перезапуск сервера с той же базой."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

from tests.conftest import BACKEND, free_port, login
from tests.test_api import card, demo_board, slot


def test_retry_after_lost_response_is_idempotent(client: httpx.Client) -> None:
    """Ответ потерян, клиент повторяет тот же запрос со старой версией: результат уже достигнут — 200 без изменений."""
    h = login(client, "organizer")
    b = demo_board(client, h)
    anton = card(b, "Антон Белов")
    target = slot(b, "Альфа", "Backend")["id"]
    first = client.put(f"/api/applications/{anton['id']}/assignment", json={"slot_id": target, "version": anton["version"]}, headers=h)
    assert first.status_code == 200 and first.json()["changed"] is True
    retry = client.put(f"/api/applications/{anton['id']}/assignment", json={"slot_id": target, "version": anton["version"]}, headers=h)
    assert retry.status_code == 200 and retry.json()["changed"] is False
    # Но перенос в другое место по старой версии по-прежнему запрещён.
    other = slot(b, "Бета", "Backend")["id"]
    stale = client.put(f"/api/applications/{anton['id']}/assignment", json={"slot_id": other, "version": anton["version"]}, headers=h)
    assert stale.status_code == 409 and stale.json()["code"] == "version_conflict"
    # То же для возврата в очередь.
    v = card(first.json()["board"], "Антон Белов")["version"]
    assert client.delete(f"/api/applications/{anton['id']}/assignment", params={"version": v}, headers=h).json()["changed"] is True
    again = client.delete(f"/api/applications/{anton['id']}/assignment", params={"version": v}, headers=h)
    assert again.status_code == 200 and again.json()["changed"] is False


def test_other_organizer_cannot_touch_board(client: httpx.Client, db_file) -> None:
    from app.auth import hash_password
    from app.db import connect

    conn = connect(str(db_file))
    hp, salt = hash_password("pw-org2")
    conn.execute("INSERT INTO users (username, display_name, role, password_hash, salt) VALUES ('org2', 'Второй', 'organizer', ?, ?)", (hp, salt))
    conn.close()
    org = login(client, "organizer")
    b = demo_board(client, org)
    rid = b["recruitment"]["id"]
    org2 = login(client, "org2", "pw-org2")
    assert client.get(f"/api/recruitments/{rid}/board", headers=org2).status_code == 403
    anton = card(b, "Антон Белов")
    r = client.put(f"/api/applications/{anton['id']}/assignment", json={"slot_id": slot(b, "Альфа", "Backend")["id"], "version": anton["version"]}, headers=org2)
    assert r.status_code == 403
    assert client.patch(f"/api/recruitments/{rid}", json={"status": "closed"}, headers=org2).status_code == 403
    assert client.get("/api/recruitments", headers=org2).json()["recruitments"] == []


def test_restart_with_existing_database(tmp_path: Path) -> None:
    """Сервер перезапускается на той же базе: миграции не повторяются, сид не дублирует, состав сохраняется."""
    db = tmp_path / "persist.sqlite3"
    env = {**os.environ, "DB_PATH": str(db), "SEED_DEMO": "1", "DEMO_MODE": "1", "STATIC_DIR": str(tmp_path / "none")}

    def start() -> tuple[subprocess.Popen[bytes], str]:
        port = free_port()
        proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"], cwd=BACKEND, env=env)
        base = f"http://127.0.0.1:{port}"
        for _ in range(100):
            try:
                if httpx.get(f"{base}/api/health", timeout=1).status_code == 200:
                    return proc, base
            except httpx.HTTPError:
                time.sleep(0.1)
        raise RuntimeError("не поднялся")

    proc, base = start()
    try:
        c = httpx.Client(base_url=base)
        h = login(c, "organizer")
        b = demo_board(c, h)
        anton = card(b, "Антон Белов")
        c.put(f"/api/applications/{anton['id']}/assignment", json={"slot_id": slot(b, "Альфа", "Backend")["id"], "version": anton["version"]}, headers=h)
    finally:
        proc.terminate()
        proc.wait(timeout=10)
    proc, base = start()
    try:
        c = httpx.Client(base_url=base)
        h = login(c, "organizer")  # старая сессия тоже жива, но вход проверяет и пароли после перезапуска
        b = demo_board(c, h)
        assert slot(b, "Альфа", "Backend")["members"][0]["name"] == "Антон Белов"
        assert len(b["queue"]) == 7
        health = c.get("/api/health").json()
        assert health["schema_version"] == 1
        assert len(c.get("/api/recruitments", headers=h).json()["recruitments"]) == 1
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def test_users_cli(tmp_path: Path) -> None:
    db = tmp_path / "cli.sqlite3"
    env = {**os.environ, "DB_PATH": str(db)}
    run = lambda *a, inp="": subprocess.run([sys.executable, "-m", "app.users", *a], cwd=BACKEND, env=env, input=inp, capture_output=True, text=True)  # noqa: E731
    r = run("add", "Maria", "--role", "organizer", "--name", "Мария", "--password-stdin", inp="long-password\n")
    assert r.returncode == 0, r.stderr
    assert run("add", "maria", "--role", "participant", "--name", "Дубль", "--password-stdin", inp="long-password\n").returncode != 0
    assert run("add", "p", "--role", "participant", "--name", "Коротко", "--password-stdin", inp="short\n").returncode != 0
    assert "organizer    maria" in run("list").stdout
    assert run("passwd", "maria", "--password-stdin", inp="another-password\n").returncode == 0
    from app.auth import login as do_login
    from app.db import connect

    conn = connect(str(db))
    assert do_login(conn, "maria", "long-password") is None
    assert do_login(conn, "maria", "another-password") is not None
    conn.close()
