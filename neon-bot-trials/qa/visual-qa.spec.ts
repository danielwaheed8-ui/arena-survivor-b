import { expect, test, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

/**
 * Visual QA suite. For every core screen it verifies:
 *  - the screen renders without console errors,
 *  - key controls are visible and inside the viewport (no clipping),
 *  - canvases actually paint pixels (no blank/black renders),
 * and captures a screenshot artifact per viewport for human review.
 */

const ARTIFACTS = path.join(__dirname, 'artifacts');
fs.mkdirSync(ARTIFACTS, { recursive: true });

function shotPath(page: Page, name: string): string {
  const project = test.info().project.name;
  return path.join(ARTIFACTS, `${name}-${project}.png`);
}

async function expectNoOverlapWithViewport(page: Page, selector: string): Promise<void> {
  const box = await page.locator(selector).first().boundingBox();
  expect(box, `${selector} has a bounding box`).not.toBeNull();
  const viewport = page.viewportSize()!;
  expect(box!.x, `${selector} not clipped left`).toBeGreaterThanOrEqual(-1);
  expect(box!.y, `${selector} not clipped top`).toBeGreaterThanOrEqual(-1);
  expect(box!.x + box!.width, `${selector} not clipped right`).toBeLessThanOrEqual(viewport.width + 1);
}

/** Counts distinct sampled colors on a canvas — a blank canvas has 1. */
async function canvasColorCount(page: Page, testId: string): Promise<number> {
  return page.evaluate((id) => {
    const canvas = document.querySelector(`canvas[data-testid="${id}"]`) as HTMLCanvasElement | null;
    if (!canvas || canvas.width === 0) return 0;
    const ctx = canvas.getContext('2d');
    if (!ctx) return 0;
    const { width, height } = canvas;
    const data = ctx.getImageData(0, 0, width, height).data;
    const colors = new Set<number>();
    const step = Math.max(4, Math.floor((width * height) / 4000)) * 4;
    for (let i = 0; i < data.length; i += step) {
      colors.add((data[i] << 16) | (data[i + 1] << 8) | data[i + 2]);
    }
    return colors.size;
  }, testId);
}

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() === 'error') errors.push(`console: ${msg.text()}`);
  });
  return errors;
}

test.describe('landing page', () => {
  test('renders hero, live sim canvas and CTAs', async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto('/');
    await expect(page.getByTestId('hero-kicker')).toBeVisible();
    await expect(page.getByTestId('cta-simulate')).toBeVisible();
    await expectNoOverlapWithViewport(page, '[data-testid="cta-simulate"]');
    // Hero canvas must be actively painting the demo simulation.
    await page.waitForTimeout(1500);
    expect(await canvasColorCount(page, 'hero-sim')).toBeGreaterThan(20);
    await page.screenshot({ path: shotPath(page, '01-landing'), fullPage: true });
    expect(errors).toEqual([]);
  });
});

test.describe('arena select', () => {
  test('shows all six arena cards with previews', async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto('/arenas');
    for (const id of ['first-drive', 'ramp-lab', 'gap-run', 'balance-bridge', 'wind-tunnel', 'neon-gauntlet']) {
      await expect(page.getByTestId(`arena-card-${id}`)).toBeVisible();
    }
    await page.waitForTimeout(600);
    expect(await canvasColorCount(page, 'arena-preview')).toBeGreaterThan(3);
    await page.screenshot({ path: shotPath(page, '02-arenas'), fullPage: true });
    expect(errors).toEqual([]);
  });
});

test.describe('robot builder', () => {
  test('palette, canvas, tuning and save all work', async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto('/builder');
    await expect(page.getByTestId('builder-canvas')).toBeVisible();
    await expect(page.getByTestId('palette-wheel')).toBeVisible();
    await expect(page.getByTestId('robot-name')).toBeVisible();
    await page.waitForTimeout(800);
    expect(await canvasColorCount(page, 'builder-canvas')).toBeGreaterThan(10);

    // Interactive check: arm a wheel and mount it on the canvas.
    const before = await page.getByTestId('palette-wheel').locator('.mono-value').textContent();
    await page.getByTestId('palette-wheel').click();
    const canvas = page.getByTestId('builder-canvas');
    const box = (await canvas.boundingBox())!;
    await canvas.click({ position: { x: box.width / 2 - 40, y: box.height / 2 + 30 } });
    await expect(page.getByTestId('tuning-panel')).toBeVisible();
    const after = await page.getByTestId('palette-wheel').locator('.mono-value').textContent();
    expect(after).not.toBe(before);

    // Save to garage produces a confirmation.
    await page.getByTestId('save-robot').click();
    await expect(page.getByTestId('builder-notice')).toBeVisible();

    await page.screenshot({ path: shotPath(page, '03-builder'), fullPage: true });
    expect(errors).toEqual([]);
  });
});

test.describe('simulation', () => {
  test('launches a run, HUD updates, controls respond', async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto('/simulate?arena=first-drive');
    await expect(page.getByTestId('sim-canvas')).toBeVisible();
    await expect(page.getByTestId('play-pause')).toBeVisible();
    await expectNoOverlapWithViewport(page, '[data-testid="play-pause"]');
    await page.waitForTimeout(700);
    expect(await canvasColorCount(page, 'sim-canvas')).toBeGreaterThan(20);

    // Launch and verify simulated time advances.
    await page.getByTestId('play-pause').click();
    await page.waitForTimeout(1600);
    const time = await page.locator('.mono-value').first().textContent();
    expect(parseFloat(time ?? '0')).toBeGreaterThan(0.5);

    await page.screenshot({ path: shotPath(page, '04-simulate') });

    // Speed control + pause must respond.
    await page.getByTestId('speed-2').click();
    await page.getByTestId('play-pause').click();
    await expect(page.getByTestId('play-pause')).toContainText(/Resume/i);
    expect(errors).toEqual([]);
  });

  test('cinematic mode hides chrome and shows the stage', async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto('/simulate?arena=neon-gauntlet');
    await page.getByTestId('play-pause').click();
    await page.getByTestId('cinematic-toggle').click();
    await expect(page.locator('nav.app-nav')).toHaveCSS('opacity', '0', { timeout: 5000 });
    await expect(page.getByTestId('arena-select')).toHaveCount(0);
    await page.waitForTimeout(900);
    expect(await canvasColorCount(page, 'sim-canvas')).toBeGreaterThan(20);
    await page.screenshot({ path: shotPath(page, '05-cinematic') });
    await page.getByTestId('cinematic-toggle').click();
    await expect(page.getByTestId('arena-select')).toBeVisible();
    expect(errors).toEqual([]);
  });

  test('a full run produces results and a saved replay', async ({ page }) => {
    test.slow();
    const errors = collectErrors(page);
    await page.goto('/simulate?arena=first-drive');
    // Skyhopper finishes First Drive in ~3s simulated; 4× speed keeps it quick.
    await page.getByTestId('robot-select').selectOption('preset-skyhopper');
    await page.getByTestId('speed-4').click();
    await page.getByTestId('play-pause').click();
    await expect(page.getByTestId('results-modal')).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId('final-score')).not.toHaveText('0');
    await expect(page.getByTestId('grade')).toBeVisible();
    await page.screenshot({ path: shotPath(page, '06-results') });

    // Replay flows into the archive viewer.
    await page.getByTestId('watch-replay').click();
    await page.waitForURL(/\/replays\?run=/);
    await expect(page.getByTestId('replay-canvas')).toBeVisible();
    await expect(page.getByTestId('replay-controls')).toBeVisible();
    await page.waitForTimeout(1200);
    expect(await canvasColorCount(page, 'replay-canvas')).toBeGreaterThan(20);
    await page.getByTestId('replay-scrub').fill('0.5');
    await expect(page.getByTestId('replay-play')).toContainText(/Play/i);
    await page.screenshot({ path: shotPath(page, '07-replay') });
    expect(errors).toEqual([]);
  });
});

test.describe('garage', () => {
  test('shows presets and saved robots', async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto('/robots');
    await expect(page.getByTestId('preset-card-preset-volt-roller')).toBeVisible();
    await page.waitForTimeout(800);
    expect(await canvasColorCount(page, 'robot-preview')).toBeGreaterThan(5);
    await page.screenshot({ path: shotPath(page, '08-garage'), fullPage: true });
    expect(errors).toEqual([]);
  });
});

test.describe('system self-check', () => {
  test('all runtime diagnostics pass', async ({ page }) => {
    const errors = collectErrors(page);
    await page.goto('/qa');
    await expect(page.locator('[data-qa-status]')).toBeVisible({ timeout: 20_000 });
    await expect(page.locator('[data-qa-status]')).toHaveAttribute('data-qa-status', 'pass');
    await page.screenshot({ path: shotPath(page, '09-selfcheck'), fullPage: true });
    expect(errors).toEqual([]);
  });
});

test.describe('layout integrity', () => {
  test('no horizontal overflow on any core screen', async ({ page }) => {
    for (const route of ['/', '/arenas', '/builder', '/simulate', '/replays', '/robots', '/qa']) {
      await page.goto(route);
      await page.waitForTimeout(400);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${route} horizontal overflow`).toBeLessThanOrEqual(2);
    }
  });
});
