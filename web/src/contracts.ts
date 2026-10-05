/**
 * contracts.ts — Interfaces between the app layer (Claude) and the UI layer
 * (Sol). Changing anything here is a contract change: both sides review it.
 *
 * Rules:
 *  - UI modules never call camera / vision / core code directly. They render
 *    AirViewState and report user intent through the callbacks below.
 *  - render() is called only when the state changes (plus ~2 Hz for fps),
 *    never per camera frame.
 *  - Keep the data-testid values listed on each view; the e2e tests use them.
 */

import type { GestureName } from './core/gestures';
import type { HandObservation } from './core/hand';
import type { InteractionSnapshot } from './core/interaction';
import type { CursorSample } from './core/pointer';

export type { CursorSample, GestureName, HandObservation, InteractionSnapshot };

/** Lifecycle of the AIR session. */
export type AirPhase =
  | 'idle' // not started yet: show the Start AIR screen
  | 'requesting' // waiting for the browser camera permission / device
  | 'running' // camera live, AIR active
  | 'paused' // tab hidden: camera released, resumes automatically
  | 'denied' // the user (or browser policy) refused camera access
  | 'unavailable' // no camera, camera busy, or not a secure (HTTPS) page
  | 'error'; // anything else

/** Same vocabulary as the desktop PodStatus, plus web's HAND. */
export type PodStatus =
  | 'READY'
  | 'HAND'
  | 'PAUSED'
  | 'CLOSE?'
  | 'SELECT'
  | 'CONFIRM' // W2: locked card waiting for Enter / tap / pinch (blink in W3)
  | 'BLINK'
  | 'CLOSING…'
  | 'CLOSED'
  | 'STILL OPEN'
  | 'CANCELLED';

export interface AirViewState {
  readonly phase: AirPhase;
  readonly podStatus: PodStatus;
  /** Short human-readable status or error text ('' when nothing to say). */
  readonly message: string;
  /** Camera frames per second; 0 when not running. */
  readonly fps: number;
  /** Hand tracking model: off until Start, then loading → ready (or unavailable). */
  readonly tracker: TrackerStatus;
  /** A hand is currently tracked (stabilized). */
  readonly handPresent: boolean;
  /** Stable gesture, or '' when no hand. */
  readonly gesture: GestureName | '';
  /** Hand confidence 0..1, rounded to 0.1 (0 when no hand). */
  readonly handConfidence: number;
  /** Interaction-driven Pod status (CLOSE?, SELECT, …); null = none. */
  readonly actionStatus: PodStatus | null;
  /** One-line instruction for the current interaction step ('' = none). */
  readonly hint: string;
}

export type TrackerStatus = 'off' | 'loading' | 'ready' | 'unavailable';

/**
 * Full-screen entry view. Visible while phase is idle / requesting /
 * denied / unavailable / error.
 * Test ids: `start-button`, `start-message`, `privacy-link`.
 */
export interface StartScreenView {
  mount(root: HTMLElement): void;
  onStart(cb: () => void): void;
  onPrivacy(cb: () => void): void;
  render(state: AirViewState): void;
  setVisible(visible: boolean): void;
}

/**
 * Tiny top-left camera Pod. Visible while phase is running / paused.
 * The Pod shows the stream in its own <video muted playsinline>; it must
 * not keep a reference to the stream after setStream(null).
 * Test ids: `pod`, `pod-status`, `pod-gesture`, `pod-video`, `pod-stop`.
 */
export interface PodView {
  mount(root: HTMLElement): void;
  setStream(stream: MediaStream | null): void;
  onStop(cb: () => void): void;
  render(state: AirViewState): void;
  setVisible(visible: boolean): void;
}

/**
 * Privacy explanation (what the camera is used for, nothing leaves the
 * device). Test ids: `privacy-dialog`, `privacy-close`.
 */
export interface PrivacyView {
  mount(root: HTMLElement): void;
  open(): void;
  close(): void;
}

/**
 * The AIR virtual cursor. update() is called once per animation frame
 * (NOT through render()); move it with CSS transforms only. It must never
 * capture pointer events. Test id: `air-cursor`.
 */
export interface CursorView {
  mount(root: HTMLElement): void;
  update(sample: CursorSample & { readonly gesture: GestureName | '' }): void;
}

/**
 * Developer visualization of the raw landmarks. Off by default; toggled
 * with the D key or the ?debug URL parameter. drawHands() is called once
 * per tracker frame while enabled. Landmarks are unmirrored camera
 * coordinates; mirror x when drawing. Test id: `debug-layer`.
 */
export interface DebugLayerView {
  mount(root: HTMLElement): void;
  setEnabled(on: boolean): void;
  drawHands(hands: readonly HandObservation[]): void;
}

/** A mock in-page AIR window (W2 demo content). */
export interface AirWindow {
  readonly id: string;
  readonly app: string;
  readonly title: string;
  readonly icon: string;
  readonly lines: readonly string[];
}

/**
 * The page's "desktop": mock AIR windows in NORMAL mode, and the close
 * selection (dim layer + centered cards at the given rects) in
 * CLOSE_SELECTION. render() is called whenever the interaction snapshot
 * changes — up to once per tracker frame while progress values move —
 * so keep it cheap. Cards must be clickable/tappable; the cursor is not.
 * Test ids: `workspace`, `air-window` (data-window-id), `arm-indicator`,
 * `selection-overlay`, `select-card` (data-target-id, data-hovered,
 * data-locked), `confirm-button`, `cancel-button`, `reset-windows`.
 */
export interface WorkspaceView {
  mount(root: HTMLElement): void;
  setVisible(visible: boolean): void;
  setWindows(windows: readonly AirWindow[], total: number): void;
  render(snapshot: InteractionSnapshot): void;
  onTargetTap(cb: (id: string) => void): void;
  onConfirmTap(cb: () => void): void;
  onCancelTap(cb: () => void): void;
  onReset(cb: () => void): void;
}

/** Everything the app layer needs from the UI layer. */
export interface AirUi {
  readonly start: StartScreenView;
  readonly pod: PodView;
  readonly privacy: PrivacyView;
  readonly cursor: CursorView;
  readonly debug: DebugLayerView;
  readonly workspace: WorkspaceView;
}
