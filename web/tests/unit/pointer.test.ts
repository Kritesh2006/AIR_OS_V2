import { describe, expect, it } from 'vitest';
import { OneEuroFilter } from '../../src/core/oneEuro';
import { DEFAULT_POINTER, mapToViewport, PointerController } from '../../src/core/pointer';

const vp = { width: 1000, height: 600 };

describe('mapToViewport', () => {
  it('maps the center of the camera to the center of the screen', () => {
    expect(mapToViewport({ x: 0.5, y: 0.5 }, vp, 0.6)).toEqual({ x: 500, y: 300 });
  });

  it('mirrors x: the user moving right moves the cursor right', () => {
    // In the unmirrored camera image the user's right hand side is small x.
    expect(mapToViewport({ x: 0.2, y: 0.5 }, vp, 0.6).x).toBe(1000);
    expect(mapToViewport({ x: 0.8, y: 0.5 }, vp, 0.6).x).toBe(0);
  });

  it('the control box reaches the screen edges before the camera edges, and clamps', () => {
    expect(mapToViewport({ x: 0.5, y: 0.2 }, vp, 0.6).y).toBe(0);
    expect(mapToViewport({ x: 0.5, y: 0.8 }, vp, 0.6).y).toBe(600);
    expect(mapToViewport({ x: 0.0, y: 1.0 }, vp, 0.6)).toEqual({ x: 1000, y: 600 });
  });
});

describe('OneEuroFilter', () => {
  it('passes the first value through and stays put on a constant signal', () => {
    const f = new OneEuroFilter();
    expect(f.filter(10, 0)).toBe(10);
    expect(f.filter(10, 33)).toBe(10);
  });

  it('smooths jitter around a still point', () => {
    const f = new OneEuroFilter(1.0, 0.007);
    let maxDev = 0;
    for (let i = 0; i < 60; i++) {
      const out = f.filter(500 + (i % 2 ? 4 : -4), i * 33);
      if (i > 10) maxDev = Math.max(maxDev, Math.abs(out - 500));
    }
    expect(maxDev).toBeLessThan(2.5);
  });

  it('follows a fast move closely', () => {
    const f = new OneEuroFilter(1.0, 0.007);
    let out = 0;
    for (let i = 0; i <= 15; i++) out = f.filter(i * 60, i * 33);
    expect(900 - out).toBeLessThan(120);
  });
});

describe('PointerController', () => {
  it('is hidden before any hand is seen', () => {
    expect(new PointerController().sample(0).visible).toBe(false);
  });

  it('appears where the finger is, without swooping from a corner', () => {
    const p = new PointerController();
    p.update({ x: 0.5, y: 0.5 }, 0, vp, 0.9);
    const s = p.sample(16);
    expect(s.visible).toBe(true);
    expect(s.x).toBeCloseTo(500);
    expect(s.y).toBeCloseTo(300);
    expect(s.confidence).toBe(0.9);
  });

  it('moves toward a new finger position over animation frames', () => {
    const p = new PointerController();
    p.update({ x: 0.5, y: 0.5 }, 0, vp);
    p.sample(0);
    p.update({ x: 0.3, y: 0.5 }, 33, vp);
    const first = p.sample(40).x;
    let last = first;
    for (let t = 56; t < 600; t += 16) last = p.sample(t).x;
    expect(first).toBeGreaterThan(500);
    expect(last).toBeGreaterThan(first);
  });

  it('hides after the lost-hand grace period', () => {
    const p = new PointerController();
    p.update({ x: 0.5, y: 0.5 }, 0, vp);
    expect(p.sample(DEFAULT_POINTER.lostGraceMs - 10).visible).toBe(true);
    expect(p.sample(DEFAULT_POINTER.lostGraceMs + 10).visible).toBe(false);
  });

  it('reports pinch as pressed', () => {
    const p = new PointerController();
    p.update({ x: 0.5, y: 0.5 }, 0, vp, 1, true);
    expect(p.sample(16).pressed).toBe(true);
  });
});
