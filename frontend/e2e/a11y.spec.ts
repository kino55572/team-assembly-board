import { expect, test, type Page } from '@playwright/test';
import { card, loginAs, loginOrganizer, ORG, PARTICIPANT_PASSWORD, resetDemo, slot } from './helpers';

test.beforeEach(async ({ page }) => {
  await resetDemo(page);
});

async function activeLabel(page: Page): Promise<string | null> {
  return page.evaluate(() => {
    const el = document.activeElement as HTMLElement | null;
    if (!el || el === document.body) return null;
    return (el.getAttribute('aria-label') ?? el.textContent ?? '').trim();
  });
}

/** Назначение только клавиатурой: Tab до кнопки, Enter, стрелки по радиокнопкам, Enter. */
async function keyboardAssign(page: Page, name: string, team: string, role: string): Promise<void> {
  const btn = card(page, name).getByRole('button', { name: `Назначить: ${name}` });
  await btn.focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog');
  await expect(dialog).toBeVisible();
  const target = dialog.getByRole('radio', { name: new RegExp(`^${team} — ${role}`) });
  // Стрелками до нужного варианта (не больше числа вариантов).
  for (let i = 0; i < 8 && !(await target.isChecked()); i += 1) await page.keyboard.press('ArrowDown');
  await expect(target).toBeChecked();
  await page.keyboard.press('Enter');
  await expect(slot(page, team, role).locator(`[data-name="${name}"]`)).toBeVisible();
}

test('команда собирается только клавиатурой, фокус следует за карточкой', async ({ page }) => {
  await loginOrganizer(page);
  await keyboardAssign(page, 'Антон Белов', 'Альфа', 'Backend');
  await expect.poll(() => activeLabel(page)).toBe('Перенести: Антон Белов');
  await keyboardAssign(page, 'Вика Гусева', 'Альфа', 'Frontend');
  await keyboardAssign(page, 'Денис Егоров', 'Альфа', 'Дизайн');
  await expect(page.getByRole('heading', { name: /Альфа/ })).toContainText('3/3');
  await expect(page.getByTestId('announcer')).toContainText('Денис Егоров → Альфа, Дизайн');
  // Esc закрывает меню и возвращает фокус на кнопку.
  const btn = card(page, 'Илья Ковалёв').getByRole('button', { name: 'Назначить: Илья Ковалёв' });
  await btn.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(btn).toBeFocused();
});

test('конфликт при назначении с клавиатуры: доска восстанавливается, фокус не теряется', async ({ page, browser }) => {
  await loginOrganizer(page);
  const btn = card(page, 'Илья Ковалёв').getByRole('button', { name: 'Назначить: Илья Ковалёв' });
  await btn.focus();
  await page.keyboard.press('Enter');
  const dialog = page.getByRole('dialog');
  const target = dialog.getByRole('radio', { name: /^Бета — Backend/ });
  for (let i = 0; i < 8 && !(await target.isChecked()); i += 1) await page.keyboard.press('ArrowDown');
  // Пока меню открыто, другой организатор (вторая сессия) занимает это место.
  const other = await browser.newContext();
  const api = other.request;
  await api.post(new URL('/api/auth/login', page.url()).toString(), { data: ORG });
  const rid = (await (await api.get(new URL('/api/recruitments', page.url()).toString())).json()).recruitments[0].id;
  const board = await (await api.get(new URL(`/api/recruitments/${rid}/board`, page.url()).toString())).json();
  const anton = board.queue.find((c: { name: string }) => c.name === 'Антон Белов');
  const betaBackend = board.teams.find((t: { name: string }) => t.name === 'Бета').slots.find((s: { role: string }) => s.role === 'Backend');
  await api.put(new URL(`/api/applications/${anton.id}/assignment`, page.url()).toString(), { data: { slot_id: betaBackend.id, version: anton.version } });
  await other.close();

  await page.keyboard.press('Enter');
  await expect(page.getByTestId('conflict')).toContainText('уже занято');
  await expect(slot(page, 'Бета', 'Backend').locator('[data-name="Антон Белов"]')).toBeVisible();
  await expect(page.getByTestId('queue').locator('[data-name="Илья Ковалёв"]')).toBeVisible();
  await expect.poll(() => activeLabel(page)).toBe('Назначить: Илья Ковалёв');
});

for (const width of [360, 320]) {
  test(`узкий экран ${width}px: доска, вход и страница участника без горизонтальной прокрутки`, async ({ page }) => {
    await page.setViewportSize({ width, height: 780 });
    await page.goto('/');
    expect(await page.evaluate(() => document.documentElement.scrollWidth), 'вход').toBeLessThanOrEqual(width);
    await loginOrganizer(page);
    expect(await page.evaluate(() => document.documentElement.scrollWidth), 'доска').toBeLessThanOrEqual(width);
    await page.getByText('Настройка набора').click();
    expect(await page.evaluate(() => document.documentElement.scrollWidth), 'настройка').toBeLessThanOrEqual(width);
    await loginAs(page, 'p1', PARTICIPANT_PASSWORD);
    expect(await page.evaluate(() => document.documentElement.scrollWidth), 'участник').toBeLessThanOrEqual(width);
  });
}

test('узкий экран: порядок фокуса совпадает с порядком на экране', async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 780 });
  await loginOrganizer(page);
  await page.reload();
  await expect(page.getByTestId('whoami')).toBeVisible();
  const stops: Array<{ y: number; t: string }> = [];
  for (let i = 0; i < 40; i += 1) {
    await page.keyboard.press('Tab');
    const s = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      let inner = 0;
      for (let n = el.parentElement; n; n = n.parentElement) inner += n.scrollTop;
      return { y: el.getBoundingClientRect().top + window.scrollY + inner - document.documentElement.scrollTop, t: (el.getAttribute('aria-label') ?? el.textContent ?? '').trim().slice(0, 30) };
    });
    if (!s) break;
    stops.push(s);
  }
  const jumps = stops.slice(1).filter((s, i) => s.y < stops[i].y - 60).map((s) => s.t);
  expect(stops.length).toBeGreaterThan(20);
  expect(jumps).toEqual([]);
});

test('кнопки, поля и чипы навыков не меньше 36–40 px', async ({ page }) => {
  await loginOrganizer(page);
  const small = await page.evaluate(() =>
    [...document.querySelectorAll('button, input:not([type=checkbox]):not([type=radio]), select, a.btn, label.chip--toggle')]
      .map((el) => ({ t: (el.getAttribute('aria-label') ?? el.textContent ?? '').trim().slice(0, 25), h: el.getBoundingClientRect().height }))
      .filter((x) => x.h > 0 && x.h < 36),
  );
  expect(small).toEqual([]);
});
