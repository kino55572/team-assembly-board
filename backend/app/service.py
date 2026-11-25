"""Правила предметной области: набор, команды, слоты ролей, отклики и назначения.

Права пользователя здесь не проверяются — это делает permissions.py до вызова.
Каждая запись — одна транзакция BEGIN IMMEDIATE (db.write_tx).
"""
from __future__ import annotations

import csv
import io
import json
import sqlite3
from typing import Any

from .db import now_iso, write_tx


class DomainError(Exception):
    status = 400

    def __init__(self, code: str, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra


class NotFound(DomainError):
    status = 404


class Forbidden(DomainError):
    status = 403


class Conflict(DomainError):
    status = 409


class Invalid(DomainError):
    status = 422


def _loads(s: str) -> list[str]:
    try:
        v = json.loads(s)
        return [str(x) for x in v] if isinstance(v, list) else []
    except (TypeError, ValueError):
        return []


# ---------- чтение ----------


def recruitment_row(conn: sqlite3.Connection, rid: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM recruitments WHERE id = ?", (rid,)).fetchone()
    if row is None:
        raise NotFound("recruitment_not_found", "Набор не найден")
    return row


def list_recruitments(conn: sqlite3.Connection, user_id: int, organizer: bool) -> list[dict[str, Any]]:
    if organizer:
        rows = conn.execute("SELECT * FROM recruitments WHERE organizer_id = ? ORDER BY id", (user_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT r.* FROM recruitments r WHERE r.status = 'open' OR EXISTS "
            "(SELECT 1 FROM applications a WHERE a.recruitment_id = r.id AND a.user_id = ?) ORDER BY r.id",
            (user_id,),
        ).fetchall()
    out = []
    for r in rows:
        stats = conn.execute(
            "SELECT (SELECT COUNT(*) FROM applications WHERE recruitment_id = ?) AS apps,"
            " (SELECT COALESCE(SUM(s.capacity), 0) FROM role_slots s JOIN teams t ON t.id = s.team_id WHERE t.recruitment_id = ?) AS capacity,"
            " (SELECT COUNT(*) FROM assignments x JOIN applications a ON a.id = x.application_id WHERE a.recruitment_id = ?) AS filled",
            (r["id"], r["id"], r["id"]),
        ).fetchone()
        out.append({**_recruitment(r), "applications": stats["apps"], "capacity": stats["capacity"], "filled": stats["filled"]})
    return out


def _recruitment(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": r["id"],
        "title": r["title"],
        "description": r["description"],
        "status": r["status"],
        "board_version": r["board_version"],
    }


def roles_of(conn: sqlite3.Connection, rid: int) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT s.role FROM role_slots s JOIN teams t ON t.id = s.team_id WHERE t.recruitment_id = ? ORDER BY s.role",
        (rid,),
    ).fetchall()
    return [r["role"] for r in rows]


def _card(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        "name": row["name"],
        "skills": _loads(row["skills"]),
        "interests": row["interests"],
        "desired_roles": _loads(row["desired_roles"]),
        "note": row["note"],
        "version": row["assignment_version"],
        "slot_id": row["slot_id"],
        "created_at": row["created_at"],
    }


APP_SELECT = (
    "SELECT a.id, a.user_id, a.desired_roles, a.note, a.assignment_version, a.created_at,"
    " p.name, p.skills, p.interests, x.slot_id"
    " FROM applications a JOIN profiles p ON p.user_id = a.user_id"
    " LEFT JOIN assignments x ON x.application_id = a.id"
)


def board(conn: sqlite3.Connection, rid: int) -> dict[str, Any]:
    """Вся доска одним снимком: команды со слотами и участниками, очередь, сводка незакрытых ролей."""
    rec = recruitment_row(conn, rid)
    teams = conn.execute("SELECT * FROM teams WHERE recruitment_id = ? ORDER BY position, id", (rid,)).fetchall()
    slots = conn.execute(
        # Порядок: команда за командой (как на доске), внутри команды — порядок ролей.
        "SELECT s.* FROM role_slots s JOIN teams t ON t.id = s.team_id WHERE t.recruitment_id = ? ORDER BY t.position, t.id, s.position, s.id",
        (rid,),
    ).fetchall()
    apps = [_card(r) for r in conn.execute(APP_SELECT + " WHERE a.recruitment_id = ? ORDER BY a.created_at, a.id", (rid,))]
    by_slot: dict[int, list[dict[str, Any]]] = {}
    queue = []
    for a in apps:
        if a["slot_id"] is None:
            queue.append(a)
        else:
            by_slot.setdefault(a["slot_id"], []).append(a)
    slots_by_team: dict[int, list[dict[str, Any]]] = {}
    open_slots = []
    capacity = 0
    filled = 0
    team_names = {t["id"]: t["name"] for t in teams}
    for s in slots:
        members = by_slot.get(s["id"], [])
        free = s["capacity"] - len(members)
        capacity += s["capacity"]
        filled += len(members)
        item = {"id": s["id"], "role": s["role"], "capacity": s["capacity"], "taken": len(members), "free": free, "members": members}
        slots_by_team.setdefault(s["team_id"], []).append(item)
        if free > 0:
            open_slots.append({"slot_id": s["id"], "team": team_names[s["team_id"]], "role": s["role"], "free": free})
    skills = sorted({sk for a in apps for sk in a["skills"]}, key=str.lower)
    return {
        "recruitment": _recruitment(rec),
        "board_version": rec["board_version"],
        "teams": [{"id": t["id"], "name": t["name"], "slots": slots_by_team.get(t["id"], [])} for t in teams],
        "queue": queue,
        "summary": {
            "capacity": capacity,
            "filled": filled,
            "open_slots": open_slots,
            "applications": len(apps),
            "unassigned": len(queue),
        },
        "roles": sorted({s["role"] for s in slots}),
        "skills": skills,
    }


def my_status(conn: sqlite3.Connection, user_id: int, rid: int) -> dict[str, Any]:
    rec = recruitment_row(conn, rid)
    row = conn.execute(APP_SELECT + " WHERE a.recruitment_id = ? AND a.user_id = ?", (rid, user_id)).fetchone()
    profile = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    assignment = None
    if row and row["slot_id"] is not None:
        s = conn.execute(
            "SELECT s.role, t.name AS team FROM role_slots s JOIN teams t ON t.id = s.team_id WHERE s.id = ?",
            (row["slot_id"],),
        ).fetchone()
        assignment = {"team": s["team"], "role": s["role"]}
    return {
        "recruitment": _recruitment(rec),
        "roles": roles_of(conn, rid),
        "application": _card(row) if row else None,
        "assignment": assignment,
        "profile": {"name": profile["name"], "skills": _loads(profile["skills"]), "interests": profile["interests"]} if profile else None,
    }


# ---------- отклики ----------


def create_application(
    conn: sqlite3.Connection,
    user_id: int,
    rid: int,
    name: str,
    skills: list[str],
    interests: str,
    desired_roles: list[str],
    note: str,
) -> dict[str, Any]:
    with write_tx(conn):
        rec = recruitment_row(conn, rid)
        if rec["status"] != "open":
            raise Conflict("recruitment_closed", "Набор закрыт: отклики не принимаются")
        roles = set(roles_of(conn, rid))
        unknown = [r for r in desired_roles if r not in roles]
        if unknown:
            raise Invalid("unknown_roles", f"В наборе нет ролей: {', '.join(unknown)}", field="desired_roles")
        exists = conn.execute("SELECT id FROM applications WHERE recruitment_id = ? AND user_id = ?", (rid, user_id)).fetchone()
        if exists:
            raise Conflict("duplicate_application", "Вы уже откликнулись на этот набор", application_id=exists["id"])
        conn.execute(
            "INSERT INTO profiles (user_id, name, skills, interests) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, skills = excluded.skills, interests = excluded.interests",
            (user_id, name, json.dumps(skills, ensure_ascii=False), interests),
        )
        cur = conn.execute(
            "INSERT INTO applications (recruitment_id, user_id, desired_roles, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (rid, user_id, json.dumps(desired_roles, ensure_ascii=False), note, now_iso()),
        )
        conn.execute("UPDATE recruitments SET board_version = board_version + 1 WHERE id = ?", (rid,))
        app_id = cur.lastrowid
    row = conn.execute(APP_SELECT + " WHERE a.id = ?", (app_id,)).fetchone()
    return _card(row)


def application_recruitment(conn: sqlite3.Connection, app_id: int) -> int:
    row = conn.execute("SELECT recruitment_id FROM applications WHERE id = ?", (app_id,)).fetchone()
    if row is None:
        raise NotFound("application_not_found", "Отклик не найден")
    return int(row["recruitment_id"])


# ---------- назначения ----------


def assign(conn: sqlite3.Connection, actor_id: int, app_id: int, slot_id: int, version: int) -> dict[str, Any]:
    """Назначить отклик в слот или перенести его. Перенос освобождает старое место в той же транзакции."""
    with write_tx(conn):
        app = conn.execute(
            "SELECT a.id, a.recruitment_id, a.assignment_version, r.status FROM applications a"
            " JOIN recruitments r ON r.id = a.recruitment_id WHERE a.id = ?",
            (app_id,),
        ).fetchone()
        if app is None:
            raise NotFound("application_not_found", "Отклик не найден")
        if app["status"] != "open":
            raise Conflict("recruitment_closed", "Набор закрыт: состав не меняется")
        current = conn.execute("SELECT slot_id FROM assignments WHERE application_id = ?", (app_id,)).fetchone()
        if current is not None and current["slot_id"] == slot_id:
            # Уже здесь (в том числе повтор запроса, ответ на который потерялся): ничего не меняем.
            cap = conn.execute("SELECT capacity FROM role_slots WHERE id = ?", (slot_id,)).fetchone()["capacity"]
            taken_all = conn.execute("SELECT COUNT(*) AS n FROM assignments WHERE slot_id = ?", (slot_id,)).fetchone()["n"]
            return {"changed": False, "free_places": cap - taken_all, "version": app["assignment_version"]}
        if app["assignment_version"] != version:
            raise Conflict(
                "version_conflict",
                "Карточку уже изменили: участник " + ("назначен в другое место" if current else "вернулся в очередь") + ". Доска обновлена.",
            )
        slot = conn.execute(
            "SELECT s.id, s.capacity, s.role, t.name AS team, t.recruitment_id FROM role_slots s JOIN teams t ON t.id = s.team_id WHERE s.id = ?",
            (slot_id,),
        ).fetchone()
        if slot is None or slot["recruitment_id"] != app["recruitment_id"]:
            raise Invalid("slot_not_in_recruitment", "Слот не принадлежит этому набору", field="slot_id")
        taken = conn.execute(
            "SELECT COUNT(*) AS n FROM assignments WHERE slot_id = ? AND application_id <> ?", (slot_id, app_id)
        ).fetchone()["n"]
        if taken >= slot["capacity"]:
            raise Conflict("slot_full", f"Место «{slot['role']}» в команде «{slot['team']}» уже занято")
        conn.execute(
            "INSERT INTO assignments (application_id, slot_id, assigned_by, assigned_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(application_id) DO UPDATE SET slot_id = excluded.slot_id, assigned_by = excluded.assigned_by, assigned_at = excluded.assigned_at",
            (app_id, slot_id, actor_id, now_iso()),
        )
        conn.execute("UPDATE applications SET assignment_version = assignment_version + 1 WHERE id = ?", (app_id,))
        conn.execute("UPDATE recruitments SET board_version = board_version + 1 WHERE id = ?", (app["recruitment_id"],))
        return {"changed": True, "free_places": slot["capacity"] - taken - 1, "version": app["assignment_version"] + 1}


def unassign(conn: sqlite3.Connection, app_id: int, version: int) -> dict[str, Any]:
    """Вернуть карточку в очередь."""
    with write_tx(conn):
        app = conn.execute(
            "SELECT a.id, a.recruitment_id, a.assignment_version, r.status FROM applications a"
            " JOIN recruitments r ON r.id = a.recruitment_id WHERE a.id = ?",
            (app_id,),
        ).fetchone()
        if app is None:
            raise NotFound("application_not_found", "Отклик не найден")
        if app["status"] != "open":
            raise Conflict("recruitment_closed", "Набор закрыт: состав не меняется")
        assigned = conn.execute("SELECT 1 FROM assignments WHERE application_id = ?", (app_id,)).fetchone()
        if assigned is None:
            # Уже в очереди (в том числе повтор запроса): ничего не меняем.
            return {"changed": False, "version": app["assignment_version"]}
        if app["assignment_version"] != version:
            raise Conflict("version_conflict", "Карточку уже изменили. Доска обновлена.")
        conn.execute("DELETE FROM assignments WHERE application_id = ?", (app_id,))
        conn.execute("UPDATE applications SET assignment_version = assignment_version + 1 WHERE id = ?", (app_id,))
        conn.execute("UPDATE recruitments SET board_version = board_version + 1 WHERE id = ?", (app["recruitment_id"],))
        return {"changed": True, "version": version + 1}


# ---------- структура набора ----------


def create_recruitment(conn: sqlite3.Connection, organizer_id: int, title: str, description: str) -> int:
    with write_tx(conn):
        cur = conn.execute(
            "INSERT INTO recruitments (title, description, status, organizer_id, created_at) VALUES (?, ?, 'open', ?, ?)",
            (title, description, organizer_id, now_iso()),
        )
        return int(cur.lastrowid or 0)


def update_recruitment(conn: sqlite3.Connection, rid: int, title: str | None, description: str | None, status: str | None) -> None:
    with write_tx(conn):
        recruitment_row(conn, rid)
        if title is not None:
            conn.execute("UPDATE recruitments SET title = ? WHERE id = ?", (title, rid))
        if description is not None:
            conn.execute("UPDATE recruitments SET description = ? WHERE id = ?", (description, rid))
        if status is not None:
            conn.execute("UPDATE recruitments SET status = ? WHERE id = ?", (status, rid))
        conn.execute("UPDATE recruitments SET board_version = board_version + 1 WHERE id = ?", (rid,))


def add_team(conn: sqlite3.Connection, rid: int, name: str) -> int:
    with write_tx(conn):
        recruitment_row(conn, rid)
        if conn.execute("SELECT 1 FROM teams WHERE recruitment_id = ? AND name = ?", (rid, name)).fetchone():
            raise Conflict("duplicate_team", f"Команда «{name}» уже есть", field="name")
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM teams WHERE recruitment_id = ?", (rid,)).fetchone()["p"]
        cur = conn.execute("INSERT INTO teams (recruitment_id, name, position) VALUES (?, ?, ?)", (rid, name, pos))
        conn.execute("UPDATE recruitments SET board_version = board_version + 1 WHERE id = ?", (rid,))
        return int(cur.lastrowid or 0)


def team_recruitment(conn: sqlite3.Connection, team_id: int) -> int:
    row = conn.execute("SELECT recruitment_id FROM teams WHERE id = ?", (team_id,)).fetchone()
    if row is None:
        raise NotFound("team_not_found", "Команда не найдена")
    return int(row["recruitment_id"])


def slot_recruitment(conn: sqlite3.Connection, slot_id: int) -> int:
    row = conn.execute("SELECT t.recruitment_id FROM role_slots s JOIN teams t ON t.id = s.team_id WHERE s.id = ?", (slot_id,)).fetchone()
    if row is None:
        raise NotFound("slot_not_found", "Слот не найден")
    return int(row["recruitment_id"])


def delete_team(conn: sqlite3.Connection, team_id: int) -> None:
    with write_tx(conn):
        rid = team_recruitment(conn, team_id)
        busy = conn.execute(
            "SELECT COUNT(*) AS n FROM assignments x JOIN role_slots s ON s.id = x.slot_id WHERE s.team_id = ?", (team_id,)
        ).fetchone()["n"]
        if busy:
            raise Conflict("team_not_empty", "В команде есть участники: сначала верните их в очередь")
        conn.execute("DELETE FROM teams WHERE id = ?", (team_id,))
        conn.execute("UPDATE recruitments SET board_version = board_version + 1 WHERE id = ?", (rid,))


def add_slot(conn: sqlite3.Connection, team_id: int, role: str, capacity: int) -> int:
    with write_tx(conn):
        rid = team_recruitment(conn, team_id)
        if conn.execute("SELECT 1 FROM role_slots WHERE team_id = ? AND role = ?", (team_id, role)).fetchone():
            raise Conflict("duplicate_slot", f"Роль «{role}» в этой команде уже есть: измените её вместимость", field="role")
        pos = conn.execute("SELECT COALESCE(MAX(position), -1) + 1 AS p FROM role_slots WHERE team_id = ?", (team_id,)).fetchone()["p"]
        cur = conn.execute("INSERT INTO role_slots (team_id, role, capacity, position) VALUES (?, ?, ?, ?)", (team_id, role, capacity, pos))
        conn.execute("UPDATE recruitments SET board_version = board_version + 1 WHERE id = ?", (rid,))
        return int(cur.lastrowid or 0)


def update_slot(conn: sqlite3.Connection, slot_id: int, capacity: int) -> None:
    with write_tx(conn):
        rid = slot_recruitment(conn, slot_id)
        taken = conn.execute("SELECT COUNT(*) AS n FROM assignments WHERE slot_id = ?", (slot_id,)).fetchone()["n"]
        if capacity < taken:
            raise Conflict("capacity_below_taken", f"Занято {taken} мест: вместимость не может быть меньше", field="capacity")
        conn.execute("UPDATE role_slots SET capacity = ? WHERE id = ?", (capacity, slot_id))
        conn.execute("UPDATE recruitments SET board_version = board_version + 1 WHERE id = ?", (rid,))


def delete_slot(conn: sqlite3.Connection, slot_id: int) -> None:
    with write_tx(conn):
        rid = slot_recruitment(conn, slot_id)
        if conn.execute("SELECT 1 FROM assignments WHERE slot_id = ?", (slot_id,)).fetchone():
            raise Conflict("slot_not_empty", "В слоте есть участник: сначала верните его в очередь")
        conn.execute("DELETE FROM role_slots WHERE id = ?", (slot_id,))
        conn.execute("UPDATE recruitments SET board_version = board_version + 1 WHERE id = ?", (rid,))


def export_csv(conn: sqlite3.Connection, rid: int) -> str:
    b = board(conn, rid)
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(["team", "role", "name", "skills", "desired_roles"])
    for t in b["teams"]:
        for s in t["slots"]:
            for m in s["members"]:
                w.writerow([t["name"], s["role"], _safe(m["name"]), _safe(", ".join(m["skills"])), _safe(", ".join(m["desired_roles"]))])
            for _ in range(s["free"]):
                w.writerow([t["name"], s["role"], "", "", ""])
    for m in b["queue"]:
        w.writerow(["", "", _safe(m["name"]), _safe(", ".join(m["skills"])), _safe(", ".join(m["desired_roles"]))])
    return buf.getvalue()


def _safe(value: str) -> str:
    """Значение, начинающееся с = + - @, Excel выполнит как формулу — экранируем апострофом."""
    return f"'{value}" if value[:1] in ("=", "+", "-", "@") else value
