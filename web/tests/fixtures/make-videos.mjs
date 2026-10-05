// Turns the hand photos into 640x480 MJPEG files Chromium can use as a fake
// camera (--use-file-for-fake-video-capture). Run: node tests/fixtures/make-videos.mjs
import { chromium } from '@playwright/test';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const dir = dirname(fileURLToPath(import.meta.url));
const names = ['pointing_up', 'victory', 'fist', 'thumb_up'];
const browser = await chromium.launch();
const page = await browser.newPage();
for (const name of names) {
  const src = 'data:image/jpeg;base64,' + readFileSync(join(dir, `${name}.jpg`)).toString('base64');
  const b64 = await page.evaluate(async (src) => {
    const img = new Image();
    img.src = src;
    await img.decode();
    const c = document.createElement('canvas');
    c.width = 640;
    c.height = 480;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#d8d4cc';
    ctx.fillRect(0, 0, 640, 480);
    const s = Math.min(640 / img.width, 480 / img.height);
    ctx.drawImage(img, (640 - img.width * s) / 2, (480 - img.height * s) / 2, img.width * s, img.height * s);
    return c.toDataURL('image/jpeg', 0.9).split(',')[1];
  }, src);
  const frame = Buffer.from(b64, 'base64');
  writeFileSync(join(dir, `${name}.mjpeg`), Buffer.concat([frame, frame]));
  console.log(`${name}.mjpeg`);
}
await browser.close();
