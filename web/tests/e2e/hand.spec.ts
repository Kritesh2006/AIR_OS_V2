import { expect, test } from '@playwright/test';
import { withCamera } from './camera';

/**
 * Real MediaPipe hand tracking on real hand photos fed in as the camera
 * (Apache-2.0 test images from the MediaPipe project, see fixtures/NOTICE).
 * Each clip needs its own browser launch because the fake camera file is a
 * launch flag.
 */

const cases = [
  { clip: 'pointing_up', gesture: 'POINT' },
  { clip: 'victory', gesture: 'PEACE' },
  { clip: 'fist', gesture: 'FIST' },
] as const;

for (const { clip, gesture } of cases) {
  test(`${clip}: detects the hand, shows ${gesture}, and drives the AIR cursor`, async ({ playwright, baseURL }) => {
    await withCamera(playwright.chromium, clip, baseURL!, async (page) => {
      const errors: string[] = [];
      page.on('pageerror', (e) => errors.push(e.message));
      await page.goto('/');
      await page.getByTestId('start-button').click();

      const html = page.locator('html');
      await expect(html).toHaveAttribute('data-air-phase', 'running', { timeout: 15_000 });
      await expect(html).toHaveAttribute('data-air-tracker', 'ready', { timeout: 20_000 });
      // A held fist also starts the W2 close flow, so the Pod may already
      // have moved on from HAND to CLOSE? / SELECT.
      await expect(page.getByTestId('pod-status')).toHaveText(/AIR • (HAND|CLOSE\?|SELECT|CONFIRM)/, { timeout: 10_000 });
      await expect(html).toHaveAttribute('data-air-gesture', gesture);
      // (A held fist replaces the gesture name with the W2 close hint.)
      if (gesture !== 'FIST') await expect(page.getByTestId('pod-gesture')).toContainText(gesture);

      const cursor = page.getByTestId('air-cursor');
      await expect(cursor).toHaveAttribute('data-visible', 'true');
      const box = (await cursor.boundingBox())!;
      const vp = page.viewportSize()!;
      const cx = box.x + box.width / 2;
      const cy = box.y + box.height / 2;
      expect(cx).toBeGreaterThanOrEqual(0);
      expect(cx).toBeLessThanOrEqual(vp.width);
      expect(cy).toBeGreaterThanOrEqual(0);
      expect(cy).toBeLessThanOrEqual(vp.height);
      expect(errors).toEqual([]);
    });
  });
}

test('debug skeleton is off by default and toggles with D / ?debug', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('debug-layer')).toBeHidden();
  await page.keyboard.press('d');
  await expect(page.getByTestId('debug-layer')).toBeVisible();
  await page.keyboard.press('d');
  await expect(page.getByTestId('debug-layer')).toBeHidden();
  await page.goto('/?debug');
  await expect(page.getByTestId('debug-layer')).toBeVisible();
});

test('no hand in view: AIR stays READY and the cursor stays hidden', async ({ page }) => {
  await page.goto('/');
  await page.getByTestId('start-button').click();
  await expect(page.locator('html')).toHaveAttribute('data-air-tracker', 'ready', { timeout: 20_000 });
  await page.waitForTimeout(800);
  await expect(page.getByTestId('pod-status')).toHaveText('AIR • READY');
  await expect(page.getByTestId('air-cursor')).toHaveAttribute('data-visible', 'false');
});
