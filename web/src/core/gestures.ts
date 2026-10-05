/**
 * gestures.ts — Static hand poses from one frame of landmarks, plus a
 * stabilizer so the displayed gesture does not flicker on noisy frames.
 *
 * Finger rules match desktop hand_tracker.get_finger_states (tip farther
 * from the wrist than the PIP joint), with distances corrected for the
 * camera aspect ratio. Pinch is measured relative to palm length so it
 * works at any distance from the camera.
 */

import { LM, type Landmark } from './hand';

export type GestureName = 'OPEN PALM' | 'FIST' | 'POINT' | 'PEACE' | 'PINCH' | 'HAND';

export interface FingerStates {
  thumb: boolean;
  index: boolean;
  middle: boolean;
  ring: boolean;
  pinky: boolean;
}

/** Extension margin, same as desktop (1.08). */
const EXTEND_RATIO = 1.08;
/** Thumb–index tip distance below this fraction of palm length = pinch. */
export const PINCH_RATIO = 0.3;

function dist(a: Landmark, b: Landmark, aspect: number): number {
  return Math.hypot((a.x - b.x) * aspect, a.y - b.y);
}

/** `aspect` = camera width / height (normalized x is scaled by it). */
export function fingerStates(lm: readonly Landmark[], aspect = 1): FingerStates {
  const w = lm[LM.WRIST];
  const ext = (tip: number, pip: number) => dist(lm[tip], w, aspect) > dist(lm[pip], w, aspect) * EXTEND_RATIO;
  const pinkyBase = lm[LM.PINKY_MCP];
  return {
    thumb: dist(lm[LM.THUMB_TIP], pinkyBase, aspect) > dist(lm[LM.THUMB_IP], pinkyBase, aspect) * EXTEND_RATIO,
    index: ext(LM.INDEX_TIP, LM.INDEX_PIP),
    middle: ext(LM.MIDDLE_TIP, LM.MIDDLE_PIP),
    ring: ext(LM.RING_TIP, LM.RING_PIP),
    pinky: ext(LM.PINKY_TIP, LM.PINKY_PIP),
  };
}

/** Thumb–index tip distance divided by palm length (wrist → middle MCP). */
export function pinchRatio(lm: readonly Landmark[], aspect = 1): number {
  const palm = dist(lm[LM.WRIST], lm[LM.MIDDLE_MCP], aspect);
  return palm > 0 ? dist(lm[LM.THUMB_TIP], lm[LM.INDEX_TIP], aspect) / palm : Infinity;
}

/** Classify one frame. 'HAND' = a hand is visible but no known pose. */
export function classifyGesture(lm: readonly Landmark[], aspect = 1): GestureName {
  if (lm.length < 21) return 'HAND';
  const f = fingerStates(lm, aspect);
  const others = [f.middle, f.ring, f.pinky].filter(Boolean).length;

  // A fist also brings thumb and index tips together, so a pinch needs the
  // index or thumb reaching out (same rule as desktop).
  if (pinchRatio(lm, aspect) < PINCH_RATIO && (f.index || f.thumb)) return 'PINCH';
  if (f.index && others === 3) return 'OPEN PALM';
  if (!f.index && others === 0 && !f.thumb) return 'FIST';
  if (f.index && others === 0) return 'POINT';
  if (f.index && f.middle && !f.ring && !f.pinky) return 'PEACE';
  return 'HAND';
}

/**
 * Debounces raw per-frame gestures. A new gesture must be seen
 * continuously for `holdMs` before it is reported; a lost hand is reported
 * after `lostMs` so a single dropped frame does not blank the display.
 * Time-based, so it behaves the same at any frame rate.
 */
export class GestureStabilizer {
  private stable: GestureName | null = null;
  // `undefined` = no candidate; `null` is a real candidate ("hand lost").
  private candidate: GestureName | null | undefined = undefined;
  private candidateSince = 0;

  constructor(
    private readonly holdMs = 150,
    private readonly lostMs = 300,
  ) {}

  get current(): GestureName | null {
    return this.stable;
  }

  update(raw: GestureName | null, tsMs: number): GestureName | null {
    if (raw === this.stable) {
      this.candidate = undefined;
      return this.stable;
    }
    if (raw !== this.candidate) {
      this.candidate = raw;
      this.candidateSince = tsMs;
    }
    const needed = raw === null ? this.lostMs : this.stable === null ? 0 : this.holdMs;
    if (tsMs - this.candidateSince >= needed) {
      this.stable = raw;
      this.candidate = undefined;
    }
    return this.stable;
  }

  reset(): void {
    this.stable = null;
    this.candidate = undefined;
  }
}
