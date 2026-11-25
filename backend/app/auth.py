"""Пароли, сессии и проверка прав. Предметные правила — в service.py."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

ITERATIONS = 120_000
SESSION_DAYS = 7


@dataclass(frozen=True)
class User:
    id: int
    username: str
    display_name: str
    role: str

    @property
    def is_organizer(self) -> bool:
        return self.role == "organizer"


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), ITERATIONS)
    return digest.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    candidate, _ = hash_password(password, salt)
    return hmac.compare_digest(candidate, password_hash)


def login(conn: sqlite3.Connection, username: str, password: str) -> tuple[User, str] | None:
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip().lower(),)).fetchone()
    if row is None:
        # Одинаковое время ответа для существующих и несуществующих логинов.
        hash_password(password)
        return None
    if not verify_password(password, row["password_hash"], row["salt"]):
        return None
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(UTC) + timedelta(days=SESSION_DAYS)).isoformat(timespec="seconds")
    conn.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)", (token, row["id"], expires))
    conn.execute("DELETE FROM sessions WHERE expires_at < ?", (datetime.now(UTC).isoformat(timespec="seconds"),))
    return _user(row), token


def user_by_token(conn: sqlite3.Connection, token: str | None) -> User | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ? AND s.expires_at > ?",
        (token, datetime.now(UTC).isoformat(timespec="seconds")),
    ).fetchone()
    return _user(row) if row else None


def logout(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def _user(row: sqlite3.Row) -> User:
    return User(id=row["id"], username=row["username"], display_name=row["display_name"], role=row["role"])
