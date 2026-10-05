import { expect, test } from '@playwright/test';
import { startAir, withCamera } from './camera';

/**
 * W2 with REAL hand tracking: the fake camera shows a held fist, so these
 * exercise fist → arming → close selection, confirmation, cancellation and
 * the wait-for-release guard end to end.
 */

test('before any fist: demo windows are shown and nothing is selected', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('start-button').click();
  await expect(page.getByTestId('air-window')).toHaveCount(6);
  await expect(page.getByTestId('selection-overlay')).toBeHidden();
  await expect(page.locator('html')).toHaveAttribute('data-air-mode', 'NORMAL');
});

test('held fist → selection → tap card → ✓ closes exactly that window; held fist cannot re-trigger', async ({ playwright, baseURL }) => {
  await withCamera(playwright.chromium, 'fist', baseURL!, async (page) => {
    await startAir(page);
    const html = page.locator('html');
    await expect(page.getByTestId('air-window')).toHaveCount(6);

    await expect(html).toHaveAttribute('data-air-mode', 'CLOSE_SELECTION', { timeout: 10_000 });
    await expect(page.getByTestId('selection-overlay')).toBeVisible();
    await expect(page.getByTestId('select-card')).toHaveCount(6);
    await expect(page.getByTestId('pod-status')).toContainText(/SELECT|CONFIRM/);

    const music = page.locator('[data-testid="select-card"][data-target-id="music"]');
    await music.click();
    await expect(music).toHaveAttribute('data-locked', 'true');
    await expect(page.getByTestId('pod-status')).toHaveText('AIR • CONFIRM');
    await music.getByTestId('confirm-button').click();

    await expect(page.getByTestId('pod-status')).toHaveText('AIR • CLOSED');
    await expect(page.getByTestId('pod-gesture')).toContainText('Closed Music');
    await expect(page.getByTestId('selection-overlay')).toBeHidden();
    await expect(page.getByTestId('air-window')).toHaveCount(5);
    await expect(page.locator('[data-testid="air-window"][data-window-id="music"]')).toHaveCount(0);

    // The fist is still held: AIR must not open another selection.
    await expect(html).toHaveAttribute('data-air-mode', 'WAIT_FOR_RELEASE');
    await page.waitForTimeout(4000);
    await expect(html).toHaveAttribute('data-air-mode', 'WAIT_FOR_RELEASE');
    await expect(page.getByTestId('air-window')).toHaveCount(5);

    await page.getByTestId('reset-windows').click();
    await expect(page.getByTestId('air-window')).toHaveCount(6);
  });
});

test('Enter confirms a locked card; Esc cancels without closing anything', async ({ playwright, baseURL }) => {
  await withCamera(playwright.chromium, 'fist', baseURL!, async (page) => {
    await startAir(page);
    const html = page.locator('html');
    await expect(html).toHaveAttribute('data-air-mode', 'CLOSE_SELECTION', { timeout: 10_000 });

    await page.keyboard.press('Escape');
    await expect(page.getByTestId('selection-overlay')).toBeHidden();
    await expect(page.getByTestId('pod-status')).toHaveText('AIR • CANCELLED');
    await expect(page.getByTestId('air-window')).toHaveCount(6);
    await page.waitForTimeout(2500);
    await expect(html).toHaveAttribute('data-air-mode', 'WAIT_FOR_RELEASE');
  });
});

test('Enter confirms the locked card', async ({ playwright, baseURL }) => {
  await withCamera(playwright.chromium, 'fist', baseURL!, async (page) => {
    await startAir(page);
    await expect(page.locator('html')).toHaveAttribute('data-air-mode', 'CLOSE_SELECTION', { timeout: 10_000 });
    await page.locator('[data-testid="select-card"][data-target-id="terminal"]').click();
    await page.keyboard.press('Enter');
    await expect(page.locator('[data-testid="air-window"][data-window-id="terminal"]')).toHaveCount(0);
    await expect(page.getByTestId('air-window')).toHaveCount(5);
  });
});

test('Cancel button cancels', async ({ playwright, baseURL }) => {
  await withCamera(playwright.chromium, 'fist', baseURL!, async (page) => {
    await startAir(page);
    await expect(page.locator('html')).toHaveAttribute('data-air-mode', 'CLOSE_SELECTION', { timeout: 10_000 });
    await page.getByTestId('cancel-button').click();
    await expect(page.getByTestId('selection-overlay')).toBeHidden();
    await expect(page.getByTestId('air-window')).toHaveCount(6);
  });
});

test('a pointing hand (no fist) never opens a selection', async ({ playwright, baseURL }) => {
  await withCamera(playwright.chromium, 'pointing_up', baseURL!, async (page) => {
    await startAir(page);
    await expect(page.getByTestId('pod-status')).toHaveText('AIR • HAND', { timeout: 10_000 });
    await page.waitForTimeout(3000);
    await expect(page.locator('html')).toHaveAttribute('data-air-mode', 'NORMAL');
    await expect(page.getByTestId('selection-overlay')).toBeHidden();
  });
});
