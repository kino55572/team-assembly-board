"""HTTP API доски сборки команд и раздача собранного интерфейса."""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import Cookie, Depends, FastAPI, Header, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from . import auth, service
from .db import connect, latest_migration, migrate, schema_version
from .service import DomainError, Forbidden

COOKIE = "tab_session"


def env_flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


@asynccontextmanager
async def lifespan(_: FastAPI):
    conn = connect()
    try:
        migrate(conn)
        if env_flag("SEED_DEMO"):
            from .seed import seed

            seed(conn)
    finally:
        conn.close()
    yield


app = FastAPI(title="Доска сборки команд", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")


@app.exception_handler(DomainError)
async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message, **exc.extra})


def get_conn() -> Iterator[sqlite3.Connection]:
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _token(cookie: str | None, authorization: str | None) -> str | None:
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return cookie


class _Unauthorized(DomainError):
    status = 401

    def __init__(self) -> None:
        super().__init__("unauthorized", "Нужно войти")


def current_user(
    conn: Conn,
    tab_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> auth.User:
    user = auth.user_by_token(conn, _token(tab_session, authorization))
    if user is None:
        raise _Unauthorized()
    return user


CurrentUser = Annotated[auth.User, Depends(current_user)]


# ---------- права (отдельно от предметных правил) ----------


def require_organizer_of(conn: sqlite3.Connection, user: auth.User, rid: int) -> None:
    rec = service.recruitment_row(conn, rid)
    if not user.is_organizer or rec["organizer_id"] != user.id:
        raise Forbidden("forbidden", "Менять состав может только организатор набора")


def require_participant(user: auth.User) -> None:
    if user.is_organizer:
        raise Forbidden("forbidden", "Отклик подаёт участник, а не организатор")


# ---------- схемы ----------


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=200)


class ApplicationIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    skills: list[str] = Field(default_factory=list, max_length=12)
    interests: str = Field(default="", max_length=300)
    desired_roles: list[str] = Field(default_factory=list, max_length=10)
    note: str = Field(default="", max_length=300)

    @field_validator("name", "interests", "note")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("skills")
    @classmethod
    def clean_skills(cls, v: list[str]) -> list[str]:
        out: list[str] = []
        for s in v:
            s = s.strip()
            if not s:
                continue
            if len(s) > 30:
                raise ValueError("Навык не длиннее 30 символов")
            if s.lower() not in (x.lower() for x in out):
                out.append(s)
        return out

    @field_validator("desired_roles")
    @classmethod
    def clean_roles(cls, v: list[str]) -> list[str]:
        return list(dict.fromkeys(r.strip() for r in v if r.strip()))


class AssignmentIn(BaseModel):
    slot_id: int
    version: int = Field(ge=0)


class RecruitmentIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class RecruitmentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    status: Literal["open", "closed"] | None = None


class TeamIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)

    @field_validator("name")
    @classmethod
    def strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Введите название")
        return v.strip()


class SlotIn(BaseModel):
    role: str = Field(min_length=1, max_length=40)
    capacity: int = Field(ge=1, le=50)

    @field_validator("role")
    @classmethod
    def strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Введите роль")
        return v.strip()


class SlotPatch(BaseModel):
    capacity: int = Field(ge=1, le=50)


# ---------- служебное ----------


@app.get("/api/health")
def health(conn: Conn) -> dict[str, object]:
    conn.execute("SELECT 1").fetchone()
    version = schema_version(conn)
    ready = version >= latest_migration()
    return {"status": "ok" if ready else "migrating", "schema_version": version, "demo": env_flag("DEMO_MODE")}


@app.post("/api/auth/login")
def login(body: LoginIn, conn: Conn, response: Response) -> dict[str, object]:
    res = auth.login(conn, body.username, body.password)
    if res is None:
        raise _BadLogin()
    user, token = res
    response.set_cookie(COOKIE, token, httponly=True, samesite="lax", secure=env_flag("COOKIE_SECURE"), max_age=auth.SESSION_DAYS * 86400, path="/")
    return {"user": _user(user), "token": token}


class _BadLogin(DomainError):
    status = 401

    def __init__(self) -> None:
        super().__init__("bad_credentials", "Неверный логин или пароль", field="password")


@app.post("/api/auth/logout")
def logout(
    conn: Conn,
    response: Response,
    tab_session: Annotated[str | None, Cookie()] = None,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, bool]:
    auth.logout(conn, _token(tab_session, authorization))
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@app.get("/api/me")
def me(user: CurrentUser) -> dict[str, object]:
    return {"user": _user(user)}


def _user(u: auth.User) -> dict[str, object]:
    return {"id": u.id, "username": u.username, "display_name": u.display_name, "role": u.role}


@app.get("/api/demo/users")
def demo_users() -> dict[str, object]:
    """Подсказка логинов на экране входа. Только в демо-режиме."""
    if not env_flag("DEMO_MODE"):
        raise service.NotFound("not_found", "Нет такого адреса")
    from .seed import DEMO_PASSWORD_ORG, DEMO_PASSWORD_PARTICIPANT, DEMO_USERS

    return {
        "users": [
            {"username": u, "display_name": n, "role": r, "password": DEMO_PASSWORD_ORG if r == "organizer" else DEMO_PASSWORD_PARTICIPANT}
            for u, n, r in DEMO_USERS
        ]
    }


@app.post("/api/demo/reset")
def demo_reset(conn: Conn, user: CurrentUser) -> dict[str, bool]:
    """Вернуть демо-набор к исходному виду (для показа и автотестов). Только в демо-режиме и только организатору."""
    if not env_flag("DEMO_MODE"):
        raise service.NotFound("not_found", "Нет такого адреса")
    if not user.is_organizer:
        raise Forbidden("forbidden", "Только организатор")
    from .seed import seed

    seed(conn, reset=True)
    return {"ok": True}


# ---------- наборы ----------


@app.get("/api/recruitments")
def recruitments(conn: Conn, user: CurrentUser) -> dict[str, object]:
    return {"recruitments": service.list_recruitments(conn, user.id, user.is_organizer)}


@app.post("/api/recruitments", status_code=201)
def create_recruitment(body: RecruitmentIn, conn: Conn, user: CurrentUser) -> dict[str, object]:
    if not user.is_organizer:
        raise Forbidden("forbidden", "Набор открывает организатор")
    rid = service.create_recruitment(conn, user.id, body.title.strip(), body.description.strip())
    return service.board(conn, rid)


@app.patch("/api/recruitments/{rid}")
def patch_recruitment(rid: int, body: RecruitmentPatch, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_organizer_of(conn, user, rid)
    service.update_recruitment(conn, rid, body.title, body.description, body.status)
    return service.board(conn, rid)


def _etag(rid: int, version: int) -> str:
    return f'"board-{rid}-v{version}"'


@app.get("/api/recruitments/{rid}/board", response_model=None)
def get_board(
    rid: int,
    conn: Conn,
    user: CurrentUser,
    response: Response,
    if_none_match: Annotated[str | None, Header()] = None,
) -> dict[str, object] | Response:
    """Доска целиком. ETag = версия доски: при опросе без изменений — 304 без сборки доски."""
    require_organizer_of(conn, user, rid)
    version = service.recruitment_row(conn, rid)["board_version"]
    tag = _etag(rid, version)
    headers = {"ETag": tag, "Cache-Control": "private, no-cache"}
    if if_none_match and tag in [t.strip() for t in if_none_match.split(",")]:
        return Response(status_code=304, headers=headers)
    b = service.board(conn, rid)
    # Версия могла вырасти между двумя чтениями — заголовок берём из собранной доски.
    response.headers["ETag"] = _etag(rid, int(b["board_version"]))
    response.headers["Cache-Control"] = headers["Cache-Control"]
    return b


@app.get("/api/recruitments/{rid}/my")
def get_my(rid: int, conn: Conn, user: CurrentUser) -> dict[str, object]:
    return service.my_status(conn, user.id, rid)


@app.post("/api/recruitments/{rid}/applications", status_code=201)
def post_application(rid: int, body: ApplicationIn, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_participant(user)
    card = service.create_application(conn, user.id, rid, body.name, body.skills, body.interests, body.desired_roles, body.note)
    return {"application": card}


@app.get("/api/recruitments/{rid}/export.csv")
def export(rid: int, conn: Conn, user: CurrentUser) -> PlainTextResponse:
    require_organizer_of(conn, user, rid)
    text = "﻿" + service.export_csv(conn, rid)
    return PlainTextResponse(
        text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="team-board-{rid}.csv"'},
    )


@app.post("/api/recruitments/{rid}/teams", status_code=201)
def post_team(rid: int, body: TeamIn, conn: Conn, user: CurrentUser) -> dict[str, object]:
    require_organizer_of(conn, user, rid)
    service.add_team(conn, rid, body.name)
    return service.board(conn, rid)


@app.delete("/api/teams/{team_id}")
def del_team(team_id: int, conn: Conn, user: CurrentUser) -> dict[str, object]:
    rid = service.team_recruitment(conn, team_id)
    require_organizer_of(conn, user, rid)
    service.delete_team(conn, team_id)
    return service.board(conn, rid)


@app.post("/api/teams/{team_id}/slots", status_code=201)
def post_slot(team_id: int, body: SlotIn, conn: Conn, user: CurrentUser) -> dict[str, object]:
    rid = service.team_recruitment(conn, team_id)
    require_organizer_of(conn, user, rid)
    service.add_slot(conn, team_id, body.role, body.capacity)
    return service.board(conn, rid)


@app.patch("/api/slots/{slot_id}")
def patch_slot(slot_id: int, body: SlotPatch, conn: Conn, user: CurrentUser) -> dict[str, object]:
    rid = service.slot_recruitment(conn, slot_id)
    require_organizer_of(conn, user, rid)
    service.update_slot(conn, slot_id, body.capacity)
    return service.board(conn, rid)


@app.delete("/api/slots/{slot_id}")
def del_slot(slot_id: int, conn: Conn, user: CurrentUser) -> dict[str, object]:
    rid = service.slot_recruitment(conn, slot_id)
    require_organizer_of(conn, user, rid)
    service.delete_slot(conn, slot_id)
    return service.board(conn, rid)


# ---------- назначения ----------


def _with_board(conn: sqlite3.Connection, rid: int, exc: DomainError) -> JSONResponse:
    """Конфликт: вернуть актуальную доску, чтобы клиент сразу показал текущее состояние."""
    return JSONResponse(status_code=exc.status, content={"code": exc.code, "message": exc.message, **exc.extra, "board": service.board(conn, rid)})


@app.put("/api/applications/{app_id}/assignment", response_model=None)
def put_assignment(app_id: int, body: AssignmentIn, conn: Conn, user: CurrentUser) -> dict[str, object] | JSONResponse:
    rid = service.application_recruitment(conn, app_id)
    require_organizer_of(conn, user, rid)
    try:
        res = service.assign(conn, user.id, app_id, body.slot_id, body.version)
    except service.Conflict as exc:
        return _with_board(conn, rid, exc)
    return {**res, "board": service.board(conn, rid)}


@app.delete("/api/applications/{app_id}/assignment", response_model=None)
def delete_assignment(app_id: int, conn: Conn, user: CurrentUser, version: Annotated[int, Query(ge=0)]) -> dict[str, object] | JSONResponse:
    rid = service.application_recruitment(conn, app_id)
    require_organizer_of(conn, user, rid)
    try:
        res = service.unassign(conn, app_id, version)
    except service.Conflict as exc:
        return _with_board(conn, rid, exc)
    return {**res, "board": service.board(conn, rid)}


# ---------- интерфейс ----------

_static = Path(os.environ.get("STATIC_DIR", str(Path(__file__).resolve().parent.parent / "static")))
if _static.is_dir() and (_static / "index.html").exists():
    app.mount("/", StaticFiles(directory=_static, html=True), name="ui")
