"""Синтетический набор для замеров: N участников с откликами, команды по 5 ролей.

    python -m app.synthetic 100      # набор «Синтетика 100» в базе из DB_PATH

Повторный запуск с тем же N ничего не дублирует. Все имена вымышленные («Участник 001»).
"""
from __future__ import annotations

import json
import sqlite3
import sys

from .auth import hash_password
from .db import connect, migrate, now_iso, write_tx

ROLES = ["Backend", "Frontend", "Дизайн", "Аналитик", "QA"]
SKILLS = ["Python", "SQL", "React", "TypeScript", "Figma", "Go", "Docker", "pandas", "Kotlin", "UX"]
PASSWORD = "synthetic-demo"


def create(conn: sqlite3.Connection, n: int, organizer: str = "organizer") -> int:
    migrate(conn)
    title = f"Синтетика {n}"
    with write_tx(conn):
        org = conn.execute("SELECT id FROM users WHERE username = ?", (organizer,)).fetchone()
        if org is None:
            h, salt = hash_password("organizer-demo")
            org_id = int(conn.execute(
                "INSERT INTO users (username, display_name, role, password_hash, salt) VALUES (?, 'Организатор', 'organizer', ?, ?)",
                (organizer, h, salt),
            ).lastrowid or 0)
        else:
            org_id = int(org["id"])
        row = conn.execute("SELECT id FROM recruitments WHERE title = ? AND organizer_id = ?", (title, org_id)).fetchone()
        if row:
            return int(row["id"])
        rid = int(conn.execute(
            "INSERT INTO recruitments (title, description, status, organizer_id, created_at) VALUES (?, 'Синтетические данные для замеров', 'open', ?, ?)",
            (title, org_id, now_iso()),
        ).lastrowid or 0)
        teams = max(1, n // 10)
        for t in range(teams):
            tid = int(conn.execute("INSERT INTO teams (recruitment_id, name, position) VALUES (?, ?, ?)", (rid, f"Команда {t + 1:02d}", t)).lastrowid or 0)
            for pos, role in enumerate(ROLES):
                conn.execute("INSERT INTO role_slots (team_id, role, capacity, position) VALUES (?, ?, 2, ?)", (tid, role, pos))
        # Один хеш на всех синтетических участников: замер не должен упираться в создание данных.
        h, salt = hash_password(PASSWORD)
        for i in range(1, n + 1):
            username = f"s{n}_{i:03d}"
            uid_row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
            uid = int(uid_row["id"]) if uid_row else int(conn.execute(
                "INSERT INTO users (username, display_name, role, password_hash, salt) VALUES (?, ?, 'participant', ?, ?)",
                (username, f"Участник {i:03d}", h, salt),
            ).lastrowid or 0)
            skills = [SKILLS[(i * 3 + k) % len(SKILLS)] for k in range(3)]
            conn.execute(
                "INSERT INTO profiles (user_id, name, skills, interests) VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO NOTHING",
                (uid, f"Участник {i:03d}", json.dumps(skills, ensure_ascii=False), "синтетика"),
            )
            conn.execute(
                "INSERT INTO applications (recruitment_id, user_id, desired_roles, created_at) VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (rid, uid, json.dumps([ROLES[i % len(ROLES)]], ensure_ascii=False), now_iso()),
            )
    return rid


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    c = connect()
    rid = create(c, n)
    c.close()
    print(f"Набор «Синтетика {n}» (id={rid}) готов: {n} откликов, {max(1, n // 10)} команд по 5 ролей × 2 места")
