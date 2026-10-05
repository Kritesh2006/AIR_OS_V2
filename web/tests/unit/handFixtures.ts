import type { Landmark } from '../../src/core/hand';

export type Finger = 'thumb' | 'index' | 'middle' | 'ring' | 'pinky';

/**
 * Synthetic upright hand (wrist at the bottom), palm length 0.2.
 * `extended` lists straight fingers; `pinch` puts the thumb tip on the
 * index tip.
 */
export function makeHand(extended: Finger[], opts: { pinch?: boolean; dx?: number; dy?: number } = {}): Landmark[] {
  const lm: Landmark[] = Array.from({ length: 21 }, () => ({ x: 0.5, y: 0.8 }));
  const set = (i: number, x: number, y: number) => (lm[i] = { x, y });
  set(0, 0.5, 0.8);
  set(1, 0.42, 0.75);
  set(2, 0.38, 0.7);
  set(3, 0.35, 0.65);
  if (extended.includes('thumb')) set(4, 0.3, 0.58);
  else set(4, 0.47, 0.62);
  const fingers: Array<[Finger, number, number]> = [['index', 5, 0.45], ['middle', 9, 0.5], ['ring', 13, 0.55], ['pinky', 17, 0.6]];
  for (const [name, mcp, x] of fingers) {
    const ext = extended.includes(name);
    set(mcp, x, name === 'pinky' ? 0.62 : 0.6);
    set(mcp + 1, x, ext ? 0.5 : 0.52);
    set(mcp + 2, x, ext ? 0.44 : 0.56);
    set(mcp + 3, x, ext ? 0.38 : 0.6);
  }
  if (opts.pinch) set(4, lm[8].x + 0.01, lm[8].y + 0.02);
  const { dx = 0, dy = 0 } = opts;
  return lm.map((p) => ({ x: p.x + dx, y: p.y + dy }));
}

/** Rotate a hand around its wrist (radians). */
export function rotate(lm: Landmark[], angle: number): Landmark[] {
  const { x: cx, y: cy } = lm[0];
  const c = Math.cos(angle), s = Math.sin(angle);
  return lm.map((p) => ({ x: cx + (p.x - cx) * c - (p.y - cy) * s, y: cy + (p.x - cx) * s + (p.y - cy) * c }));
}
