"""Демоданные: организатор, восемь участников, набор «Осенний хакатон» с двумя командами.

Повторный запуск ничего не дублирует: записи ищутся по естественным ключам
(логин, название набора, команда в наборе, роль в команде, отклик участника на набор).
--reset дополнительно возвращает демо к исходному виду: все в очереди, набор открыт, слоты по умолчанию,
остальные наборы удалены. Только для демо-базы.

Запуск: python -m app.seed [--reset]
"""
from __future__ import annotations

import json
import sqlite3
import sys

from .auth import hash_password
from .db import connect, migrate, now_iso, write_tx

DEMO_PASSWORD_ORG = "organizer-demo"
DEMO_PASSWORD_PARTICIPANT = "participant-demo"
DEMO_TITLE = "Осенний хакатон"

# (логин, отображаемое имя, роль)
DEMO_USERS: list[tuple[str, str, str]] = [
    ("organizer", "Ольга Организаторова", "organizer"),
    ("p1", "Антон Белов", "participant"),
    ("p2", "Вика Гусева", "participant"),
    ("p3", "Денис Егоров", "participant"),
    ("p4", "Женя Зуева", "participant"),
    ("p5", "Илья Ковалёв", "participant"),
    ("p6", "Лена Морозова", "participant"),
    ("p7", "Никита Орлов", "participant"),
    ("p8", "Полина Руднева", "participant"),
]

TEAMS: list[tuple[str, list[tuple[str, int]]]] = [
    ("Альфа", [("Backend", 1), ("Frontend", 1), ("Дизайн", 1)]),
    ("Бета", [("Backend", 1), ("Frontend", 1), ("Аналитик", 1)]),
]

# логин → (навыки, интересы, желаемые роли)
APPLICATIONS: dict[str, tuple[list[str], str, list[str]]] = {
    "p1": (["Python", "FastAPI", "SQL"], "финтех, API", ["Backend"]),
    "p2": (["React", "TypeScript", "CSS"], "интерфейсы, доступность", ["Frontend"]),
    "p3": (["Figma", "UX-исследования"], "мобильные приложения", ["Дизайн"]),
    "p4": (["Python", "pandas", "SQL"], "аналитика продукта", ["Аналитик", "Backend"]),
    "p5": (["Go", "PostgreSQL", "Docker"], "инфраструктура", ["Backend"]),
    "p6": (["Vue", "TypeScript"], "образование", ["Frontend"]),
    "p7": (["Kotlin", "Android"], "мобильные приложения", ["Frontend", "Backend"]),
    "p8": (["Figma", "иллюстрация"], "игры", ["Дизайн"]),
}


def seed(conn: sqlite3.Connection, reset: bool = False) -> dict[str, int]:
    migrate(conn)
    with write_tx(conn):
        ids: dict[str, int] = {}
        for username, name, role in DEMO_USERS:
            row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            if row is None:
                pwd = DEMO_PASSWORD_ORG if role == "organizer" else DEMO_PASSWORD_PARTICIPANT
                h, salt = hash_password(pwd)
                cur = conn.execute(
                    "INSERT INTO users (username, display_name, role, password_hash, salt) VALUES (?, ?, ?, ?, ?)",
                    (username, name, role, h, salt),
                )
                ids[username] = int(cur.lastrowid or 0)
            else:
                ids[username] = int(row["id"])
        org = ids["organizer"]
        rec = conn.execute("SELECT id FROM recruitments WHERE title = ? AND organizer_id = ?", (DEMO_TITLE, org)).fetchone()
        if rec is None:
            rid = int(
                conn.execute(
                    "INSERT INTO recruitments (title, description, status, organizer_id, created_at) VALUES (?, ?, 'open', ?, ?)",
                    (DEMO_TITLE, "Две команды по три роли. Демо-набор: все данные вымышленные.", org, now_iso()),
                ).lastrowid
                or 0
            )
        else:
            rid = int(rec["id"])
        if reset:
            # Наборы, созданные поверх демо, удаляются целиком: сброс возвращает демо к исходному виду.
            conn.execute(
                "DELETE FROM assignments WHERE application_id IN (SELECT a.id FROM applications a JOIN recruitments r ON r.id = a.recruitment_id WHERE r.id <> ?)",
                (rid,),
            )
            conn.execute("DELETE FROM recruitments WHERE id <> ?", (rid,))
            conn.execute(
                "DELETE FROM assignments WHERE application_id IN (SELECT id FROM applications WHERE recruitment_id = ?)", (rid,)
            )
            conn.execute("UPDATE recruitments SET status = 'open' WHERE id = ?", (rid,))
            # Отклики, созданные не демо-участниками, и лишние команды убираем.
            demo_ids = [ids[u] for u, _, r in DEMO_USERS if r == "participant"]
            conn.execute(
                f"DELETE FROM applications WHERE recruitment_id = ? AND user_id NOT IN ({','.join('?' * len(demo_ids))})",
                (rid, *demo_ids),
            )
            names = [t[0] for t in TEAMS]
            conn.execute(f"DELETE FROM teams WHERE recruitment_id = ? AND name NOT IN ({','.join('?' * len(names))})", (rid, *names))
        for pos, (team, slots) in enumerate(TEAMS):
            t = conn.execute("SELECT id FROM teams WHERE recruitment_id = ? AND name = ?", (rid, team)).fetchone()
            tid = int(t["id"]) if t else int(conn.execute("INSERT INTO teams (recruitment_id, name, position) VALUES (?, ?, ?)", (rid, team, pos)).lastrowid or 0)
            if reset:
                roles = [r for r, _ in slots]
                conn.execute(f"DELETE FROM role_slots WHERE team_id = ? AND role NOT IN ({','.join('?' * len(roles))})", (tid, *roles))
            for spos, (role, cap) in enumerate(slots):
                s = conn.execute("SELECT id FROM role_slots WHERE team_id = ? AND role = ?", (tid, role)).fetchone()
                if s is None:
                    conn.execute("INSERT INTO role_slots (team_id, role, capacity, position) VALUES (?, ?, ?, ?)", (tid, role, cap, spos))
                elif reset:
                    conn.execute("UPDATE role_slots SET capacity = ?, position = ? WHERE id = ?", (cap, spos, s["id"]))
        for i, (username, (skills, interests, roles)) in enumerate(APPLICATIONS.items()):
            uid = ids[username]
            name = next(n for u, n, _ in DEMO_USERS if u == username)
            conn.execute(
                "INSERT INTO profiles (user_id, name, skills, interests) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(user_id) DO " + ("UPDATE SET name = excluded.name, skills = excluded.skills, interests = excluded.interests" if reset else "NOTHING"),
                (uid, name, json.dumps(skills, ensure_ascii=False), interests),
            )
            # Фиксированное время создания: порядок очереди одинаковый при каждом запуске.
            conn.execute(
                "INSERT INTO applications (recruitment_id, user_id, desired_roles, created_at) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(recruitment_id, user_id) DO " + ("UPDATE SET desired_roles = excluded.desired_roles, note = ''" if reset else "NOTHING"),
                (rid, uid, json.dumps(roles, ensure_ascii=False), f"2026-11-01T10:{i:02d}:00+00:00"),
            )
        if reset:
            conn.execute("UPDATE applications SET assignment_version = assignment_version + 1 WHERE recruitment_id = ?", (rid,))
        conn.execute("UPDATE recruitments SET board_version = board_version + 1 WHERE id = ?", (rid,))
    counts = {
        t: int(conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"])
        for t in ("users", "recruitments", "teams", "role_slots", "applications", "assignments")
    }
    return counts


def main(argv: list[str]) -> int:
    conn = connect()
    try:
        counts = seed(conn, reset="--reset" in argv)
    finally:
        conn.close()
    print("Демоданные готовы:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print(f"Вход: organizer / {DEMO_PASSWORD_ORG}; участники p1…p8 / {DEMO_PASSWORD_PARTICIPANT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
