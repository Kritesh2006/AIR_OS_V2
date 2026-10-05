/**
 * pointer.ts — Index fingertip → AIR virtual cursor.
 *
 *   tip (unmirrored, normalized) → mirror x → control box → viewport px
 *   → One Euro filter (on tracker timestamps) → target
 *   sample() at animation-frame rate eases the drawn cursor toward the
 *   target, so it glides between ~30 Hz tracker updates.
 *
 * Never touches the real OS cursor.
 */

import type { Landmark } from './hand';
import { OneEuroFilter } from './oneEuro';

export interface CursorSample {
  /** Viewport CSS pixels. */
  readonly x: number;
  readonly y: number;
  readonly visible: boolean;
  /** 0..1, for opacity / emphasis. */
  readonly confidence: number;
  readonly pressed: boolean;
}

export interface PointerConfig {
  /** Central fraction of the camera frame that maps to the whole viewport. */
  boxFraction: number;
  minCutoff: number;
  beta: number;
  /** Keep the cursor this long after the hand disappears. */
  lostGraceMs: number;
  /** Easing time constant for the drawn cursor. */
  easeMs: number;
}

export const DEFAULT_POINTER: PointerConfig = {
  boxFraction: 0.6,
  minCutoff: 1.0,
  beta: 0.007,
  lostGraceMs: 400,
  easeMs: 45,
};

export interface Viewport {
  width: number;
  height: number;
}

/** Map an unmirrored normalized point to viewport px through the control box. */
export function mapToViewport(p: Landmark, vp: Viewport, boxFraction: number): { x: number; y: number } {
  const lo = (1 - boxFraction) / 2;
  const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
  const u = clamp01((1 - p.x - lo) / boxFraction); // mirror: user's right = screen right
  const v = clamp01((p.y - lo) / boxFraction);
  return { x: u * vp.width, y: v * vp.height };
}

export class PointerController {
  private readonly fx: OneEuroFilter;
  private readonly fy: OneEuroFilter;
  private target: { x: number; y: number } | null = null;
  private drawn: { x: number; y: number } | null = null;
  private lastSeen = -Infinity;
  private lastSample = 0;
  private confidence = 0;
  private pressed = false;

  constructor(private readonly cfg: PointerConfig = DEFAULT_POINTER) {
    this.fx = new OneEuroFilter(cfg.minCutoff, cfg.beta);
    this.fy = new OneEuroFilter(cfg.minCutoff, cfg.beta);
  }

  /** Call once per tracker frame. `tip` null = no hand this frame. */
  update(tip: Landmark | null, tsMs: number, vp: Viewport, confidence = 1, pressed = false): void {
    if (!tip) return;
    const raw = mapToViewport(tip, vp, this.cfg.boxFraction);
    const fresh = tsMs - this.lastSeen > this.cfg.lostGraceMs;
    if (fresh) {
      // Re-acquired after a loss: start where the finger is, no swoop.
      this.fx.reset();
      this.fy.reset();
      this.drawn = null;
    }
    this.target = { x: this.fx.filter(raw.x, tsMs), y: this.fy.filter(raw.y, tsMs) };
    this.lastSeen = tsMs;
    this.confidence = confidence;
    this.pressed = pressed;
  }

  /** Filtered cursor position for hit-testing, or null if not visible. */
  targetAt(nowMs: number): { x: number; y: number } | null {
    return this.target && nowMs - this.lastSeen <= this.cfg.lostGraceMs ? this.target : null;
  }

  /** Call once per animation frame. */
  sample(nowMs: number): CursorSample {
    const dt = this.lastSample ? Math.max(0, nowMs - this.lastSample) : 16;
    this.lastSample = nowMs;
    const visible = this.target !== null && nowMs - this.lastSeen <= this.cfg.lostGraceMs;
    if (!this.target) return { x: 0, y: 0, visible: false, confidence: 0, pressed: false };
    if (!this.drawn) this.drawn = { ...this.target };
    const k = 1 - Math.exp(-dt / this.cfg.easeMs);
    this.drawn = {
      x: this.drawn.x + (this.target.x - this.drawn.x) * k,
      y: this.drawn.y + (this.target.y - this.drawn.y) * k,
    };
    return { x: this.drawn.x, y: this.drawn.y, visible, confidence: visible ? this.confidence : 0, pressed: visible && this.pressed };
  }

  reset(): void {
    this.target = null;
    this.drawn = null;
    this.lastSeen = -Infinity;
    this.fx.reset();
    this.fy.reset();
  }
}
