#!/usr/bin/env node
// Собирает тексты лицензий production-зависимостей, чей код попадает в dist/, в public/THIRD_PARTY_LICENSES.txt.
// Запуск: node scripts/third-party-licenses.mjs (выполняется автоматически перед сборкой).
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const lock = JSON.parse(readFileSync('package-lock.json', 'utf8'));
const out = ['Сторонние компоненты, включённые в сборку dist/.', ''];
for (const [key, meta] of Object.entries(lock.packages)) {
  if (!key || meta.dev || meta.optional) continue;
  const dir = key;
  const name = key.replace(/^.*node_modules\//, '');
  const file = ['LICENSE', 'LICENSE.md', 'LICENSE.txt', 'license'].map((f) => join(dir, f)).find((f) => existsSync(f));
  out.push('='.repeat(72), `${name}@${meta.version} — ${meta.license ?? 'лицензия не указана'}`, '='.repeat(72));
  out.push(file ? readFileSync(file, 'utf8').trim() : '(текст лицензии не найден в пакете)', '');
}
writeFileSync('public/THIRD_PARTY_LICENSES.txt', out.join('\n') + '\n');
console.log('public/THIRD_PARTY_LICENSES.txt обновлён');
