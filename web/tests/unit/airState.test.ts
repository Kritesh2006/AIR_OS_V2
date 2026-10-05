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
