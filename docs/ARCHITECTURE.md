# Архитектура 205 · team-assembly-board

## Схема

```text
Браузер ──HTTP──► 127.0.0.1:8205 ─► контейнер :8000 uvicorn
                                       └─ FastAPI app.main
                                            ├─ /api/*            JSON API (права → правила → SQLite)
                                            └─ /                 StaticFiles: собранный React (/app/static)
                                       SQLite /data/team-board.sqlite3 (том board-data, WAL)
```

| Слой | Файл | Ответственность |
|---|---|---|
| Маршруты, сессии, права | `backend/app/main.py`, `auth.py` | разбор запроса (Pydantic), пользователь по cookie или Bearer, `require_organizer_of` / `require_participant`, ETag доски, 409 с доской |
| Правила предметной области | `backend/app/service.py` | доска, отклики, назначение и перенос, возврат в очередь, структура набора, CSV. Права здесь не проверяются |
| Хранение | `backend/app/db.py`, `migrations/` | соединение на запрос, `BEGIN IMMEDIATE`, WAL, `busy_timeout`, миграции по номерам |
| Данные | `seed.py`, `synthetic.py`, `users.py` | демо, синтетика, учётные записи из консоли |
| Интерфейс | `frontend/src/` | вход, доска организатора, меню назначения, настройка, страница участника |

## Модель данных

```text
users(id, username UNIQUE, display_name, role organizer|participant, password_hash, salt)
sessions(token PK, user_id, expires_at)
profiles(user_id PK, name, skills JSON, interests)                     — профиль участника
recruitments(id, title, description, status open|closed, organizer_id, board_version, created_at)
teams(id, recruitment_id, name, position, UNIQUE(recruitment_id, name))
role_slots(id, team_id, role, capacity 1..50, position, UNIQUE(team_id, role))   — слот роли
applications(id, recruitment_id, user_id, desired_roles JSON, note, assignment_version, created_at,
             UNIQUE(recruitment_id, user_id))                            — отклик
assignments(application_id PK, slot_id, assigned_by, assigned_at)       — назначение
schema_migrations(version PK, name, applied_at)
```

Ограничения на уровне БД: один отклик человека в наборе (`UNIQUE(recruitment_id, user_id)`), одно назначение на отклик (PK `assignments.application_id`), вместимость от 1 до 50, внешние ключи с `ON DELETE CASCADE` для структуры набора.

## API

| Метод и путь | Кто | Что делает |
|---|---|---|
| `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/me` | все | сессия (HttpOnly cookie `tab_session`, SameSite=Lax, 7 дней) |
| `GET /api/recruitments` | все | организатор — свои наборы, участник — открытые и те, куда откликнулся |
| `POST /api/recruitments`, `PATCH /api/recruitments/{id}` | организатор | создать, переименовать, открыть или закрыть |
| `GET /api/recruitments/{id}/board` | организатор набора | доска: команды → слоты → участники, очередь, сводка, роли, навыки. `ETag`, 304 по `If-None-Match` |
| `POST /api/recruitments/{id}/applications` | участник | отклик: 201, 409 `duplicate_application` / `recruitment_closed`, 422 `unknown_roles` и ошибки полей |
| `GET /api/recruitments/{id}/my` | все | свой отклик, итог назначения, роли набора, профиль |
| `PUT /api/applications/{id}/assignment` `{slot_id, version}` | организатор набора | назначить или перенести: 200 `{changed, free_places, version, board}`, 409 `slot_full` / `version_conflict` / `recruitment_closed` с `board`, 422 `slot_not_in_recruitment` |
| `DELETE /api/applications/{id}/assignment?version=N` | организатор набора | вернуть в очередь: 200 / 409 с `board` |
| `POST /api/recruitments/{id}/teams`, `DELETE /api/teams/{id}`, `POST /api/teams/{id}/slots`, `PATCH`/`DELETE /api/slots/{id}` | организатор набора | структура. 409 `duplicate_team` / `duplicate_slot` / `capacity_below_taken` / `slot_not_empty` / `team_not_empty` |
| `GET /api/recruitments/{id}/export.csv` | организатор набора | `team,role,name,skills,desired_roles`, свободные места и очередь, UTF-8 с BOM |
| `GET /api/health` | все | `{status, schema_version, demo}` — проверка готовности |
| `GET /api/demo/users`, `POST /api/demo/reset` | только `DEMO_MODE=1` | демо-входы, сброс демо (организатор) |

Ошибки правил — `{code, message, field?, board?}` с кодами 401, 403, 404, 409, 422. Ошибки формата — стандартный ответ FastAPI 422 `{detail: [...]}`, интерфейс раскладывает их по полям.

## Назначение (ядро)

```text
BEGIN IMMEDIATE                                      — блокировка записи с начала транзакции
прочитать отклик и статус набора                    — 404 / 409 recruitment_closed
если отклик уже в целевом слоте → COMMIT, changed=false   (повтор безопасен при любой версии)
если assignment_version ≠ version → ROLLBACK, 409 version_conflict
слот принадлежит набору отклика?                     — иначе 422 slot_not_in_recruitment
занято = COUNT(assignments в слоте, кроме этого отклика)
если занято ≥ вместимость → ROLLBACK, 409 slot_full
UPSERT assignments(application_id → slot_id)         — перенос освобождает прежнее место в той же транзакции
assignment_version += 1, board_version += 1
COMMIT → ответ со свободными местами и актуальной доской
```

Права (`require_organizer_of`) проверяются до транзакции: владелец набора не меняется. Возврат в очередь устроен так же (`DELETE`, версия, повтор безопасен). Параллельность проверена тестами на настоящем uvicorn: 8 запросов на одно место дают ровно один успех. Одна карточка в 6 слотов одновременно попадает ровно в один. Смешанная нагрузка (24 запроса × 4 раунда) не нарушает вместимость и не дублирует людей.

## Версии и обновление доски

- `applications.assignment_version` — защита от устаревших действий над конкретной карточкой.
- `recruitments.board_version` — растёт при любом изменении доски (назначение, отклик, структура, статус, сброс). Из неё строится ETag `"board-<id>-v<версия>"`. Ответ `Cache-Control: private, no-cache` заставляет браузер перепроверять доску при каждом опросе: при неизменной доске сервер отвечает 304, не собирая её.
- Интерфейс опрашивает доску каждые 5 с, пока вкладка видна, и сразу при возврате фокуса. Конфликт (409) сразу подменяет доску версией из ответа и показывает баннер.

## Интерфейс

- `App` выбирает вид по роли. Событие `auth-lost` (любой 401) возвращает на вход с объяснением.
- Доска: очередь с фильтром (`board-logic.filterQueue`: все выбранные навыки + текст) и колонки команд. На широком экране колонки прокручиваются сами, чтобы очередь и слоты были видны одновременно при перетаскивании.
- Меню назначения — нативный `<dialog>` с радиокнопками (`slotOptions`: желаемые роли первыми, занятые недоступны). После назначения фокус переходит на кнопку карточки на новом месте, после отмены — на кнопку-источник.
- Кнопки карточки на время запроса — `aria-disabled` (не `disabled`), чтобы фокус не терялся. Если фокус всё же потерян, эффект после отрисовки возвращает его на карточку.
- Объявления для экранных читалок — `role="status"`, ошибки и конфликты — `role="alert"`, ошибки полей — `aria-invalid` + `aria-describedby`.

## Решения и причины

| Решение | Причина |
|---|---|
| stdlib `sqlite3` вместо ORM | явные транзакции `BEGIN IMMEDIATE` и минимум зависимостей. Запросов немного |
| Версия на назначении + `BEGIN IMMEDIATE` | ТЗ: «при записи передавать версию назначения», проверка вместимости без гонок |
| 409 вместе с актуальной доской | ТЗ: «при конфликте вернуть актуальную доску» — клиенту не нужен второй запрос |
| Идемпотентный повтор | потеря ответа при назначении не должна давать ложный конфликт (дефект раунда 2) |
| Cookie-сессии в базе | простое отключение сессий (смена пароля, выход), без секретного ключа подписи в окружении |
| PBKDF2-SHA256, 120 000 итераций (stdlib) | без внешних зависимостей. Вход ~23 мс — приемлемо |
| Один контейнер с API и статикой | ТЗ: один опубликованный порт на localhost. Нет CORS и второго сервиса |
| ETag по `board_version` | опрос раз в 5 с перестал гонять полные 31 КБ при неизменной доске (раунд 4) |
| Порт `127.0.0.1:8205` и `DEMO_MODE` | демо-доступ ограничен локальным профилем |
| Необязательный секрет сборки `extra_ca` | сборка за корпоративным прокси с собственным CA без правки Dockerfile |
