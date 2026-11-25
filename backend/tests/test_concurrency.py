"""Параллельные запросы к настоящему uvicorn (отдельный процесс, пул потоков, SQLite WAL)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import httpx

from app.seed import DEMO_PASSWORD_ORG


def _org(base: str) -> dict[str, str]:
    r = httpx.post(f"{base}/api/auth/login", json={"username": "organizer", "password": DEMO_PASSWORD_ORG})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _board(base: str, h: dict[str, str]) -> dict:
    rid = httpx.get(f"{base}/api/recruitments", headers=h).json()["recruitments"][0]["id"]
    return httpx.get(f"{base}/api/recruitments/{rid}/board", headers=h).json()


def test_eight_requests_for_one_slot(live_server: str) -> None:
    """8 разных участников одновременно в слот вместимостью 1: ровно один успех, остальные — slot_full."""
    h = _org(live_server)
    b = _board(live_server, h)
    slot_id = b["teams"][0]["slots"][0]["id"]
    cards = b["queue"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda c: httpx.put(
                    f"{live_server}/api/applications/{c['id']}/assignment", json={"slot_id": slot_id, "version": c["version"]}, headers=h, timeout=30
                ),
                cards,
            )
        )
    codes = sorted(r.status_code for r in results)
    assert codes == [200] + [409] * 7
    assert {r.json()["code"] for r in results if r.status_code == 409} == {"slot_full"}
    b = _board(live_server, h)
    assert b["teams"][0]["slots"][0]["taken"] == 1


def test_same_card_to_two_slots_at_once(live_server: str) -> None:
    """Одна карточка одновременно в два разных слота с одной версией: применяется одно назначение."""
    h = _org(live_server)
    b = _board(live_server, h)
    c = b["queue"][0]
    slots = [s["id"] for t in b["teams"] for s in t["slots"]]
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(
            pool.map(
                lambda sid: httpx.put(
                    f"{live_server}/api/applications/{c['id']}/assignment", json={"slot_id": sid, "version": c["version"]}, headers=h, timeout=30
                ),
                slots,
            )
        )
    assert sorted(r.status_code for r in results) == [200] + [409] * 5
    assert {r.json()["code"] for r in results if r.status_code == 409} == {"version_conflict"}
    b = _board(live_server, h)
    assert sum(s["taken"] for t in b["teams"] for s in t["slots"]) == 1


def test_mixed_load_keeps_invariants(live_server: str) -> None:
    """Смешанная нагрузка: переносы и возвраты 8 карточек по 6 слотам. Вместимость не превышается, у человека одно место."""
    h = _org(live_server)
    import random

    rnd = random.Random(5)
    for _ in range(4):
        b = _board(live_server, h)
        cards = b["queue"] + [m for t in b["teams"] for s in t["slots"] for m in s["members"]]
        slots = [s["id"] for t in b["teams"] for s in t["slots"]]
        jobs = []
        for c in cards:
            for _ in range(3):
                if rnd.random() < 0.25:
                    jobs.append(("del", c, None))
                else:
                    jobs.append(("put", c, rnd.choice(slots)))
        rnd.shuffle(jobs)

        def run(job: tuple) -> int:
            kind, c, sid = job
            if kind == "put":
                return httpx.put(f"{live_server}/api/applications/{c['id']}/assignment", json={"slot_id": sid, "version": c["version"]}, headers=h, timeout=30).status_code
            return httpx.delete(f"{live_server}/api/applications/{c['id']}/assignment", params={"version": c["version"]}, headers=h, timeout=30).status_code

        with ThreadPoolExecutor(max_workers=12) as pool:
            codes = list(pool.map(run, jobs))
        assert set(codes) <= {200, 409}
        b = _board(live_server, h)
        for t in b["teams"]:
            for s in t["slots"]:
                assert s["taken"] <= s["capacity"]
        placed = [m["id"] for t in b["teams"] for s in t["slots"] for m in s["members"]] + [c["id"] for c in b["queue"]]
        assert sorted(placed) == sorted(c["id"] for c in cards)
