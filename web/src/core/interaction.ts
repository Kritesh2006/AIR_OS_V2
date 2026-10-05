/**
 * interaction.ts — The frozen AIR interaction model (docs/ARCHITECTURE.md
 * §4), web edition:
 *
 *   NORMAL ──fist held armMs──▶ CLOSE_SELECTION ──confirm / cancel──▶ WAIT_FOR_RELEASE ──▶ NORMAL
 *                                SELECTING ⇄ LOCKED (dwell + hysteresis)
 *
 * A fist only ever OPENS the selection; nothing closes without an explicit
 * confirmation on a locked target. Pure and time-driven (all timestamps are
 * passed in), so it is fully unit-testable.
 *
 * W2 confirmation (temporary until blink in W3): Enter, tapping ✓, or a
 * pinch held for pinchConfirmMs. All go through the same confirm path.
 */

import type { PodStatus } from '../contracts';
import type { ActionProvider, Target } from './actions';
import type { GestureName } from './gestures';
import { hitTest, layoutGrid, type Rect } from './layout';
import type { Viewport } from './pointer';

export type Mode = 'NORMAL' | 'CLOSE_SELECTION' | 'WAIT_FOR_RELEASE';
export type SessionState = 'IDLE' | 'ARMING' | 'SELECTING' | 'LOCKED';
export type OutcomeKind = 'closed' | 'still_open' | 'cancelled' | 'timeout' | 'hand_lost' | 'empty';

export interface Outcome {
  readonly kind: OutcomeKind;
  readonly label: string;
  readonly at: number;
}

export interface InteractionSnapshot {
  readonly mode: Mode;
  readonly state: SessionState;
  /** 0..1 while the fist is being held in NORMAL. */
  readonly armProgress: number;
  /** Targets snapshotted when selection began ([] outside selection). */
  readonly targets: readonly Target[];
  /** Card geometry in viewport px, keyed by target id. */
  readonly rects: Readonly<Record<string, Rect>>;
  readonly hoveredId: string | null;
  readonly lockedId: string | null;
  /** 0..1 dwell toward locking the hovered card. */
  readonly dwellProgress: number;
  /** 0..1 pinch-hold toward confirming the locked card. */
  readonly confirmProgress: number;
  /** Pod status to show, or null when the interaction has nothing to say. */
  readonly podStatus: PodStatus | null;
  readonly hint: string;
  readonly lastOutcome: Outcome | null;
}

export interface FrameInput {
  readonly ts: number;
  /** Stable gesture, null = no hand. */
  readonly gesture: GestureName | null;
  /** AIR cursor in viewport px, null when not visible. */
  readonly cursor: { x: number; y: number } | null;
  readonly viewport: Viewport;
}

export type InteractionCommand =
  | { type: 'CONFIRM' }
  | { type: 'CANCEL' }
  | { type: 'TAP_TARGET'; id: string };

export interface InteractionConfig {
  armMs: number;
  dwellMs: number;
  pinchConfirmMs: number;
  /** Confirm the card that was locked this long before the pinch began. */
  confirmLookbackMs: number;
  timeoutMs: number;
  handLostMs: number;
  releasePoseMs: number;
  releaseAbsentMs: number;
  resultShowMs: number;
}

export const DEFAULT_INTERACTION: InteractionConfig = {
  armMs: 1000, // desktop fist_hold_seconds
  dwellMs: 350,
  pinchConfirmMs: 500,
  confirmLookbackMs: 200,
  timeoutMs: 10000,
  handLostMs: 1000, // desktop hand_lost_grace_s
  releasePoseMs: 150,
  releaseAbsentMs: 300,
  resultShowMs: 2500,
};

const HINTS = {
  arming: 'Keep holding the fist to close a window',
  select: 'Point at a window · open palm cancels',
  confirm: 'Pinch, tap ✓ or press Enter to close · open palm cancels',
  release: 'Release your hand',
} as const;

const OUTCOME_TEXT: Record<OutcomeKind, (label: string) => string> = {
  closed: (l) => `Closed ${l}`,
  still_open: (l) => `${l} is still open`,
  cancelled: () => 'Cancelled — nothing closed',
  timeout: () => 'Timed out — nothing closed',
  hand_lost: () => 'Hand lost — nothing closed',
  empty: () => 'No windows to close',
};

const round2 = (v: number) => Math.round(Math.min(1, Math.max(0, v)) * 100) / 100;

export class InteractionController {
  private mode: Mode = 'NORMAL';
  private now = 0;
  private gesture: GestureName | null = null;

  // NORMAL
  private armSince: number | null = null;

  // CLOSE_SELECTION
  private targets: Target[] = [];
  private rects: Record<string, Rect> = {};
  private hoveredId: string | null = null;
  private hoverSince = 0;
  private lockedId: string | null = null;
  /** A tapped lock stays until the hover moves to a different card. */
  private suppressDwellFor: string | null = null;
  private lockHistory: Array<{ ts: number; id: string | null }> = [];
  private pinchSince: number | null = null;
  private lastActivity = 0;
  private lostSince: number | null = null;

  // WAIT_FOR_RELEASE
  private endGesture: GestureName | null = null;
  private diffSince: number | null = null;
  private absentSince: number | null = null;

  private outcome: Outcome | null = null;
  private snap: InteractionSnapshot;

  constructor(
    private readonly provider: ActionProvider,
    private readonly cfg: InteractionConfig = DEFAULT_INTERACTION,
  ) {
    this.snap = this.build();
  }

  /** Same object until something visible changes. */
  get snapshot(): InteractionSnapshot {
    return this.snap;
  }

  /** Call once per tracker frame. */
  step(input: FrameInput): InteractionSnapshot {
    this.now = input.ts;
    this.gesture = input.gesture;
    switch (this.mode) {
      case 'NORMAL':
        this.stepNormal(input);
        break;
      case 'CLOSE_SELECTION':
        this.stepSelection(input);
        break;
      case 'WAIT_FOR_RELEASE':
        this.stepRelease(input);
        break;
    }
    return this.publish();
  }

  /** Enter / Esc / taps. `ts` on the same clock as frames. */
  command(cmd: InteractionCommand, ts: number): InteractionSnapshot {
    this.now = Math.max(this.now, ts);
    if (this.mode === 'CLOSE_SELECTION') {
      if (cmd.type === 'CANCEL') this.end('cancelled', '');
      else if (cmd.type === 'CONFIRM' && this.lockedId) this.confirm(this.lockedId);
      else if (cmd.type === 'TAP_TARGET' && this.rects[cmd.id]) {
        this.setLock(cmd.id);
        this.suppressDwellFor = this.hoveredId;
        this.lastActivity = this.now;
      }
    }
    return this.publish();
  }

  /** Abandon everything silently (camera stopped, tab hidden). */
  reset(): InteractionSnapshot {
    this.mode = 'NORMAL';
    this.armSince = null;
    this.clearSelection();
    this.outcome = null;
    return this.publish();
  }

  // ------------------------------------------------------------------ //
  private stepNormal({ ts, gesture, viewport }: FrameInput): void {
    if (gesture !== 'FIST') {
      this.armSince = null;
      return;
    }
    this.armSince ??= ts;
    if (ts - this.armSince >= this.cfg.armMs) this.begin(viewport);
  }

  private begin(viewport: Viewport): void {
    this.armSince = null;
    this.targets = this.provider.listTargets();
    if (this.targets.length === 0) {
      this.end('empty', '');
      return;
    }
    this.mode = 'CLOSE_SELECTION';
    this.rects = layoutGrid(this.targets.map((t) => t.id), viewport);
    this.lastActivity = this.now;
    this.lockHistory = [];
  }

  private stepSelection({ ts, gesture, cursor }: FrameInput): void {
    // Hand lost (after the grace period) cancels.
    if (gesture === null) {
      this.lostSince ??= ts;
      if (ts - this.lostSince >= this.cfg.handLostMs) return this.end('hand_lost', '');
    } else {
      this.lostSince = null;
    }
    if (ts - this.lastActivity >= this.cfg.timeoutMs) return this.end('timeout', '');
    if (gesture === 'OPEN PALM') return this.end('cancelled', '');

    if (gesture === 'PINCH') {
      // Confirm in progress: freeze targeting so the pinch itself cannot
      // drag the cursor onto a neighbouring card.
      this.pinchSince ??= ts;
      if (ts - this.pinchSince >= this.cfg.pinchConfirmMs) {
        const id = this.lockedAt(this.pinchSince - this.cfg.confirmLookbackMs) ?? this.lockedId;
        if (id) return this.confirm(id);
      }
    } else {
      this.pinchSince = null;
      if (gesture !== null) this.updateHover(cursor, ts);
    }
    this.lockHistory.push({ ts, id: this.lockedId });
    while (this.lockHistory.length && ts - this.lockHistory[0].ts > 1000) this.lockHistory.shift();
  }

  private updateHover(cursor: { x: number; y: number } | null, ts: number): void {
    const hovered = hitTest(cursor, this.rects, this.hoveredId);
    if (hovered !== this.hoveredId) {
      this.hoveredId = hovered;
      this.hoverSince = ts;
      this.lastActivity = ts;
      if (this.suppressDwellFor !== null && hovered !== this.suppressDwellFor) this.suppressDwellFor = null;
      if (this.lockedId && hovered !== this.lockedId && this.suppressDwellFor === null) this.setLock(null);
    }
    if (hovered && hovered !== this.lockedId && hovered !== this.suppressDwellFor &&
        ts - this.hoverSince >= this.cfg.dwellMs) {
      this.setLock(hovered);
    }
  }

  private setLock(id: string | null): void {
    if (id !== this.lockedId) this.lastActivity = this.now;
    this.lockedId = id;
  }

  private lockedAt(ts: number): string | null {
    let id: string | null = null;
    for (const h of this.lockHistory) {
      if (h.ts > ts) break;
      id = h.id;
    }
    return id;
  }

  private confirm(id: string): void {
    const target = this.targets.find((t) => t.id === id);
    if (!target) return this.end('cancelled', '');
    const result = this.provider.execute(target);
    this.end(result.status === 'CLOSED' || result.status === 'GONE_BEFORE' ? 'closed' : 'still_open', target.label);
  }

  private end(kind: OutcomeKind, label: string): void {
    this.outcome = { kind, label, at: this.now };
    this.mode = 'WAIT_FOR_RELEASE';
    this.endGesture = this.gesture;
    this.diffSince = null;
    this.absentSince = null;
    this.clearSelection();
  }

  private clearSelection(): void {
    this.targets = [];
    this.rects = {};
    this.hoveredId = null;
    this.lockedId = null;
    this.suppressDwellFor = null;
    this.lockHistory = [];
    this.pinchSince = null;
    this.lostSince = null;
  }

  private stepRelease({ ts, gesture }: FrameInput): void {
    if (gesture === null) {
      this.absentSince ??= ts;
      this.diffSince = null;
      if (ts - this.absentSince >= this.cfg.releaseAbsentMs) this.mode = 'NORMAL';
      return;
    }
    this.absentSince = null;
    if (gesture === this.endGesture) {
      this.diffSince = null;
      return;
    }
    this.diffSince ??= ts;
    if (ts - this.diffSince >= this.cfg.releasePoseMs) this.mode = 'NORMAL';
  }

  // ------------------------------------------------------------------ //
  private build(): InteractionSnapshot {
    const selecting = this.mode === 'CLOSE_SELECTION';
    const arming = this.mode === 'NORMAL' && this.armSince !== null;
    const showOutcome = this.outcome !== null && this.now - this.outcome.at < this.cfg.resultShowMs;

    let podStatus: PodStatus | null = null;
    let hint = '';
    if (arming) {
      podStatus = 'CLOSE?';
      hint = HINTS.arming;
    } else if (selecting) {
      podStatus = this.lockedId ? 'CONFIRM' : 'SELECT';
      hint = this.lockedId ? HINTS.confirm : HINTS.select;
    } else if (showOutcome && this.outcome) {
      const k = this.outcome.kind;
      podStatus = k === 'closed' ? 'CLOSED' : k === 'still_open' ? 'STILL OPEN' : 'CANCELLED';
      hint = OUTCOME_TEXT[k](this.outcome.label);
    } else if (this.mode === 'WAIT_FOR_RELEASE') {
      hint = HINTS.release;
    }

    return Object.freeze({
      mode: this.mode,
      state: selecting ? (this.lockedId ? 'LOCKED' : 'SELECTING') : arming ? 'ARMING' : 'IDLE',
      armProgress: arming ? round2((this.now - (this.armSince ?? this.now)) / this.cfg.armMs) : 0,
      targets: this.targets,
      rects: this.rects,
      hoveredId: this.hoveredId,
      lockedId: this.lockedId,
      dwellProgress:
        selecting && this.hoveredId && this.hoveredId !== this.lockedId && this.hoveredId !== this.suppressDwellFor
          ? round2((this.now - this.hoverSince) / this.cfg.dwellMs)
          : 0,
      confirmProgress:
        selecting && this.pinchSince !== null && this.lockedId
          ? round2((this.now - this.pinchSince) / this.cfg.pinchConfirmMs)
          : 0,
      podStatus,
      hint,
      lastOutcome: this.outcome,
    } satisfies InteractionSnapshot);
  }

  private publish(): InteractionSnapshot {
    const next = this.build();
    const prev = this.snap;
    const same = (Object.keys(next) as Array<keyof InteractionSnapshot>).every((k) => next[k] === prev[k]);
    if (!same) this.snap = next;
    return this.snap;
  }
}
