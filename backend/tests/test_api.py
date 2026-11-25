from __future__ import annotations

import sqlite3

import httpx

from tests.conftest import login


def demo_board(c: httpx.Client, h: dict[str, str]) -> dict:
    rid = c.get("/api/recruitments", headers=h).json()["recruitments"][0]["id"]
    return c.get(f"/api/recruitments/{rid}/board", headers=h).json()


def slot(board: dict, team: str, role: str) -> dict:
    t = next(t for t in board["teams"] if t["name"] == team)
    return next(s for s in t["slots"] if s["role"] == role)


def card(board: dict, name: str) -> dict:
    for c in board["queue"]:
        if c["name"] == name:
            return c
    for t in board["teams"]:
        for s in t["slots"]:
            for m in s["members"]:
                if m["name"] == name:
                    return m
    raise KeyError(name)


def assign(c: httpx.Client, h: dict[str, str], board: dict, name: str, team: str, role: str) -> httpx.Response:
    cd = card(board, name)
    return c.put(f"/api/applications/{cd['id']}/assignment", json={"slot_id": slot(board, team, role)["id"], "version": cd["version"]}, headers=h)


def test_health_and_migrations(client: httpx.Client, db_file) -> None:
    r = client.get("/api/health")
    assert r.json() == {"status": "ok", "schema_version": 1, "demo": True}
    from app.db import connect, migrate

    conn = connect(str(db_file))
    assert migrate(conn) == 1  # повторная миграция ничего не меняет
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1
    conn.close()


def test_seed_is_idempotent(client: httpx.Client, db_file) -> None:
    from app.db import connect
    from app.seed import seed

    conn = connect(str(db_file))
    first = seed(conn)
    second = seed(conn)
    assert first == second == {"users": 9, "recruitments": 1, "teams": 2, "role_slots": 6, "applications": 8, "assignments": 0}
    conn.close()


def test_auth_required_and_bad_password(client: httpx.Client) -> None:
    assert client.get("/api/me").status_code == 401
    r = client.post("/api/auth/login", json={"username": "organizer", "password": "wrong"})
    assert r.status_code == 401 and r.json()["code"] == "bad_credentials"
    h = login(client, "organizer")
    assert client.get("/api/me", headers=h).json()["user"]["role"] == "organizer"
    # cookie-сессия тоже работает
    client.post("/api/auth/login", json={"username": "p1", "password": "participant-demo"})
    assert client.get("/api/me").json()["user"]["username"] == "p1"
    client.post("/api/auth/logout")
    assert client.get("/api/me").status_code == 401


def test_participant_sees_only_own_result(client: httpx.Client) -> None:
    org = login(client, "organizer")
    b = demo_board(client, org)
    rid = b["recruitment"]["id"]
    p1 = login(client, "p1")
    assert client.get(f"/api/recruitments/{rid}/board", headers=p1).status_code == 403
    cd = card(b, "Антон Белов")
    r = client.put(f"/api/applications/{cd['id']}/assignment", json={"slot_id": slot(b, "Альфа", "Backend")["id"], "version": 0}, headers=p1)
    assert r.status_code == 403
    assert client.get(f"/api/recruitments/{rid}/my", headers=p1).json()["assignment"] is None
    assert assign(client, org, b, "Антон Белов", "Альфа", "Backend").status_code == 200
    my = client.get(f"/api/recruitments/{rid}/my", headers=p1).json()
    assert my["assignment"] == {"team": "Альфа", "role": "Backend"}


def test_acceptance_two_teams_one_open_move_and_repeat_forbidden(client: httpx.Client) -> None:
    """ТЗ: восемь кандидатов, две команды, одна роль открыта, перенос, повторное назначение запрещено."""
    org = login(client, "organizer")
    b = demo_board(client, org)
    assert len(b["queue"]) == 8
    plan = [
        ("Антон Белов", "Альфа", "Backend"),
        ("Вика Гусева", "Альфа", "Frontend"),
        ("Денис Егоров", "Альфа", "Дизайн"),
        ("Илья Ковалёв", "Бета", "Backend"),
        ("Лена Морозова", "Бета", "Frontend"),
    ]
    for name, team, role in plan:
        r = assign(client, org, b, name, team, role)
        assert r.status_code == 200, r.text
        b = r.json()["board"]
    assert b["summary"]["filled"] == 5
    assert b["summary"]["open_slots"] == [{"slot_id": slot(b, "Бета", "Аналитик")["id"], "team": "Бета", "role": "Аналитик", "free": 1}]
    assert len(b["queue"]) == 3

    # Перенос: Илья из Бета/Backend в Альфа/Backend невозможен — там Антон; сначала Антона в очередь.
    r = assign(client, org, b, "Илья Ковалёв", "Альфа", "Backend")
    assert r.status_code == 409 and r.json()["code"] == "slot_full"
    b = r.json()["board"]
    anton = card(b, "Антон Белов")
    r = client.delete(f"/api/applications/{anton['id']}/assignment", params={"version": anton["version"]}, headers=org)
    assert r.status_code == 200
    b = r.json()["board"]
    ilya_before = card(b, "Илья Ковалёв")
    r = assign(client, org, b, "Илья Ковалёв", "Альфа", "Backend")
    assert r.status_code == 200
    b = r.json()["board"]
    assert slot(b, "Альфа", "Backend")["members"][0]["name"] == "Илья Ковалёв"
    assert slot(b, "Бета", "Backend")["taken"] == 0  # прежнее место освобождено в той же транзакции
    assert card(b, "Илья Ковалёв")["version"] == ilya_before["version"] + 1

    # Повторное назначение того же человека по устаревшей версии запрещено.
    r = client.put(
        f"/api/applications/{ilya_before['id']}/assignment",
        json={"slot_id": slot(b, "Бета", "Backend")["id"], "version": ilya_before["version"]},
        headers=org,
    )
    assert r.status_code == 409 and r.json()["code"] == "version_conflict"
    assert slot(r.json()["board"], "Альфа", "Backend")["members"][0]["name"] == "Илья Ковалёв"
    # Второй отклик того же человека тоже запрещён.
    rid = b["recruitment"]["id"]
    r = client.post(f"/api/recruitments/{rid}/applications", json={"name": "Илья", "desired_roles": ["Backend"]}, headers=login(client, "p5"))
    assert r.status_code == 409 and r.json()["code"] == "duplicate_application"
    # Антон вернулся в очередь, Илья перенесён: в командах четыре человека, у каждого одно место.
    names = [m["name"] for t in b["teams"] for s in t["slots"] for m in s["members"]]
    assert sorted(names) == sorted(["Вика Гусева", "Денис Егоров", "Лена Морозова", "Илья Ковалёв"])
    assert len(names) == len(set(names))


def test_move_inside_team_and_same_slot_is_noop(client: httpx.Client) -> None:
    org = login(client, "organizer")
    b = demo_board(client, org)
    b = assign(client, org, b, "Никита Орлов", "Альфа", "Frontend").json()["board"]
    r = assign(client, org, b, "Никита Орлов", "Альфа", "Backend")
    b = r.json()["board"]
    assert slot(b, "Альфа", "Frontend")["taken"] == 0 and slot(b, "Альфа", "Backend")["taken"] == 1
    v = card(b, "Никита Орлов")["version"]
    r = assign(client, org, b, "Никита Орлов", "Альфа", "Backend")
    assert r.status_code == 200 and r.json()["changed"] is False
    assert card(r.json()["board"], "Никита Орлов")["version"] == v


def test_slot_from_other_recruitment_rejected(client: httpx.Client) -> None:
    org = login(client, "organizer")
    other = client.post("/api/recruitments", json={"title": "Другой набор"}, headers=org).json()
    other = client.post(f"/api/recruitments/{other['recruitment']['id']}/teams", json={"name": "Гамма"}, headers=org).json()
    other = client.post(f"/api/teams/{other['teams'][0]['id']}/slots", json={"role": "QA", "capacity": 1}, headers=org).json()
    b = demo_board(client, org)
    cd = card(b, "Антон Белов")
    r = client.put(f"/api/applications/{cd['id']}/assignment", json={"slot_id": other["teams"][0]["slots"][0]["id"], "version": cd["version"]}, headers=org)
    assert r.status_code == 422 and r.json()["code"] == "slot_not_in_recruitment"


def test_application_rules(client: httpx.Client) -> None:
    org = login(client, "organizer")
    rid = demo_board(client, org)["recruitment"]["id"]
    # новый участник регистрируется сидом? нет — используем организатора и существующих
    assert client.post(f"/api/recruitments/{rid}/applications", json={"name": "Оля"}, headers=org).status_code == 403
    p1 = login(client, "p1")
    r = client.post(f"/api/recruitments/{rid}/applications", json={"name": "", "desired_roles": []}, headers=p1)
    assert r.status_code == 422
    # закрытый набор
    client.patch(f"/api/recruitments/{rid}", json={"status": "closed"}, headers=org)
    b = demo_board(client, org)
    assert assign(client, org, b, "Антон Белов", "Альфа", "Backend").json()["code"] == "recruitment_closed"
    client.patch(f"/api/recruitments/{rid}", json={"status": "open"}, headers=org)


def test_new_participant_application_and_unknown_role(client: httpx.Client, db_file) -> None:
    from app.auth import hash_password
    from app.db import connect

    conn = connect(str(db_file))
    h, salt = hash_password("pw-new")
    conn.execute("INSERT INTO users (username, display_name, role, password_hash, salt) VALUES ('p9', 'Новый', 'participant', ?, ?)", (h, salt))
    conn.close()
    org = login(client, "organizer")
    rid = demo_board(client, org)["recruitment"]["id"]
    p9 = login(client, "p9", "pw-new")
    r = client.post(f"/api/recruitments/{rid}/applications", json={"name": "Яна", "skills": ["Rust", "rust", " "], "desired_roles": ["Тимлид"]}, headers=p9)
    assert r.status_code == 422 and r.json()["code"] == "unknown_roles"
    r = client.post(f"/api/recruitments/{rid}/applications", json={"name": " Яна ", "skills": ["Rust", "rust", " "], "desired_roles": ["Backend"]}, headers=p9)
    assert r.status_code == 201
    assert r.json()["application"]["skills"] == ["Rust"] and r.json()["application"]["name"] == "Яна"
    b = demo_board(client, org)
    assert len(b["queue"]) == 9 and "Rust" in b["skills"]


def test_structure_rules(client: httpx.Client) -> None:
    org = login(client, "organizer")
    b = demo_board(client, org)
    b = assign(client, org, b, "Антон Белов", "Альфа", "Backend").json()["board"]
    sid = slot(b, "Альфа", "Backend")["id"]
    r = client.patch(f"/api/slots/{sid}", json={"capacity": 2}, headers=org)
    assert slot(r.json(), "Альфа", "Backend")["free"] == 1
    assert client.delete(f"/api/slots/{sid}", headers=org).json()["code"] == "slot_not_empty"
    tid = next(t["id"] for t in b["teams"] if t["name"] == "Альфа")
    assert client.delete(f"/api/teams/{tid}", headers=org).json()["code"] == "team_not_empty"
    r = client.post(f"/api/teams/{tid}/slots", json={"role": "Backend", "capacity": 1}, headers=org)
    assert r.status_code == 409 and r.json()["code"] == "duplicate_slot"
    r = client.post(f"/api/teams/{tid}/slots", json={"role": "QA", "capacity": 0}, headers=org)
    assert r.status_code == 422


def test_capacity_cannot_drop_below_taken(client: httpx.Client) -> None:
    org = login(client, "organizer")
    b = demo_board(client, org)
    sid = slot(b, "Бета", "Frontend")["id"]
    client.patch(f"/api/slots/{sid}", json={"capacity": 2}, headers=org)
    b = demo_board(client, org)
    b = assign(client, org, b, "Вика Гусева", "Бета", "Frontend").json()["board"]
    b = assign(client, org, b, "Лена Морозова", "Бета", "Frontend").json()["board"]
    r = client.patch(f"/api/slots/{sid}", json={"capacity": 1}, headers=org)
    assert r.status_code == 409 and r.json()["code"] == "capacity_below_taken"


def test_export_csv(client: httpx.Client) -> None:
    org = login(client, "organizer")
    b = demo_board(client, org)
    assign(client, org, b, "Антон Белов", "Альфа", "Backend")
    r = client.get(f"/api/recruitments/{b['recruitment']['id']}/export.csv", headers=org)
    lines = r.text.lstrip("﻿").strip().split("\r\n")
    assert lines[0] == "team,role,name,skills,desired_roles"
    assert lines[1] == 'Альфа,Backend,Антон Белов,"Python, FastAPI, SQL",Backend'
    assert len(lines) == 1 + 6 + 7  # 6 мест (1 занято, 5 свободных) + 7 в очереди


def test_demo_reset(client: httpx.Client, db_file) -> None:
    org = login(client, "organizer")
    b = demo_board(client, org)
    assign(client, org, b, "Антон Белов", "Альфа", "Backend")
    assert client.post("/api/demo/reset", headers=login(client, "p1")).status_code == 403
    assert client.post("/api/demo/reset", headers=org).status_code == 200
    b = demo_board(client, org)
    assert len(b["queue"]) == 8 and b["summary"]["filled"] == 0
    conn = sqlite3.connect(db_file)
    assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 8
    conn.close()


def test_demo_reset_removes_extra_recruitments(client: httpx.Client) -> None:
    org = login(client, "organizer")
    client.post("/api/recruitments", json={"title": "Лишний"}, headers=org)
    assert len(client.get("/api/recruitments", headers=org).json()["recruitments"]) == 2
    client.post("/api/demo/reset", headers=org)
    assert [r["title"] for r in client.get("/api/recruitments", headers=org).json()["recruitments"]] == ["Осенний хакатон"]


def test_board_etag_and_304(client: httpx.Client) -> None:
    h = login(client, "organizer")
    rid = demo_board(client, h)["recruitment"]["id"]
    r = client.get(f"/api/recruitments/{rid}/board", headers=h)
    tag = r.headers["etag"]
    assert r.headers["cache-control"] == "private, no-cache"
    r2 = client.get(f"/api/recruitments/{rid}/board", headers={**h, "If-None-Match": tag})
    assert r2.status_code == 304 and r2.content == b""
    b = r.json()
    assign(client, h, b, "Антон Белов", "Альфа", "Backend")
    r3 = client.get(f"/api/recruitments/{rid}/board", headers={**h, "If-None-Match": tag})
    assert r3.status_code == 200 and r3.headers["etag"] != tag
    # Участнику 304 не выдаётся: права проверяются раньше
    assert client.get(f"/api/recruitments/{rid}/board", headers={**login(client, "p1"), "If-None-Match": r3.headers["etag"]}).status_code == 403
