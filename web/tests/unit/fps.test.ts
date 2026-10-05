import { describe, expect, it } from 'vitest';
import { FpsCounter } from '../../src/core/fps';

describe('FpsCounter', () => {
  it('is 0 with fewer than two frames', () => {
    const f = new FpsCounter();
    expect(f.fps).toBe(0);
    f.tick(0);
    expect(f.fps).toBe(0);
  });

  it('measures a steady 30 fps', () => {
    const f = new FpsCounter(10);
    for (let i = 0; i < 20; i++) f.tick(i * (1000 / 30));
    expect(f.fps).toBeCloseTo(30, 5);
  });

  it('reset clears history', () => {
    const f = new FpsCounter();
    f.tick(0);
    f.tick(33);
    f.reset();
    expect(f.fps).toBe(0);
  });
});
