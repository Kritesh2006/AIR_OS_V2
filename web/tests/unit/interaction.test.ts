import { describe, expect, it } from 'vitest';
import type { ActionProvider, ActionResult, Target } from '../../src/core/actions';
import type { GestureName } from '../../src/core/gestures';
import { DEFAULT_INTERACTION as C, InteractionController } from '../../src/core/interaction';
import { layoutGrid } from '../../src/core/layout';

const VP = { width: 1200, height: 800 };

class FakeProvider implements ActionProvider {
  readonly id = 'fake';
  readonly risk = 'high' as const;
  closed: string[] = [];
  constructor(public open = ['a', 'b', 'c', 'd']) {}
  listTargets(): Target[] {
    return this.open.map((id) => ({ id, label: id.toUpperCase(), sublabel: '', icon: '' }));
  }
  execute(t: Target): ActionResult {
    if (!this.open.includes(t.id)) return { status: 'GONE_BEFORE', detail: '' };
    this.open = this.open.filter((x) => x !== t.id);
    this.closed.push(t.id);
    return { status: 'CLOSED', detail: '' };
  }
}

/** Drives the controller frame by frame at ~30 fps. */
function rig(provider = new FakeProvider()) {
  const ctl = new InteractionController(provider);
  let t = 0;
  const rects = layoutGrid(provider.open, VP);
  const center = (id: string) => ({ x: rects[id].x + rects[id].w / 2, y: rects[id].y + rects[id].h / 2 });
  const hold = (gesture: GestureName | null, ms: number, cursor: { x: number; y: number } | null = null) => {
    const end = t + ms;
    let s = ctl.snapshot;
    while (t < end) {
      t += 33;
      s = ctl.step({ ts: t, gesture, cursor, viewport: VP });
    }
    return s;
  };
  const openSelection = () => hold('FIST', C.armMs + 100);
  const lockOn = (id: string) => hold('POINT', C.dwellMs + 100, center(id));
  return { ctl, provider, hold, openSelection, lockOn, center, now: () => t };
}

describe('NORMAL → CLOSE_SELECTION', () => {
  it('a fist arms with progress, and only opens selection after armMs', () => {
    const r = rig();
    const s = r.hold('FIST', C.armMs / 2);
    expect(s.mode).toBe('NORMAL');
    expect(s.state).toBe('ARMING');
    expect(s.podStatus).toBe('CLOSE?');
    expect(s.armProgress).toBeGreaterThan(0.3);
    expect(r.openSelection().mode).toBe('CLOSE_SELECTION');
  });

  it('releasing the fist early does nothing', () => {
    const r = rig();
    r.hold('FIST', C.armMs - 200);
    const s = r.hold('POINT', 500);
    expect(s.mode).toBe('NORMAL');
    expect(s.state).toBe('IDLE');
    expect(r.provider.closed).toEqual([]);
  });

  it('a fist alone NEVER closes anything, however long it is held', () => {
    const r = rig();
    r.hold('FIST', 30_000, { x: 600, y: 400 });
    expect(r.provider.closed).toEqual([]);
  });

  it('snapshots targets and lays out cards when selection opens', () => {
    const s = rig().openSelection();
    expect(s.targets.map((t) => t.id)).toEqual(['a', 'b', 'c', 'd']);
    expect(Object.keys(s.rects)).toEqual(['a', 'b', 'c', 'd']);
    expect(s.podStatus).toBe('SELECT');
  });

  it('with nothing to close, explains and waits for release', () => {
    const r = rig(new FakeProvider([]));
    const s = r.openSelection();
    expect(s.mode).toBe('WAIT_FOR_RELEASE');
    expect(s.hint).toMatch(/no windows/i);
  });
});

describe('targeting', () => {
  it('hovering a card for dwellMs locks it', () => {
    const r = rig();
    r.openSelection();
    const early = r.hold('POINT', C.dwellMs / 2, r.center('b'));
    expect(early.hoveredId).toBe('b');
    expect(early.lockedId).toBeNull();
    expect(early.dwellProgress).toBeGreaterThan(0);
    const s = r.lockOn('b');
    expect(s.lockedId).toBe('b');
    expect(s.state).toBe('LOCKED');
    expect(s.podStatus).toBe('CONFIRM');
  });

  it('jitter just past a card edge keeps the hover (hysteresis)', () => {
    const r = rig();
    const sel = r.openSelection();
    r.lockOn('a');
    const a = sel.rects.a;
    const s = r.hold('POINT', 300, { x: a.x + a.w + a.w * 0.1, y: a.y + a.h / 2 });
    expect(s.hoveredId).toBe('a');
    expect(s.lockedId).toBe('a');
  });

  it('moving to another card unlocks and re-dwells', () => {
    const r = rig();
    r.openSelection();
    r.lockOn('a');
    const moved = r.hold('POINT', 66, r.center('c'));
    expect(moved.lockedId).toBeNull();
    expect(moved.hoveredId).toBe('c');
    expect(r.lockOn('c').lockedId).toBe('c');
  });

  it('a fist during selection has no meaning', () => {
    const r = rig();
    r.openSelection();
    r.lockOn('a');
    const s = r.hold('FIST', 3000, r.center('a'));
    expect(s.mode).toBe('CLOSE_SELECTION');
    expect(r.provider.closed).toEqual([]);
  });
});

describe('confirmation (temporary W2 methods)', () => {
  it('Enter / ✓ confirms the locked card only', () => {
    const r = rig();
    r.openSelection();
    expect(r.ctl.command({ type: 'CONFIRM' }, r.now()).mode).toBe('CLOSE_SELECTION'); // nothing locked
    r.lockOn('c');
    const s = r.ctl.command({ type: 'CONFIRM' }, r.now());
    expect(r.provider.closed).toEqual(['c']);
    expect(s.mode).toBe('WAIT_FOR_RELEASE');
    expect(s.podStatus).toBe('CLOSED');
    expect(s.hint).toBe('Closed C');
  });

  it('a pinch held for pinchConfirmMs confirms the card locked when the pinch began', () => {
    const r = rig();
    r.openSelection();
    r.lockOn('b');
    const mid = r.hold('PINCH', C.pinchConfirmMs / 2, r.center('d')); // pinch drags the cursor away
    expect(mid.confirmProgress).toBeGreaterThan(0);
    expect(mid.lockedId).toBe('b'); // targeting frozen during the pinch
    r.hold('PINCH', C.pinchConfirmMs, r.center('d'));
    expect(r.provider.closed).toEqual(['b']);
  });

  it('a short pinch does not confirm', () => {
    const r = rig();
    r.openSelection();
    r.lockOn('b');
    r.hold('PINCH', C.pinchConfirmMs - 150, r.center('b'));
    const s = r.hold('POINT', 200, r.center('b'));
    expect(r.provider.closed).toEqual([]);
    expect(s.confirmProgress).toBe(0);
    expect(s.lockedId).toBe('b');
  });

  it('tapping a card locks it even if the cursor is elsewhere, until the cursor moves to another card', () => {
    const r = rig();
    r.openSelection();
    r.hold('POINT', 600, r.center('a')); // a is locked by dwell
    r.ctl.command({ type: 'TAP_TARGET', id: 'd' }, r.now());
    expect(r.hold('POINT', 600, r.center('a')).lockedId).toBe('d');
    r.ctl.command({ type: 'CONFIRM' }, r.now());
    expect(r.provider.closed).toEqual(['d']);
  });

  it('a target that vanished before confirm is reported, not crashed on', () => {
    const p = new FakeProvider();
    const r = rig(p);
    r.openSelection();
    r.lockOn('a');
    p.open = p.open.filter((x) => x !== 'a');
    const s = r.ctl.command({ type: 'CONFIRM' }, r.now());
    expect(s.mode).toBe('WAIT_FOR_RELEASE');
    expect(p.closed).toEqual([]);
  });
});

describe('cancellation', () => {
  it('open palm cancels', () => {
    const r = rig();
    r.openSelection();
    r.lockOn('a');
    const s = r.hold('OPEN PALM', 66);
    expect(s.mode).toBe('WAIT_FOR_RELEASE');
    expect(s.podStatus).toBe('CANCELLED');
    expect(r.provider.closed).toEqual([]);
  });

  it('Esc / Cancel button cancels', () => {
    const r = rig();
    r.openSelection();
    expect(r.ctl.command({ type: 'CANCEL' }, r.now()).lastOutcome?.kind).toBe('cancelled');
  });

  it('times out without activity', () => {
    const r = rig();
    r.openSelection();
    const s = r.hold('POINT', C.timeoutMs + 100, null);
    expect(s.lastOutcome?.kind).toBe('timeout');
    expect(r.provider.closed).toEqual([]);
  });

  it('moving between cards keeps the session alive past the timeout', () => {
    const r = rig();
    r.openSelection();
    for (let i = 0; i < 6; i++) r.hold('POINT', 2500, r.center(i % 2 ? 'a' : 'b'));
    expect(r.ctl.snapshot.mode).toBe('CLOSE_SELECTION');
  });

  it('a brief tracking dropout is tolerated; a real hand loss cancels', () => {
    const r = rig();
    r.openSelection();
    r.lockOn('a');
    expect(r.hold(null, C.handLostMs - 200).mode).toBe('CLOSE_SELECTION');
    r.hold('POINT', 100, r.center('a'));
    const s = r.hold(null, C.handLostMs + 100);
    expect(s.lastOutcome?.kind).toBe('hand_lost');
  });
});

describe('WAIT_FOR_RELEASE', () => {
  it('a still-held fist cannot start another selection', () => {
    const r = rig(new FakeProvider([]));
    r.openSelection(); // empty → wait for release with fist held
    const s = r.hold('FIST', 10_000);
    expect(s.mode).toBe('WAIT_FOR_RELEASE');
    expect(s.state).not.toBe('ARMING');
  });

  it('after confirming with a pinch, holding the pinch does nothing more', () => {
    const r = rig();
    r.openSelection();
    r.lockOn('a');
    r.hold('PINCH', C.pinchConfirmMs + 100, r.center('a'));
    r.hold('PINCH', 5000, r.center('b'));
    expect(r.provider.closed).toEqual(['a']);
    expect(r.ctl.snapshot.mode).toBe('WAIT_FOR_RELEASE');
  });

  it('releases when the pose changes for releasePoseMs, then a new fist works', () => {
    const r = rig();
    r.openSelection();
    r.lockOn('a');
    r.ctl.command({ type: 'CONFIRM' }, r.now()); // ended while pointing
    expect(r.hold('POINT', 1000).mode).toBe('WAIT_FOR_RELEASE');
    expect(r.hold('PEACE', C.releasePoseMs + 70).mode).toBe('NORMAL');
    expect(r.openSelection().mode).toBe('CLOSE_SELECTION');
    expect(r.ctl.snapshot.targets.map((t) => t.id)).toEqual(['b', 'c', 'd']);
  });

  it('releases when the hand leaves for releaseAbsentMs', () => {
    const r = rig(new FakeProvider([]));
    r.openSelection();
    expect(r.hold(null, C.releaseAbsentMs + 70).mode).toBe('NORMAL');
  });

  it('a one-frame pose flicker does not release', () => {
    const r = rig(new FakeProvider([]));
    r.openSelection();
    r.hold('POINT', 33);
    expect(r.hold('FIST', 1000).mode).toBe('WAIT_FOR_RELEASE');
  });
});

describe('snapshot', () => {
  it('is the same object while nothing changes', () => {
    const r = rig();
    const a = r.hold('POINT', 500);
    expect(r.hold('POINT', 500)).toBe(a);
  });

  it('reset abandons a selection silently', () => {
    const r = rig();
    r.openSelection();
    const s = r.ctl.reset();
    expect(s.mode).toBe('NORMAL');
    expect(s.podStatus).toBeNull();
    expect(r.provider.closed).toEqual([]);
  });
});
