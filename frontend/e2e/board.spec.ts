import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { assignViaMenu, card, loginAs, loginOrganizer, PARTICIPANT_PASSWORD, resetDemo, slot } from './helpers';

test.beforeEach(async ({ page }) => {
  await resetDemo(page);
});

test('приёмка ТЗ: две команды, одна роль открыта, перенос, повторное назначение запрещено', async ({ page, context }) => {
  await loginOrganizer(page);
  await expect(page.getByTestId('queue').getByTestId('card')).toHaveCount(8);

  await assignViaMenu(page, 'Антон Белов', 'Альфа', 'Backend');
  await assignViaMenu(page, 'Вика Гусева', 'Альфа', 'Frontend');
  await assignViaMenu(page, 'Денис Егоров', 'Альфа', 'Дизайн');
  await assignViaMenu(page, 'Илья Ковалёв', 'Бета', 'Backend');
  // Перетаскивание мышью тоже работает.
  await card(page, 'Лена Морозова').dragTo(slot(page, 'Бета', 'Frontend'));
  await expect(slot(page, 'Бета', 'Frontend').locator('[data-name="Лена Морозова"]')).toBeVisible();

  await expect(page.getByTestId('summary-filled')).toContainText('Заполнено мест: 5 из 6');
  await expect(page.getByTestId('open-roles')).toHaveText('Незакрытые роли: Бета — Аналитик');

  // Вторая вкладка того же организатора со старой версией доски.
  const stale = await context.newPage();
  await stale.goto('/');
  await expect(slot(stale, 'Альфа', 'Backend').locator('[data-name="Антон Белов"]')).toBeVisible();
  // «Старая» вкладка не перечитывает доску сама: её чтения перехватываются.
  await stale.route('**/api/recruitments/*/board', (route) => route.abort());

  // Перенос: Антон из Альфа/Backend в Бета/Аналитик, прежнее место освобождается.
  await assignViaMenu(page, 'Антон Белов', 'Бета', 'Аналитик');
  await expect(slot(page, 'Альфа', 'Backend').locator('[data-testid="card"]')).toHaveCount(0);
  await expect(page.getByTestId('open-roles')).toHaveText('Незакрытые роли: Альфа — Backend');
  await expect(page.getByTestId('announcer')).toContainText('Антон Белов → Бета, Аналитик');

  // Повторное изменение того же человека из устаревшей вкладки (там Антон ещё в Альфа/Backend) — конфликт версии.
  await stale.getByRole('button', { name: 'В очередь: Антон Белов' }).click();
  await expect(stale.getByTestId('conflict')).toContainText('Карточку уже изменили');
  await expect(slot(stale, 'Бета', 'Аналитик').locator('[data-name="Антон Белов"]')).toBeVisible();
  await expect(slot(stale, 'Альфа', 'Backend').locator('[data-testid="card"]')).toHaveCount(0);
  await stale.close();

  // После перезагрузки состав тот же: всё хранится на сервере.
  await page.reload();
  await expect(slot(page, 'Бета', 'Аналитик').locator('[data-name="Антон Белов"]')).toBeVisible();
  await expect(page.getByTestId('summary-filled')).toContainText('Заполнено мест: 5 из 6');
});

test('занятый слот: место недоступно в меню и при перетаскивании возвращается конфликт', async ({ page }) => {
  await loginOrganizer(page);
  await assignViaMenu(page, 'Антон Белов', 'Альфа', 'Backend');
  await card(page, 'Илья Ковалёв').getByRole('button', { name: 'Назначить: Илья Ковалёв' }).click();
  await expect(page.getByRole('dialog').getByRole('radio', { name: /^Альфа — Backend/ })).toBeDisabled();
  await page.getByRole('dialog').getByRole('button', { name: 'Отмена' }).click();
  await card(page, 'Илья Ковалёв').dragTo(slot(page, 'Альфа', 'Backend'));
  await expect(page.getByTestId('conflict')).toContainText('уже занято');
  await expect(slot(page, 'Альфа', 'Backend').locator('[data-testid="card"]')).toHaveCount(1);
  await expect(page.getByTestId('queue').locator('[data-name="Илья Ковалёв"]')).toBeVisible();
});

test('участник видит итог своего назначения, но не доску', async ({ page, browser }) => {
  await loginAs(page, 'p1', PARTICIPANT_PASSWORD);
  await expect(page.getByTestId('my-result')).toContainText('Ваша заявка в очереди');
  const rid = (await (await page.request.get('/api/recruitments')).json()).recruitments[0].id;
  expect((await page.request.get(`/api/recruitments/${rid}/board`)).status()).toBe(403);

  const orgCtx = await browser.newContext();
  const org = await orgCtx.newPage();
  await loginOrganizer(org);
  await assignViaMenu(org, 'Антон Белов', 'Альфа', 'Backend');
  await orgCtx.close();

  await page.reload();
  await expect(page.getByTestId('my-result')).toContainText('Вы в команде «Альфа», роль — Backend');
});

test('фильтр очереди по навыкам и поиску', async ({ page }) => {
  await loginOrganizer(page);
  await page.getByRole('group', { name: 'Навыки' }).getByText('Figma', { exact: true }).click();
  await expect(page.getByTestId('queue').getByTestId('card')).toHaveCount(2);
  await page.getByRole('group', { name: 'Навыки' }).getByText('UX-исследования', { exact: true }).click();
  await expect(page.getByTestId('queue').getByTestId('card')).toHaveCount(1);
  await page.getByRole('button', { name: 'Сбросить фильтр' }).click();
  await page.getByLabel('Поиск').fill('мобильные');
  await expect(page.getByTestId('queue').getByTestId('card')).toHaveCount(2);
});

test('экспорт состава в CSV', async ({ page }) => {
  await loginOrganizer(page);
  await assignViaMenu(page, 'Антон Белов', 'Альфа', 'Backend');
  const [dl] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Экспорт состава CSV' }).click()]);
  const lines = readFileSync(await dl.path(), 'utf8').replace(/^﻿/, '').trim().split('\r\n');
  expect(lines[0]).toBe('team,role,name,skills,desired_roles');
  expect(lines[1]).toBe('Альфа,Backend,Антон Белов,"Python, FastAPI, SQL",Backend');
});

test('новый набор: команда, роль, отклик участника с проверкой полей', async ({ page, browser }) => {
  const title = `Весенний интенсив ${Date.now() % 100000}`;
  await loginOrganizer(page);
  await page.getByText('Настройка набора').click();
  await page.getByLabel('Открыть новый набор').fill(title);
  await page.getByRole('button', { name: 'Создать набор' }).click();
  await expect(page.getByRole('heading', { name: new RegExp(title) })).toBeVisible();
  await page.getByLabel('Новая команда').fill('Гамма');
  await page.getByRole('button', { name: 'Добавить команду' }).click();
  await page.getByRole('button', { name: 'Добавить роль' }).click();
  await expect(page.getByText('Введите роль')).toBeVisible();
  await page.getByLabel('Новая роль').fill('QA');
  await page.getByLabel('Мест').fill('2');
  await page.getByRole('button', { name: 'Добавить роль' }).click();
  await expect(slot(page, 'Гамма', 'QA')).toBeVisible();
  await page.getByLabel('Новая роль').fill('QA');
  await page.getByRole('button', { name: 'Добавить роль' }).click();
  await expect(page.getByText('Роль «QA» в этой команде уже есть')).toBeVisible();

  const pCtx = await browser.newContext();
  const p = await pCtx.newPage();
  await loginAs(p, 'p2', PARTICIPANT_PASSWORD);
  await p.getByLabel('Набор').selectOption({ label: title });
  await expect(p.getByRole('heading', { name: 'Откликнуться' })).toBeVisible();
  await p.getByLabel('Имя на карточке').fill('');
  await p.getByRole('button', { name: 'Отправить отклик' }).click();
  await expect(p.getByText('Введите имя')).toBeVisible();
  await expect(p.getByLabel('Имя на карточке')).toBeFocused();
  await p.getByLabel('Имя на карточке').fill('Вика Г.');
  await p.getByLabel('QA').check();
  await p.getByRole('button', { name: 'Отправить отклик' }).click();
  await expect(p.getByTestId('my-result')).toContainText('Ваша заявка в очереди');
  await pCtx.close();

  await page.getByRole('button', { name: 'Обновить' }).click();
  await expect(page.getByTestId('queue').locator('[data-name="Вика Г."]')).toBeVisible();
  // Демо-набор не затронут.
  await page.getByLabel('Набор', { exact: true }).selectOption({ index: 0 });
  await expect(page.getByRole('heading', { name: /Осенний хакатон/ })).toBeVisible();
});

test('неверный пароль показывается у поля', async ({ page }) => {
  await page.goto('/');
  await page.getByLabel('Логин').fill('organizer');
  await page.getByLabel('Пароль').fill('wrong');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(page.getByText('Неверный логин или пароль')).toBeVisible();
  await expect(page.getByLabel('Пароль')).toHaveAttribute('aria-invalid', 'true');
  await page.getByRole('button', { name: /Ольга Организаторова/ }).click();
  await expect(page.getByTestId('whoami')).toContainText('организатор');
});
