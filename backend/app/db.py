"""Подключение к SQLite и миграции.

Каждый запрос открывает своё соединение (обработчики работают в пуле потоков).
Запись идёт в транзакции BEGIN IMMEDIATE: блокировка записи берётся сразу, поэтому проверка
вместимости слота и запись назначения не перемешиваются с параллельными запросами.
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def db_path() -> str:
    return os.environ.get("DB_PATH", str(Path.cwd() / "data" / "team-board.sqlite3"))


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: str | None = None) -> sqlite3.Connection:
    p = path or db_path()
    if p != ":memory:":
        Path(p).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=10, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


@contextmanager
def write_tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Транзакция записи: BEGIN IMMEDIATE → COMMIT, при исключении ROLLBACK."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def migrate(conn: sqlite3.Connection) -> int:
    """Применяет недостающие миграции по порядку номеров. Возвращает текущую версию схемы."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    applied = {r["version"] for r in conn.execute("SELECT version FROM schema_migrations")}
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    for f in files:
        version = int(f.name.split("_", 1)[0])
        if version in applied:
            continue
        sql = f.read_text(encoding="utf-8")
        conn.execute("BEGIN IMMEDIATE")
        try:
            # executescript сам делает COMMIT перед выполнением, поэтому выполняем операторы по одному.
            for stmt in _split_sql(sql):
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
                (version, f.name, now_iso()),
            )
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return int(row["v"] or 0)


def _split_sql(sql: str) -> list[str]:
    lines = [ln for ln in sql.splitlines() if not ln.strip().startswith("--")]
    return [s.strip() for s in "\n".join(lines).split(";") if s.strip()]


def schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT MAX(version) AS v FROM schema_migrations").fetchone()
    return int(row["v"] or 0)


def latest_migration() -> int:
    return max(int(f.name.split("_", 1)[0]) for f in MIGRATIONS_DIR.glob("*.sql"))
