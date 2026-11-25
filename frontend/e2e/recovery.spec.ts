import { expect, test } from '@playwright/test';
import { assignViaMenu, card, loginOrganizer, resetDemo, slot } from './helpers';

test.beforeEach(async ({ page }) => {
  await resetDemo(page);
});

test('обрыв сети при назначении: понятная ошибка, карточка не зависает, повтор срабатывает', async ({ page }) => {
  await loginOrganizer(page);
  await page.route('**/api/applications/*/assignment', (route) => route.abort('connectionrefused'));
  await card(page, 'Антон Белов').getByRole('button', { name: 'Назначить: Антон Белов' }).click();
  await page.getByRole('dialog').getByRole('radio', { name: /^Альфа — Backend/ }).check();
  await page.getByRole('dialog').getByRole('button', { name: 'Назначить' }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'Сервер недоступен' })).toBeVisible();
  await expect(card(page, 'Антон Белов').getByRole('button', { name: 'Назначить: Антон Белов' })).toBeEnabled();
  await page.unroute('**/api/applications/*/assignment');
  await assignViaMenu(page, 'Антон Белов', 'Альфа', 'Backend');
  await expect(page.getByRole('alert').filter({ hasText: 'Сервер недоступен' })).toHaveCount(0);
});

test('сессия истекла: при следующем действии открывается вход с объяснением', async ({ page, context }) => {
  await loginOrganizer(page);
  await context.clearCookies();
  await card(page, 'Антон Белов').getByRole('button', { name: 'Назначить: Антон Белов' }).click();
  await page.getByRole('dialog').getByRole('radio', { name: /^Альфа — Backend/ }).check();
  await page.getByRole('dialog').getByRole('button', { name: 'Назначить' }).click();
  await expect(page.getByRole('heading', { name: 'Вход', exact: true })).toBeVisible();
  await expect(page.getByText('Сессия закончилась — войдите снова')).toBeVisible();
  await page.getByLabel('Логин').fill('organizer');
  await page.getByLabel('Пароль').fill('organizer-demo');
  await page.getByRole('button', { name: 'Войти', exact: true }).click();
  await expect(slot(page, 'Альфа', 'Backend').getByTestId('card')).toHaveCount(0);
});
