import { expect, test } from '@playwright/test';
import { loginOrganizer } from './helpers';

// Нужен синтетический набор: docker compose exec app python -m app.synthetic 100
test('100 откликов: отрисовка доски, назначение через меню, опрос с 304', async ({ page }) => {
  test.setTimeout(90_000);
  await loginOrganizer(page);
  const select = page.getByLabel('Набор', { exact: true });
  const options = await select.locator('option').allTextContents();
  const synthetic = options.find((o) => o.startsWith('Синтетика 100'));
  test.skip(!synthetic, 'нет набора «Синтетика 100»: docker compose exec app python -m app.synthetic 100');

  await page.evaluate(() => {
    const w = window as unknown as { __ev: number[]; __lt: number[] };
    w.__ev = [];
    w.__lt = [];
    new PerformanceObserver((l) => l.getEntries().forEach((e) => w.__ev.push(Math.round(e.duration)))).observe({ type: 'event', durationThreshold: 16 } as PerformanceObserverInit);
    new PerformanceObserver((l) => l.getEntries().forEach((e) => w.__lt.push(Math.round(e.duration)))).observe({ type: 'longtask' });
  });
  // Сырые коды ответов сервера из CDP: page.on('response') показывает перепроверенный по ETag ответ как 200 из кэша.
  const statuses: number[] = [];
  const boardRequests = new Set<string>();
  const cdp = await page.context().newCDPSession(page);
  await cdp.send('Network.enable');
  cdp.on('Network.requestWillBeSent', (e) => {
    if (/\/api\/recruitments\/\d+\/board$/.test(new URL(e.request.url).pathname)) boardRequests.add(e.requestId);
  });
  cdp.on('Network.responseReceivedExtraInfo', (e) => {
    if (boardRequests.has(e.requestId)) statuses.push(e.statusCode);
  });

  const t0 = Date.now();
  await select.selectOption({ label: synthetic as string });
  await expect(page.getByTestId('queue').getByTestId('card').first()).toBeVisible();
  const switchMs = Date.now() - t0;
  const cards = await page.getByTestId('card').count();
  const dom = await page.evaluate(() => document.querySelectorAll('*').length);
  const take = () =>
    page.evaluate(() => {
      const w = window as unknown as { __ev: number[]; __lt: number[] };
      const r = { worstEventMs: Math.max(0, ...w.__ev), longestTaskMs: Math.max(0, ...w.__lt) };
      w.__ev = [];
      w.__lt = [];
      return r;
    });
  const switchPerf = await take();

  // Назначение через меню на доске из 100 карточек и 50 слотов.
  const first = page.getByTestId('queue').getByTestId('card').first();
  const name = (await first.getAttribute('data-name')) as string;
  await first.getByRole('button', { name: `Назначить: ${name}` }).click();
  const radios = page.getByRole('dialog').getByRole('radio');
  const radioCount = await radios.count();
  await page.getByRole('dialog').getByRole('button', { name: 'Назначить' }).click();
  await expect(page.locator(`[data-testid="slot"] [data-name="${name}"]`)).toBeVisible();
  const assignPerf = await take();

  // Опрос без изменений: браузер перепроверяет по ETag и получает 304. Первый опрос после назначения
  // может прийти с 200 (версия доски выросла), дальше — только 304.
  await page.waitForTimeout(6_000);
  statuses.length = 0;
  await page.waitForTimeout(11_000);
  const result = { cards, dom, switchMs, switchPerf, radioCount, assignPerf, pollStatuses: statuses };
  console.log(`PERF205-UI ${JSON.stringify(result)}`);
  expect(cards).toBe(100);
  expect(statuses.length).toBeGreaterThanOrEqual(2);
  expect(statuses.every((s) => s === 304)).toBe(true);
});
