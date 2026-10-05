import { expect, test, type Page } from '@playwright/test';

const phase = (page: Page) => page.locator('html').getAttribute('data-air-phase');

test('Start AIR → camera permission → live Pod', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('start-button')).toBeVisible();
  await expect(page.getByTestId('pod')).toBeHidden();

  await page.getByTestId('start-button').click();

  await expect(page.locator('html')).toHaveAttribute('data-air-phase', 'running');
  await expect(page.getByTestId('start-button')).toBeHidden();
  await expect(page.getByTestId('pod')).toBeVisible();
  await expect(page.getByTestId('pod-status')).toHaveText('AIR • READY');

  // The Pod's own <video> is actually playing the camera stream.
  await expect
    .poll(() => page.getByTestId('pod-video').evaluate((v: HTMLVideoElement) => !!v.srcObject && !v.paused && v.videoWidth > 0))
    .toBe(true);
});

test('Stop releases the camera and returns to Start', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('start-button').click();
  await expect(page.locator('html')).toHaveAttribute('data-air-phase', 'running');

  await page.getByTestId('pod-stop').click();

  await expect(page.locator('html')).toHaveAttribute('data-air-phase', 'idle');
  await expect(page.getByTestId('start-message')).toContainText('Camera is off');
  await expect(page.getByTestId('pod-video')).toHaveJSProperty('srcObject', null);
});

test('a denied camera is explained and can be retried', async ({ page }) => {
  await page.addInitScript(() => {
    navigator.mediaDevices.getUserMedia = () =>
      Promise.reject(Object.assign(new Error('denied'), { name: 'NotAllowedError' }));
  });
  await page.goto('/');
  await page.getByTestId('start-button').click();

  await expect(page.locator('html')).toHaveAttribute('data-air-phase', 'denied');
  await expect(page.getByTestId('start-message')).toContainText('Camera access was blocked');
  await expect(page.getByTestId('start-button')).toHaveText('Try again');
});

test('hiding the tab pauses AIR and releases the camera; returning resumes', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('start-button').click();
  await expect(page.locator('html')).toHaveAttribute('data-air-phase', 'running');

  const setVisibility = (state: 'hidden' | 'visible') =>
    page.evaluate((s) => {
      Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => s });
      document.dispatchEvent(new Event('visibilitychange'));
    }, state);

  await setVisibility('hidden');
  expect(await phase(page)).toBe('paused');
  await expect(page.getByTestId('pod-status')).toHaveText('AIR • PAUSED');
  await expect(page.getByTestId('pod-video')).toHaveJSProperty('srcObject', null);

  await setVisibility('visible');
  await expect(page.locator('html')).toHaveAttribute('data-air-phase', 'running');
});

test('privacy dialog opens from the start screen', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('privacy-link').click();
  await expect(page.getByTestId('privacy-dialog')).toBeVisible();
  await expect(page.getByTestId('privacy-dialog')).toContainText('No video or images are uploaded');
  await page.getByTestId('privacy-close').click();
  await expect(page.getByTestId('privacy-dialog')).toBeHidden();
});

test('production build: CSP present, no third-party requests, no console errors', async ({ page }) => {
  const foreign: string[] = [];
  const errors: string[] = [];
  page.on('request', (r) => {
    const url = new URL(r.url());
    if (!['localhost', '127.0.0.1'].includes(url.hostname) && !['data:', 'blob:'].includes(url.protocol)) foreign.push(r.url());
  });
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()));
  page.on('pageerror', (e) => errors.push(e.message));

  await page.goto('/');
  const csp = await page.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content');
  expect(csp).toContain("default-src 'self'");
  expect(csp).toContain("connect-src 'self'");

  await page.getByTestId('start-button').click();
  await expect(page.locator('html')).toHaveAttribute('data-air-phase', 'running');
  await page.waitForTimeout(1500);

  expect(foreign).toEqual([]);
  expect(errors).toEqual([]);
});
