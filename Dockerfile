# Сборка: docker compose build (или docker build -t team-assembly-board:local .).
# За корпоративным прокси с собственным корневым сертификатом передайте его необязательным секретом:
#   docker build --secret id=extra_ca,src=/path/to/ca.pem -t team-assembly-board:local .
# Без секрета сборка идёт как обычно.

# Этап 1: сборка интерфейса (React + Vite).
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Этап 2: сервер FastAPI + SQLite, интерфейс раздаётся как статика.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/data/team-board.sqlite3 \
    STATIC_DIR=/app/static
WORKDIR /app
COPY backend/requirements.txt ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=ui /ui/dist ./static
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app:app /data
USER app
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD python -c "import json,urllib.request,sys; r=json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)); sys.exit(0 if r['status']=='ok' else 1)"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
