import { expect, type Page } from '@playwright/test';

export const ORG = { username: 'organizer', password: 'organizer-demo' };
export const PARTICIPANT_PASSWORD = 'participant-demo';

/** Сброс демо-набора к исходному виду через API (в демо-режиме, от имени организатора). */
export async function resetDemo(page: Page): Promise<void> {
  const r = await page.request.post('/api/auth/login', { data: ORG });
  expect(r.ok()).toBeTruthy();
  const reset = await page.request.post('/api/demo/reset');
  expect(reset.ok()).toBeTruthy();
  await page.request.post('/api/auth/logout');
}

export async function loginAs(page: Page, username: string, password: string): Promise<void> {
  await page.goto('/');
  // Сначала дождаться, что приложение решило, вошли мы или нет: isVisible() не ждёт, и при медленной
  // проверке сессии helper искал поле «Логин» на уже открытом рабочем экране.
  const out = page.getByRole('button', { name: 'Выйти' });
  await expect(out.or(page.getByLabel('Логин'))).toBeVisible();
  if (await out.isVisible()) await out.click();
  await page.getByLabel('Логин').fill(username);
  await page.getByLabel('Пароль').fill(password);
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByTestId('whoami')).toBeVisible();
}

export async function loginOrganizer(page: Page): Promise<void> {
  await loginAs(page, ORG.username, ORG.password);
  await expect(page.getByRole('heading', { name: /Осенний хакатон/ })).toBeVisible();
}

export const slot = (page: Page, team: string, role: string) => page.locator(`[data-testid="slot"][data-slot="${team}/${role}"]`);
export const card = (page: Page, name: string) => page.locator(`[data-testid="card"][data-name="${name}"]`);

/** Назначение через меню (клавиатурный путь): «Назначить…» → радиокнопка «Команда — Роль» → «Назначить». */
export async function assignViaMenu(page: Page, name: string, team: string, role: string): Promise<void> {
  await card(page, name).getByRole('button', { name: new RegExp(`^(Назначить|Перенести): ${name}$`) }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByRole('radio', { name: new RegExp(`^${team} — ${role}`) }).check();
  await dialog.getByRole('button', { name: /^(Назначить|Перенести)$/ }).click();
  await expect(slot(page, team, role).locator(`[data-name="${name}"]`)).toBeVisible();
}
