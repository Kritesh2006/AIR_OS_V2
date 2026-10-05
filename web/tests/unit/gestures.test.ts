import { describe, expect, it } from 'vitest';
import { classifyGesture, fingerStates, GestureStabilizer, pinchRatio } from '../../src/core/gestures';
import { makeHand, rotate } from './handFixtures';

describe('classifyGesture', () => {
  it.each([
    ['OPEN PALM', makeHand(['thumb', 'index', 'middle', 'ring', 'pinky'])],
    ['OPEN PALM', makeHand(['index', 'middle', 'ring', 'pinky'])],
    ['FIST', makeHand([])],
    ['POINT', makeHand(['index'])],
    ['PEACE', makeHand(['index', 'middle'])],
    ['PINCH', makeHand(['index', 'middle', 'ring', 'pinky'], { pinch: true })],
    ['PINCH', makeHand(['index'], { pinch: true })],
    ['HAND', makeHand(['thumb'])],
    ['HAND', makeHand(['pinky'])],
  ] as const)('%s', (expected, hand) => {
    expect(classifyGesture(hand)).toBe(expected);
  });

  it('a fist is not a pinch even though thumb and index tips are close', () => {
    const fist = makeHand([]);
    expect(pinchRatio(fist)).toBeLessThan(0.3);
    expect(classifyGesture(fist)).toBe('FIST');
  });

  it('works when the hand is rotated or moved', () => {
    for (const angle of [0.4, -0.6, Math.PI / 2]) {
      expect(classifyGesture(rotate(makeHand(['index', 'middle']), angle))).toBe('PEACE');
      expect(classifyGesture(rotate(makeHand([]), angle))).toBe('FIST');
    }
    expect(classifyGesture(makeHand(['index'], { dx: -0.2, dy: 0.1 }))).toBe('POINT');
  });

  it('matches the desktop finger rules', () => {
    expect(fingerStates(makeHand(['index', 'ring']))).toEqual({
      thumb: false, index: true, middle: false, ring: true, pinky: false,
    });
  });

  it('pinch is measured relative to hand size', () => {
    const big = makeHand(['index'], { pinch: true }).map((p) => ({ x: 0.5 + (p.x - 0.5) * 2, y: 0.5 + (p.y - 0.5) * 2 }));
    expect(classifyGesture(big)).toBe('PINCH');
  });

  it('incomplete landmark lists are just a hand', () => {
    expect(classifyGesture(makeHand(['index']).slice(0, 10))).toBe('HAND');
  });
});

describe('GestureStabilizer', () => {
  it('shows the first gesture immediately', () => {
    const s = new GestureStabilizer(150, 300);
    expect(s.update('POINT', 0)).toBe('POINT');
  });

  it('ignores a one-frame flicker', () => {
    const s = new GestureStabilizer(150, 300);
    s.update('POINT', 0);
    expect(s.update('PEACE', 33)).toBe('POINT');
    expect(s.update('POINT', 66)).toBe('POINT');
    expect(s.update('POINT', 400)).toBe('POINT');
  });

  it('switches after the new gesture holds', () => {
    const s = new GestureStabilizer(150, 300);
    s.update('POINT', 0);
    s.update('FIST', 100);
    expect(s.update('FIST', 200)).toBe('POINT');
    expect(s.update('FIST', 250)).toBe('FIST');
  });

  it('keeps the hand through short dropouts, clears after lostMs', () => {
    const s = new GestureStabilizer(150, 300);
    s.update('OPEN PALM', 0);
    expect(s.update(null, 50)).toBe('OPEN PALM');
    expect(s.update('OPEN PALM', 100)).toBe('OPEN PALM');
    s.update(null, 200);
    expect(s.update(null, 499)).toBe('OPEN PALM');
    expect(s.update(null, 500)).toBeNull();
  });

  it('reset forgets everything', () => {
    const s = new GestureStabilizer();
    s.update('FIST', 0);
    s.reset();
    expect(s.current).toBeNull();
  });
});
