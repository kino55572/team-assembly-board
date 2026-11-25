# Ассеты и сторонние материалы

Сторонних изображений, шрифтов и других материалов нет.

| Файл | Происхождение | Права |
|---|---|---|
| `frontend/public/favicon.svg` | нарисован для проекта (доска с колонками, SVG-примитивы) | собственный материал проекта |
| `backend/app/seed.py` — организатор, участники p1…p8, «Осенний хакатон», навыки и интересы | придуманы для проекта | синтетические данные, все имена вымышленные |
| `backend/app/synthetic.py` — «Участник 001…100» | генерируются | синтетические данные |
| Шрифты | системные, не загружаются | — |

## Зависимости и лицензии

Сервер (`backend/requirements.txt`, ставятся в образ, в репозиторий не копируются):

| Пакет | Версия | Лицензия |
|---|---|---|
| fastapi | 0.165.0 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| pydantic / pydantic_core | 2.14.4 / 2.50.5 | MIT |
| uvicorn | 0.54.0 | BSD-3-Clause |
| anyio | 4.16.0 | MIT |
| h11 | 0.16.0 | MIT |
| click | 8.5.1 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| typing_extensions | 4.16.0 | PSF-2.0 |
| typing-inspection, annotated-types, annotated-doc | 0.4.5, 0.8.0, 0.0.7 | MIT |

Тексты лицензий Python-пакетов остаются в образе вместе с пакетами (`site-packages/*/LICENSE*`).

Интерфейс: в собранный `frontend/dist` (и в образ) попадает код `react`, `react-dom`, `scheduler` (MIT). Тексты лицензий собираются в `frontend/public/THIRD_PARTY_LICENSES.txt` → `dist/THIRD_PARTY_LICENSES.txt` скриптом `frontend/scripts/third-party-licenses.mjs` при каждой сборке. Dev-зависимости (Vite, TypeScript, Vitest, Playwright, pytest, httpx) в образ не входят.

Базовые образы: `node:22-alpine` (только этап сборки интерфейса) и `python:3.12-slim` (итоговый образ). Их лицензионные условия — на страницах официальных образов Docker Hub.
