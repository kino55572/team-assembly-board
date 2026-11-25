# Правила работы с проектом 205 Доска сборки команд

Сервер FastAPI + SQLite (stdlib `sqlite3`, без ORM), интерфейс React + TypeScript + Vite. Один Docker-контейнер, порт `127.0.0.1:8205`.

## Где что находится

- Интерфейс и публичные маршруты — `frontend/src/App.tsx` (вход и выбор вида по роли), `frontend/src/ui/Login.tsx`, `OrganizerView.tsx` (доска), `CardView.tsx`, `AssignDialog.tsx` (меню назначения), `SetupPanel.tsx`, `ParticipantView.tsx`, `frontend/src/api.ts`, `frontend/src/board-logic.ts`. API: `/api/auth/*`, `/api/me`, `/api/recruitments[/{id}/board|my|applications|teams|export.csv]`, `/api/teams/{id}[/slots]`, `/api/slots/{id}`, `/api/applications/{id}/assignment`, `/api/health`, `/api/demo/*` (только `DEMO_MODE=1`). OpenAPI — `/api/docs`.
- Предметная логика и хранение — `backend/app/service.py` (правила), `backend/app/main.py` (маршруты, права, сессии), `backend/app/auth.py`, `backend/app/db.py`, `backend/app/migrations/*.sql`.
- Данные, ассеты и демоматериалы — `backend/app/seed.py` (организатор, p1…p8, «Осенний хакатон»), `backend/app/synthetic.py` (100 откликов), `frontend/public/favicon.svg` (собственная), том Docker `board-data`.
- Тесты и документация — `backend/tests/` (pytest), `frontend/src/*.test.ts` (Vitest), `frontend/e2e/` (Playwright), `scripts/container_check.py`, `docs/`.

## Команды и сценарий

- Установка — `docker compose up -d --build`. Для разработки: `backend/.venv` + `pip install -r requirements-dev.txt`, `frontend: npm ci`.
- Запуск и адрес — http://127.0.0.1:8205 (контейнер). В разработке: uvicorn на :8000 и `npm run dev` на :5205.
- Проверки и сборка — `cd backend && python -m pytest`, `cd frontend && npm test && npm run build && npm run e2e` (против контейнера), `python3 scripts/container_check.py --restart`.
- Данные и результат показательного сценария — вход `organizer / organizer-demo`. 8 кандидатов, две команды, одна роль (Бета — Аналитик) открыта. Перенос освобождает прежнее место. Изменение по устаревшей версии даёт 409 и актуальную доску. Участник `p1 / participant-demo` видит свой итог.

## Инварианты проекта

- Права (`require_organizer_of`, `require_participant` в `main.py`) отделены от правил предметной области (`service.py`). Менять состав может только организатор, владеющий набором. Участник видит только `/my`.
- Каждая запись — одна транзакция `BEGIN IMMEDIATE` (`db.write_tx`): проверка вместимости и запись не перемешиваются с параллельными запросами. Вместимость слота не превышается, у отклика не больше одного назначения (PK `assignments.application_id`), у человека один отклик на набор.
- Изменение назначения передаёт `version` (`applications.assignment_version`). Устаревшая версия даёт 409 `version_conflict` и актуальную доску в ответе. Повтор, который ничего не меняет (карточка уже в этом слоте или уже в очереди), даёт 200 `changed=false` при любой версии.
- Любое изменение доски увеличивает `recruitments.board_version`. От неё зависит ETag `GET /board` (304 при неизменной доске). Не меняйте данные доски в обход `board_version`.
- Миграции — только новыми файлами `NNN_*.sql`, применённые не редактировать. Сид и синтетика идемпотентны.
- `/api/demo/reset` удаляет всё, кроме демо-набора: только для демо-базы.
- В интерфейсе кнопки карточки на время запроса — `aria-disabled` (не `disabled`), иначе теряется фокус. Колонки доски на широком экране прокручиваются сами, чтобы очередь и слоты были видны одновременно.

Изменения проверяй через основной сценарий и применимые граничные случаи. Для ночного выпуска веди в `docs/ACCEPTANCE.md` пять секций: корректность, восстановление, удобство, узкие места и воспроизводимость. Записывай измерения и результаты повторных проверок. Фактическое устройство продукта описано в `docs/ARCHITECTURE.md`, рецепты проверок — в `docs/ACCEPTANCE.md`. Публикуй этот репозиторий и развёртывай его по `PUBLISH_TO_GITHUB.md` только по запросу владельца.
