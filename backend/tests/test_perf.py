"""Замер на 100 синтетических откликах (настоящий uvicorn). Печатает строку PERF205 с медианами и p95.

Запуск отдельно: python -m pytest tests/test_perf.py -s
"""
from __future__ import annotations

import cProfile
import io
import json
import os
import pstats
import statistics
import time
from pathlib import Path

import httpx

from app.seed import DEMO_PASSWORD_ORG


def _q(xs: list[float], p: float) -> float:
    s = sorted(xs)
    return round(s[min(len(s) - 1, int(p * len(s)))], 2)


def _measure(fn, n: int) -> dict[str, float]:
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        times.append((time.perf_counter() - t0) * 1000)
    return {"p50": round(statistics.median(times), 2), "p95": _q(times, 0.95), "max": round(max(times), 2)}


def test_board_and_assignment_on_100_applications(live_server: str, tmp_path: Path) -> None:
    from app.db import connect
    from app.synthetic import create

    db = Path(os.environ.get("DB_PATH_LIVE", "")) if os.environ.get("DB_PATH_LIVE") else None
    # live_server создаёт базу в tmp_path/live.sqlite3
    conn = connect(str(db or tmp_path / "live.sqlite3"))
    rid = create(conn, 100)
    conn.close()

    c = httpx.Client(base_url=live_server, timeout=30)
    login = _measure(lambda: c.post("/api/auth/login", json={"username": "organizer", "password": DEMO_PASSWORD_ORG}).raise_for_status(), 10)
    r = c.get(f"/api/recruitments/{rid}/board")
    board = r.json()
    board_bytes = len(r.content)
    assert board["summary"]["applications"] == 100 and len(board["teams"]) == 10

    get_board = _measure(lambda: c.get(f"/api/recruitments/{rid}/board").raise_for_status(), 50)
    etag = r.headers.get("etag")
    poll = (
        _measure(lambda: c.get(f"/api/recruitments/{rid}/board", headers={"If-None-Match": etag}), 50) if etag else None
    )
    list_recs = _measure(lambda: c.get("/api/recruitments").raise_for_status(), 20)

    # Назначения: 50 разных карточек по свободным местам, каждая — PUT с полной доской в ответе.
    queue = board["queue"]
    slots = [s for t in board["teams"] for s in t["slots"]]
    put_times = []
    for i, cardx in enumerate(queue[:50]):
        sid = slots[i % len(slots)]["id"]
        t0 = time.perf_counter()
        resp = c.put(f"/api/applications/{cardx['id']}/assignment", json={"slot_id": sid, "version": cardx["version"]})
        put_times.append((time.perf_counter() - t0) * 1000)
        assert resp.status_code == 200, resp.text
    put = {"p50": round(statistics.median(put_times), 2), "p95": _q(put_times, 0.95), "max": round(max(put_times), 2)}

    # Разбивка самого частого запроса внутри процесса: где тратится время при построении доски.
    os.environ["DB_PATH"] = str(tmp_path / "live.sqlite3")
    from app import service
    from app.db import connect as conn_fn

    prof = cProfile.Profile()
    conn2 = conn_fn()
    prof.enable()
    for _ in range(50):
        json.dumps(service.board(conn2, rid), ensure_ascii=False)
    prof.disable()
    conn2.close()
    out = io.StringIO()
    pstats.Stats(prof, stream=out).sort_stats("tottime").print_stats(6)
    top = [ln.strip() for ln in out.getvalue().splitlines() if ln.strip() and ln.strip()[0].isdigit()][:6]

    result = {
        "login_ms": login,
        "board_ms": get_board,
        "board_poll_unchanged_ms": poll,
        "board_bytes": board_bytes,
        "recruitments_ms": list_recs,
        "assign_put_ms": put,
        "board_profile_top": top,
    }
    print("PERF205 " + json.dumps(result, ensure_ascii=False))
    assert get_board["p95"] < 200
    assert put["p95"] < 300
