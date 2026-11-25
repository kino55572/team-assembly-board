"""Учётные записи из командной строки (для публичной версии без демо-сида).

    python -m app.users add organizer2 --role organizer --name "Мария Иванова"   # пароль спросит скрыто
    echo "secret" | python -m app.users add p9 --role participant --name "Пётр" --password-stdin
    python -m app.users passwd organizer2
    python -m app.users list

В контейнере: docker compose exec app python -m app.users list
(для ввода пароля используйте docker compose exec -it ... или --password-stdin).
"""
from __future__ import annotations

import argparse
import getpass
import sqlite3
import sys

from .auth import hash_password
from .db import connect, migrate, write_tx

MIN_PASSWORD = 8


def _password(args: argparse.Namespace) -> str:
    if args.password_stdin:
        pwd = sys.stdin.readline().rstrip("\n")
    else:
        pwd = getpass.getpass("Пароль: ")
        if getpass.getpass("Повторите: ") != pwd:
            raise SystemExit("Пароли не совпадают")
    if len(pwd) < MIN_PASSWORD:
        raise SystemExit(f"Пароль короче {MIN_PASSWORD} символов")
    return pwd


def add(conn: sqlite3.Connection, username: str, role: str, name: str, password: str) -> int:
    username = username.strip().lower()
    if not username or not name.strip():
        raise SystemExit("Нужны логин и имя")
    h, salt = hash_password(password)
    with write_tx(conn):
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise SystemExit(f"Логин {username} уже занят")
        return int(
            conn.execute(
                "INSERT INTO users (username, display_name, role, password_hash, salt) VALUES (?, ?, ?, ?, ?)",
                (username, name.strip(), role, h, salt),
            ).lastrowid
            or 0
        )


def set_password(conn: sqlite3.Connection, username: str, password: str) -> None:
    h, salt = hash_password(password)
    with write_tx(conn):
        cur = conn.execute("UPDATE users SET password_hash = ?, salt = ? WHERE username = ?", (h, salt, username.strip().lower()))
        if cur.rowcount == 0:
            raise SystemExit(f"Нет пользователя {username}")
        # Старые сессии после смены пароля недействительны.
        conn.execute("DELETE FROM sessions WHERE user_id = (SELECT id FROM users WHERE username = ?)", (username.strip().lower(),))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.users")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("username")
    a.add_argument("--role", choices=["organizer", "participant"], required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--password-stdin", action="store_true")
    p = sub.add_parser("passwd")
    p.add_argument("username")
    p.add_argument("--password-stdin", action="store_true")
    sub.add_parser("list")
    args = ap.parse_args(argv)
    conn = connect()
    try:
        migrate(conn)
        if args.cmd == "add":
            uid = add(conn, args.username, args.role, args.name, _password(args))
            print(f"Создан пользователь {args.username} (id={uid}, роль {args.role})")
        elif args.cmd == "passwd":
            set_password(conn, args.username, _password(args))
            print(f"Пароль {args.username} изменён, старые сессии закрыты")
        else:
            for r in conn.execute("SELECT username, display_name, role FROM users ORDER BY role, username"):
                print(f"{r['role']:<12} {r['username']:<20} {r['display_name']}")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
