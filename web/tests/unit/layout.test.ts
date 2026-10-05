import { describe, expect, it } from 'vitest';
import { FOOTER_SAFE, hitTest, layoutGrid, POD_SAFE, type Rect } from '../../src/core/layout';

const overlap = (a: Rect, b: Rect) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

describe('layoutGrid', () => {
  it.each([
    [{ width: 1280, height: 800 }, 6],
    [{ width: 390, height: 844 }, 6], // phone portrait
    [{ width: 844, height: 390 }, 5], // phone landscape
    [{ width: 1280, height: 800 }, 1],
    [{ width: 412, height: 915 }, 6], // Pixel 7
  ])('%o with %i cards: on screen, clear of Pod and footer, no overlaps, usable size', (vp, n) => {
    const ids = Array.from({ length: n }, (_, i) => `w${i}`);
    const rects = Object.values(layoutGrid(ids, vp));
    expect(rects).toHaveLength(n);
    for (const r of rects) {
      expect(r.x).toBeGreaterThanOrEqual(0);
      expect(r.y).toBeGreaterThanOrEqual(0);
      expect(r.x + r.w).toBeLessThanOrEqual(vp.width);
      expect(r.y + r.h).toBeLessThanOrEqual(vp.height - FOOTER_SAFE);
      expect(overlap(r, { x: 0, y: 0, w: POD_SAFE.w, h: POD_SAFE.h })).toBe(false);
      expect(r.w).toBeGreaterThanOrEqual(120);
      expect(r.h).toBeGreaterThanOrEqual(90);
    }
    for (let i = 0; i < rects.length; i++) for (let j = i + 1; j < rects.length; j++) expect(overlap(rects[i], rects[j])).toBe(false);
  });

  it('uses 2 columns below the Pod on a portrait phone', () => {
    const rects = layoutGrid(['a', 'b', 'c'], { width: 390, height: 844 });
    expect(rects.a.y).toBe(rects.b.y);
    expect(rects.c.y).toBeGreaterThan(rects.a.y);
    expect(rects.a.y).toBeGreaterThanOrEqual(POD_SAFE.h);
  });

  it('sits to the right of the Pod on a landscape phone', () => {
    const rects = layoutGrid(['a', 'b', 'c', 'd', 'e'], { width: 844, height: 390 });
    expect(Object.values(rects).every((r) => r.x >= POD_SAFE.w)).toBe(true);
  });

  it('is empty for no cards', () => {
    expect(layoutGrid([], { width: 100, height: 100 })).toEqual({});
  });
});

describe('hitTest', () => {
  const rects = { a: { x: 0, y: 0, w: 100, h: 60 }, b: { x: 120, y: 0, w: 100, h: 60 } };
  it('finds the card under the point', () => {
    expect(hitTest({ x: 50, y: 30 }, rects, null)).toBe('a');
    expect(hitTest({ x: 150, y: 30 }, rects, null)).toBe('b');
    expect(hitTest({ x: 110, y: 30 }, rects, null)).toBeNull();
  });
  it('keeps the current card a little beyond its edge', () => {
    expect(hitTest({ x: 110, y: 30 }, rects, 'a')).toBe('a');
    expect(hitTest({ x: 125, y: 30 }, rects, 'a')).toBe('b');
  });
  it('keeps the current card when there is no cursor', () => {
    expect(hitTest(null, rects, 'b')).toBe('b');
  });
});
