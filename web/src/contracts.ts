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

/** Lifecycle of the AIR session. */
export type AirPhase =
  | 'idle' // not started yet: show the Start AIR screen
  | 'requesting' // waiting for the browser camera permission / device
  | 'running' // camera live, AIR active
  | 'paused' // tab hidden: camera released, resumes automatically
  | 'denied' // the user (or browser policy) refused camera access
  | 'unavailable' // no camera, camera busy, or not a secure (HTTPS) page
  | 'error'; // anything else

/** Same vocabulary as the desktop PodStatus (see docs/CORE.md later). */
export type PodStatus =
  | 'READY'
  | 'PAUSED'
  | 'CLOSE?'
  | 'SELECT'
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
  /** W1: a hand is currently tracked. Always false in W0. */
  readonly handPresent: boolean;
  /** W1: current gesture label. '' in W0. */
  readonly gesture: string;
}

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
 * Test ids: `pod`, `pod-status`, `pod-video`, `pod-stop`.
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

/** Everything the app layer needs from the UI layer. */
export interface AirUi {
  readonly start: StartScreenView;
  readonly pod: PodView;
  readonly privacy: PrivacyView;
}
