"""Модельная проверка правил назначения: сервер против простой модели в памяти на случайных операциях."""
from __future__ import annotations

import random

import httpx

from tests.conftest import login


def snapshot(c: httpx.Client, h: dict[str, str], rid: int) -> dict:
    return c.get(f"/api/recruitments/{rid}/board", headers=h).json()


def check_board(b: dict, model_slot: dict[int, int | None], capacity: dict[int, int]) -> None:
    # 1) у каждого отклика ровно одно место: в очереди или в одном слоте
    seen: dict[int, int | None] = {}
    for card in b["queue"]:
        assert card["id"] not in seen
        assert card["slot_id"] is None
        seen[card["id"]] = None
    filled = 0
    open_slots = []
    for t in b["teams"]:
        for s in t["slots"]:
            assert s["taken"] == len(s["members"])
            assert s["taken"] <= s["capacity"], "вместимость превышена"
            assert s["free"] == s["capacity"] - s["taken"]
            assert s["capacity"] == capacity[s["id"]]
            filled += s["taken"]
            if s["free"] > 0:
                open_slots.append(s["id"])
            for m in s["members"]:
                assert m["id"] not in seen, "человек занимает два места"
                assert m["slot_id"] == s["id"]
                seen[m["id"]] = s["id"]
    # 2) сервер совпадает с моделью
    assert seen == model_slot
    # 3) сводка согласована с доской
    assert b["summary"]["filled"] == filled
    assert b["summary"]["unassigned"] == len(b["queue"])
    assert [o["slot_id"] for o in b["summary"]["open_slots"]] == open_slots
    assert b["summary"]["capacity"] == sum(capacity.values())


def test_random_operations_match_model(client: httpx.Client) -> None:
    h = login(client, "organizer")
    rid = client.get("/api/recruitments", headers=h).json()["recruitments"][0]["id"]
    b = snapshot(client, h, rid)
    slots = [s["id"] for t in b["teams"] for s in t["slots"]]
    capacity = {s["id"]: s["capacity"] for t in b["teams"] for s in t["slots"]}
    model: dict[int, int | None] = {c["id"]: None for c in b["queue"]}
    versions: dict[int, int] = {c["id"]: c["version"] for c in b["queue"]}
    stale: dict[int, int] = dict(versions)
    rnd = random.Random(20261120)
    board_version = b["board_version"]
    stats = {"ok": 0, "full": 0, "version": 0, "noop": 0, "cap": 0, "cap_rejected": 0}

    for step in range(400):
        app = rnd.choice(list(model))
        use_stale = rnd.random() < 0.15
        version = stale[app] if use_stale else versions[app]
        op = rnd.random()
        if op < 0.6:
            sid = rnd.choice(slots)
            r = client.put(f"/api/applications/{app}/assignment", json={"slot_id": sid, "version": version}, headers=h)
            taken_other = sum(1 for a, s in model.items() if s == sid and a != app)
            if model[app] == sid:
                # уже там — повтор без изменений при любой версии
                assert r.status_code == 200 and r.json()["changed"] is False
                stats["noop"] += 1
            elif version != versions[app]:
                assert r.status_code == 409 and r.json()["code"] == "version_conflict", (step, r.text)
                stats["version"] += 1
            elif taken_other >= capacity[sid]:
                assert r.status_code == 409 and r.json()["code"] == "slot_full", (step, r.text)
                stats["full"] += 1
            else:
                assert r.status_code == 200 and r.json()["changed"] is True, (step, r.text)
                assert r.json()["free_places"] == capacity[sid] - taken_other - 1
                stale[app] = versions[app]
                versions[app] += 1
                model[app] = sid
                stats["ok"] += 1
        elif op < 0.85:
            r = client.delete(f"/api/applications/{app}/assignment", params={"version": version}, headers=h)
            if model[app] is None:
                assert r.status_code == 200 and r.json()["changed"] is False
                stats["noop"] += 1
            elif version != versions[app]:
                assert r.status_code == 409 and r.json()["code"] == "version_conflict"
                stats["version"] += 1
            else:
                assert r.status_code == 200 and r.json()["changed"] is True
                stale[app] = versions[app]
                versions[app] += 1
                model[app] = None
                stats["ok"] += 1
        else:
            sid = rnd.choice(slots)
            cap = rnd.randint(1, 3)
            r = client.patch(f"/api/slots/{sid}", json={"capacity": cap}, headers=h)
            taken = sum(1 for s in model.values() if s == sid)
            if cap < taken:
                assert r.status_code == 409 and r.json()["code"] == "capacity_below_taken"
                stats["cap_rejected"] += 1
            else:
                assert r.status_code == 200
                capacity[sid] = cap
                stats["cap"] += 1
        b = snapshot(client, h, rid)
        check_board(b, model, capacity)
        for c in b["queue"] + [m for t in b["teams"] for s in t["slots"] for m in s["members"]]:
            assert c["version"] == versions[c["id"]]
        changed = r.status_code == 200 and r.json().get("changed", True)
        if changed:
            assert b["board_version"] > board_version
        else:
            assert b["board_version"] == board_version, f"версия доски изменилась без изменения на шаге {step}"
        board_version = b["board_version"]

    # Все ветки правил действительно проверены.
    print("MODEL205", stats)
    assert all(v > 0 for v in stats.values()), stats
