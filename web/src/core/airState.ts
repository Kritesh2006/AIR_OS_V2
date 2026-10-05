/**
 * airState.ts — Pure lifecycle state machine for the AIR web session.
 * No DOM access, so it is unit-testable in Node.
 */

import type { AirPhase, AirViewState } from '../contracts';

export type CameraFailureReason = 'denied' | 'unavailable' | 'error';

export type AirEvent =
  | { type: 'START_REQUESTED' }
  | { type: 'CAMERA_STARTED' }
  | { type: 'CAMERA_FAILED'; reason: CameraFailureReason; message: string }
  | { type: 'TAB_HIDDEN' }
  | { type: 'TAB_VISIBLE' }
  | { type: 'STOPPED' }
  | { type: 'FPS'; fps: number };

export const INITIAL_STATE: AirViewState = Object.freeze({
  phase: 'idle',
  podStatus: 'READY',
  message: '',
  fps: 0,
  handPresent: false,
  gesture: '',
});

const STARTABLE: ReadonlySet<AirPhase> = new Set(['idle', 'denied', 'unavailable', 'error']);

function next(state: AirViewState, patch: Partial<AirViewState>): AirViewState {
  return Object.freeze({ ...state, ...patch });
}

/**
 * Returns the next state, or the SAME object when the event does not apply,
 * so callers can skip re-rendering with a reference check.
 */
export function reduce(state: AirViewState, ev: AirEvent): AirViewState {
  switch (ev.type) {
    case 'START_REQUESTED':
      return STARTABLE.has(state.phase)
        ? next(state, { phase: 'requesting', message: 'Waiting for camera permission…' })
        : state;

    case 'CAMERA_STARTED':
      return state.phase === 'requesting'
        ? next(state, { phase: 'running', podStatus: 'READY', message: '' })
        : state;

    case 'CAMERA_FAILED':
      return state.phase === 'requesting'
        ? next(state, { phase: ev.reason, message: ev.message, fps: 0 })
        : state;

    case 'TAB_HIDDEN':
      return state.phase === 'running'
        ? next(state, { phase: 'paused', podStatus: 'PAUSED', fps: 0, handPresent: false, gesture: '' })
        : state;

    case 'TAB_VISIBLE':
      // The app restarts the camera; permission is already granted, so the
      // browser normally does not prompt again.
      return state.phase === 'paused'
        ? next(state, { phase: 'requesting', message: 'Resuming camera…' })
        : state;

    case 'STOPPED':
      return state.phase === 'running' || state.phase === 'paused'
        ? next(INITIAL_STATE, { message: 'AIR stopped. Camera is off.' })
        : state;

    case 'FPS': {
      const fps = Math.round(ev.fps);
      return state.phase === 'running' && fps !== state.fps ? next(state, { fps }) : state;
    }
  }
}
