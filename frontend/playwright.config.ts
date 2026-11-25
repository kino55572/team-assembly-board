import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { defineConfig, devices } from '@playwright/test';

// По умолчанию тесты идут против запущенного контейнера: docker compose up -d → http://127.0.0.1:8205.
// E2E_BASE_URL — другой адрес. E2E_LOCAL=1 — поднять сервер из backend/ без Docker
// (нужны зависимости из backend/requirements-dev.txt и собранный интерфейс npm run build).
const local = process.env.E2E_LOCAL === '1';
const LOCAL_URL = 'http://127.0.0.1:8215';
const baseURL = process.env.E2E_BASE_URL ?? (local ? LOCAL_URL : 'http://127.0.0.1:8205');

const backend = resolve(import.meta.dirname, '..', 'backend');
const venvPython = join(backend, '.venv', 'bin', 'python');
const python = process.env.PYTHON ?? (existsSync(venvPython) ? venvPython : 'python3');

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: { ...devices['Desktop Chrome'], baseURL, locale: 'ru-RU', trace: 'retain-on-failure' },
  webServer: local
    ? {
        command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port 8215`,
        cwd: backend,
        url: `${LOCAL_URL}/api/health`,
        reuseExistingServer: false,
        timeout: 30_000,
        env: {
          DB_PATH: join(mkdtempSync(join(tmpdir(), 'tab-e2e-')), 'e2e.sqlite3'),
          STATIC_DIR: resolve(import.meta.dirname, 'dist'),
          DEMO_MODE: '1',
          SEED_DEMO: '1',
        },
      }
    : undefined,
});
