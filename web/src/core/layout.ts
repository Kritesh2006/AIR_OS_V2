/**
 * layout.ts — Selection-card geometry and hit-testing. The interaction
 * core owns geometry; the UI only draws the rects it is given.
 */

import type { Viewport } from './pointer';

export interface Rect {
  readonly x: number;
  readonly y: number;
  readonly w: number;
  readonly h: number;
}

const GAP = 18;
const MARGIN = 16;
/** Area kept clear for the top-left Pod, and for the bottom header bar. */
export const POD_SAFE = { w: 216, h: 260 } as const;
export const FOOTER_SAFE = 72;

interface Region { x: number; y: number; w: number; h: number }

function fit(n: number, r: Region) {
  const cols = Math.min(n, r.w < 560 ? 2 : 3);
  const rows = Math.ceil(n / cols);
  const w = Math.min(280, (r.w - GAP * (cols - 1)) / cols);
  const h = Math.min(w * 0.75, (r.h - GAP * (rows - 1)) / rows);
  return { cols, rows, w, h, area: w > 0 && h > 0 ? w * h : 0 };
}

/**
 * Grid of cards that never sits under the Pod or the footer: tries the
 * area below the Pod and the area to its right, and uses whichever gives
 * bigger cards (portrait phones → below, laptops/landscape → right).
 */
export function layoutGrid(ids: readonly string[], vp: Viewport): Record<string, Rect> {
  const n = ids.length;
  if (n === 0) return {};
  const below: Region = { x: MARGIN, y: POD_SAFE.h, w: vp.width - 2 * MARGIN, h: vp.height - POD_SAFE.h - FOOTER_SAFE };
  const right: Region = { x: POD_SAFE.w, y: MARGIN, w: vp.width - POD_SAFE.w - MARGIN, h: vp.height - MARGIN - FOOTER_SAFE };
  const a = fit(n, below);
  const b = fit(n, right);
  const [region, g] = b.area >= a.area ? [right, b] : [below, a];
  const gridW = g.cols * g.w + (g.cols - 1) * GAP;
  const gridH = g.rows * g.h + (g.rows - 1) * GAP;
  const x0 = region.x + (region.w - gridW) / 2;
  const y0 = region.y + Math.max(0, (region.h - gridH) / 2);
  const out: Record<string, Rect> = {};
  ids.forEach((id, i) => {
    const r = Math.floor(i / g.cols);
    // Center a short last row.
    const inRow = r === g.rows - 1 ? n - r * g.cols : g.cols;
    const rowX = x0 + ((g.cols - inRow) * (g.w + GAP)) / 2;
    out[id] = Object.freeze({ x: rowX + (i % g.cols) * (g.w + GAP), y: y0 + r * (g.h + GAP), w: g.w, h: g.h });
  });
  return out;
}

function inside(p: { x: number; y: number }, r: Rect, pad = 0): boolean {
  return p.x >= r.x - pad && p.x <= r.x + r.w + pad && p.y >= r.y - pad && p.y <= r.y + r.h + pad;
}

/**
 * Which card is under the point. Hysteresis: the current card keeps the
 * hover while the point stays within its rect grown by `stickiness` of its
 * width, so jitter at an edge or across a gap does not flip targets.
 */
export function hitTest(
  p: { x: number; y: number } | null,
  rects: Readonly<Record<string, Rect>>,
  current: string | null,
  stickiness = 0.15,
): string | null {
  if (!p) return current;
  if (current && rects[current] && inside(p, rects[current], rects[current].w * stickiness)) return current;
  for (const [id, r] of Object.entries(rects)) if (inside(p, r)) return id;
  return null;
}
