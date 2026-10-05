/**
 * airState.ts — Pure lifecycle state machine for the AIR web session.
 * No DOM access, so it is unit-testable in Node.
 */

import type { AirPhase, AirViewState, PodStatus } from '../contracts';
import type { GestureName } from './gestures';

export type CameraFailureReason = 'denied' | 'unavailable' | 'error';

export type AirEvent =
  | { type: 'START_REQUESTED' }
  | { type: 'CAMERA_STARTED' }
  | { type: 'CAMERA_FAILED'; reason: CameraFailureReason; message: string }
  | { type: 'TAB_HIDDEN' }
  | { type: 'TAB_VISIBLE' }
  | { type: 'STOPPED' }
  | { type: 'FPS'; fps: number }
  | { type: 'TRACKER_LOADING' }
  | { type: 'TRACKER_READY' }
  | { type: 'TRACKER_FAILED'; message: string }
  | { type: 'HAND'; gesture: GestureName | null; confidence: number }
  | { type: 'INTERACTION'; status: PodStatus | null; hint: string };

const NO_HAND = { handPresent: false, gesture: '', handConfidence: 0, actionStatus: null, hint: '' } as const;

/** While running, the interaction's status wins over HAND / READY. */
function runningPod(s: Pick<AirViewState, 'actionStatus' | 'handPresent'>): PodStatus {
  return s.actionStatus ?? (s.handPresent ? 'HAND' : 'READY');
}

export const INITIAL_STATE: AirViewState = Object.freeze({
  phase: 'idle',
  podStatus: 'READY',
  message: '',
  fps: 0,
  tracker: 'off',
  ...NO_HAND,
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
        ? next(state, { phase: 'paused', podStatus: 'PAUSED', fps: 0, ...NO_HAND })
        : state;

    case 'TAB_VISIBLE':
      // The app restarts the camera; permission is already granted, so the
      // browser normally does not prompt again.
      return state.phase === 'paused'
        ? next(state, { phase: 'requesting', message: 'Resuming camera…' })
        : state;

    case 'STOPPED':
      return state.phase === 'running' || state.phase === 'paused'
        ? next(INITIAL_STATE, { message: 'AIR stopped. Camera is off.', tracker: state.tracker })
        : state;

    case 'FPS': {
      const fps = Math.round(ev.fps);
      return state.phase === 'running' && fps !== state.fps ? next(state, { fps }) : state;
    }

    // The model stays loaded across Stop/Start, so tracker status is
    // independent of the camera phase.
    case 'TRACKER_LOADING':
      return state.tracker === 'off' || state.tracker === 'unavailable'
        ? next(state, { tracker: 'loading' })
        : state;

    case 'TRACKER_READY':
      return state.tracker === 'ready' ? state : next(state, { tracker: 'ready' });

    case 'TRACKER_FAILED':
      return next(state, { tracker: 'unavailable', message: ev.message, ...NO_HAND,
        podStatus: state.phase === 'running' ? 'READY' : state.podStatus });

    case 'HAND': {
      if (state.phase !== 'running') return state;
      const present = ev.gesture !== null;
      const gesture = ev.gesture ?? '';
      const handConfidence = present ? Math.round(ev.confidence * 10) / 10 : 0;
      const podStatus = runningPod({ actionStatus: state.actionStatus, handPresent: present });
      if (present === state.handPresent && gesture === state.gesture &&
          handConfidence === state.handConfidence && podStatus === state.podStatus) {
        return state;
      }
      return next(state, { handPresent: present, gesture, handConfidence, podStatus });
    }

    case 'INTERACTION': {
      if (state.phase !== 'running') return state;
      if (ev.status === state.actionStatus && ev.hint === state.hint) return state;
      const podStatus = runningPod({ actionStatus: ev.status, handPresent: state.handPresent });
      return next(state, { actionStatus: ev.status, hint: ev.hint, podStatus });
    }
  }
}
