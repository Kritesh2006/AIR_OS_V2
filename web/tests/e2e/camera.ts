import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { BrowserType, Page } from '@playwright/test';

const here = dirname(fileURLToPath(import.meta.url));

/** Launch Chromium whose fake camera shows fixtures/<clip>.mjpeg. */
export async function withCamera(browserType: BrowserType, clip: string, baseURL: string, fn: (page: Page) => Promise<void>) {
  const browser = await browserType.launch({
    args: [
      '--use-fake-ui-for-media-stream',
      '--use-fake-device-for-media-stream',
      `--use-file-for-fake-video-capture=${resolve(here, `../fixtures/${clip}.mjpeg`)}`,
    ],
  });
  try {
    const context = await browser.newContext({ baseURL, permissions: ['camera'] });
    await fn(await context.newPage());
  } finally {
    await browser.close();
  }
}

/** Start AIR and wait until hand tracking is live. */
export async function startAir(page: Page) {
  await page.goto('/');
  await page.getByTestId('start-button').click();
  const html = page.locator('html');
  const { expect } = await import('@playwright/test');
  await expect(html).toHaveAttribute('data-air-phase', 'running', { timeout: 15_000 });
  await expect(html).toHaveAttribute('data-air-tracker', 'ready', { timeout: 20_000 });
}
