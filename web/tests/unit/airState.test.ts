import { describe, expect, it } from 'vitest';
import { INITIAL_STATE, reduce, type AirEvent } from '../../src/core/airState';

const run = (...events: AirEvent[]) => events.reduce(reduce, INITIAL_STATE);

describe('airState', () => {
  it('starts idle and READY', () => {
    expect(INITIAL_STATE.phase).toBe('idle');
    expect(INITIAL_STATE.podStatus).toBe('READY');
  });

  it('goes idle → requesting → running', () => {
    const s = run({ type: 'START_REQUESTED' }, { type: 'CAMERA_STARTED' });
    expect(s.phase).toBe('running');
    expect(s.message).toBe('');
  });

  it('reports a denied camera and allows retry', () => {
    const denied = run({ type: 'START_REQUESTED' }, { type: 'CAMERA_FAILED', reason: 'denied', message: 'blocked' });
    expect(denied.phase).toBe('denied');
    expect(denied.message).toBe('blocked');
    expect(reduce(denied, { type: 'START_REQUESTED' }).phase).toBe('requesting');
  });

  it('pauses when the tab is hidden and resumes through requesting', () => {
    const paused = run({ type: 'START_REQUESTED' }, { type: 'CAMERA_STARTED' }, { type: 'TAB_HIDDEN' });
    expect(paused.phase).toBe('paused');
    expect(paused.podStatus).toBe('PAUSED');
    const resuming = reduce(paused, { type: 'TAB_VISIBLE' });
    expect(resuming.phase).toBe('requesting');
    expect(reduce(resuming, { type: 'CAMERA_STARTED' }).podStatus).toBe('READY');
  });

  it('stop returns to idle with an explanation', () => {
    const s = run({ type: 'START_REQUESTED' }, { type: 'CAMERA_STARTED' }, { type: 'STOPPED' });
    expect(s.phase).toBe('idle');
    expect(s.message).toMatch(/camera is off/i);
  });

  it('returns the same object for events that do not apply', () => {
    expect(reduce(INITIAL_STATE, { type: 'CAMERA_STARTED' })).toBe(INITIAL_STATE);
    expect(reduce(INITIAL_STATE, { type: 'TAB_HIDDEN' })).toBe(INITIAL_STATE);
    expect(reduce(INITIAL_STATE, { type: 'FPS', fps: 30 })).toBe(INITIAL_STATE);
    const running = run({ type: 'START_REQUESTED' }, { type: 'CAMERA_STARTED' });
    expect(reduce(running, { type: 'START_REQUESTED' })).toBe(running);
  });

  it('updates fps only while running, rounded, and only on change', () => {
    const running = run({ type: 'START_REQUESTED' }, { type: 'CAMERA_STARTED' });
    const a = reduce(running, { type: 'FPS', fps: 29.6 });
    expect(a.fps).toBe(30);
    expect(reduce(a, { type: 'FPS', fps: 30.2 })).toBe(a);
  });

  it('states are immutable', () => {
    expect(Object.isFrozen(run({ type: 'START_REQUESTED' }))).toBe(true);
  });
});

describe('airState: hand tracking', () => {
  const running = run({ type: 'START_REQUESTED' }, { type: 'CAMERA_STARTED' });

  it('tracker goes off → loading → ready and survives Stop', () => {
    const loading = reduce(INITIAL_STATE, { type: 'TRACKER_LOADING' });
    expect(loading.tracker).toBe('loading');
    const ready = reduce(loading, { type: 'TRACKER_READY' });
    expect(ready.tracker).toBe('ready');
    const s = [{ type: 'START_REQUESTED' }, { type: 'CAMERA_STARTED' }, { type: 'STOPPED' }] as const;
    expect(s.reduce(reduce, ready).tracker).toBe('ready');
  });

  it('a hand switches the Pod to HAND and shows the gesture', () => {
    const s = reduce(running, { type: 'HAND', gesture: 'POINT', confidence: 0.93 });
    expect(s.podStatus).toBe('HAND');
    expect(s.handPresent).toBe(true);
    expect(s.gesture).toBe('POINT');
    expect(s.handConfidence).toBe(0.9);
  });

  it('losing the hand returns to READY', () => {
    const s = reduce(reduce(running, { type: 'HAND', gesture: 'FIST', confidence: 1 }), { type: 'HAND', gesture: null, confidence: 0 });
    expect(s.podStatus).toBe('READY');
    expect(s.handPresent).toBe(false);
    expect(s.gesture).toBe('');
  });

  it('repeated identical hand frames do not create new states', () => {
    const a = reduce(running, { type: 'HAND', gesture: 'PEACE', confidence: 0.81 });
    expect(reduce(a, { type: 'HAND', gesture: 'PEACE', confidence: 0.79 })).toBe(a);
  });

  it('hand events are ignored unless running; pausing clears the hand', () => {
    expect(reduce(INITIAL_STATE, { type: 'HAND', gesture: 'FIST', confidence: 1 })).toBe(INITIAL_STATE);
    const withHand = reduce(running, { type: 'HAND', gesture: 'FIST', confidence: 1 });
    const paused = reduce(withHand, { type: 'TAB_HIDDEN' });
    expect(paused.handPresent).toBe(false);
    expect(paused.gesture).toBe('');
  });

  it('a tracker failure is explained and leaves the camera running', () => {
    const s = reduce(running, { type: 'TRACKER_FAILED', message: 'nope' });
    expect(s.tracker).toBe('unavailable');
    expect(s.phase).toBe('running');
    expect(s.message).toBe('nope');
  });
});
