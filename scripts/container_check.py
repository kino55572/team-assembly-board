#!/usr/bin/env python3
"""Сквозная проверка запущенного контейнера без сторонних библиотек.

    python3 scripts/container_check.py                 # http://127.0.0.1:8205
    python3 scripts/container_check.py --restart       # + docker compose restart и проверка сохранности
    python3 scripts/container_check.py --base http://127.0.0.1:9000

Шаги: готовность /api/health → вход организатора и участника → сброс демо → 8 параллельных
назначений на одно место (ровно одно успешное) → участник видит назначение → [перезапуск → состав сохранён].
Демо-режим (DEMO_MODE=1) обязателен: используется /api/demo/reset.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from http.cookiejar import CookieJar
from pathlib import Path

ORG = {"username": "organizer", "password": "organizer-demo"}
P1 = {"username": "p1", "password": "participant-demo"}


class Session:
    def __init__(self, base: str) -> None:
        self.base = base
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))

    def call(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"} if data else {})
        try:
            with self.opener.open(req, timeout=15) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")


def wait_ready(base: str, timeout: float = 90) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        try:
            with urllib.request.urlopen(base + "/api/health", timeout=2) as r:
                h = json.loads(r.read())
                if h.get("status") == "ok":
                    return h
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(1)
    raise SystemExit("FAIL: сервер не стал готов")


def step(ok: bool, text: str) -> None:
    print(("ok   " if ok else "FAIL ") + text)
    if not ok:
        sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8205")
    ap.add_argument("--restart", action="store_true")
    args = ap.parse_args()

    h = wait_ready(args.base)
    step(h["schema_version"] >= 1 and h["demo"] is True, f"готовность: {h}")
    org = Session(args.base)
    code, me = org.call("POST", "/api/auth/login", ORG)
    step(code == 200 and me["user"]["role"] == "organizer", "вход организатора")
    step(org.call("POST", "/api/demo/reset")[0] == 200, "сброс демо")
    code, recs = org.call("GET", "/api/recruitments")
    rid = recs["recruitments"][0]["id"]
    _, board = org.call("GET", f"/api/recruitments/{rid}/board")
    step(len(board["queue"]) == 8, "8 кандидатов в очереди")
    slot = board["teams"][0]["slots"][0]

    def put(card: dict) -> int:
        return org.call("PUT", f"/api/applications/{card['id']}/assignment", {"slot_id": slot["id"], "version": card["version"]})[0]

    with ThreadPoolExecutor(max_workers=8) as pool:
        codes = sorted(pool.map(put, board["queue"]))
    step(codes == [200] + [409] * 7, f"8 параллельных назначений на «{slot['role']}» вместимостью 1: {codes}")
    _, board = org.call("GET", f"/api/recruitments/{rid}/board")
    winner = board["teams"][0]["slots"][0]["members"][0]
    step(board["summary"]["filled"] == 1, f"занято одно место: {winner['name']}")

    p1 = Session(args.base)
    step(p1.call("POST", "/api/auth/login", P1)[0] == 200, "вход участника p1")
    step(p1.call("GET", f"/api/recruitments/{rid}/board")[0] == 403, "участнику доска недоступна (403)")
    _, my = p1.call("GET", f"/api/recruitments/{rid}/my")
    expected = {"team": board["teams"][0]["name"], "role": slot["role"]} if winner["user_id"] == my["application"]["user_id"] else None
    step(my["assignment"] == expected, f"участник видит свой итог: {my['assignment']}")

    if args.restart:
        root = Path(__file__).resolve().parent.parent
        subprocess.run(["docker", "compose", "restart"], cwd=root, check=True, capture_output=True)
        wait_ready(args.base)
        org2 = Session(args.base)
        org2.call("POST", "/api/auth/login", ORG)
        _, after = org2.call("GET", f"/api/recruitments/{rid}/board")
        names = [m["name"] for t in after["teams"] for s in t["slots"] for m in s["members"]]
        step(names == [winner["name"]], f"после docker compose restart состав сохранён: {names}")
    print("Все проверки пройдены")
    return 0


if __name__ == "__main__":
    sys.exit(main())
