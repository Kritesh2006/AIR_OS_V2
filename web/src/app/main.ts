/**
 * main.ts — Wires camera, hand tracking, gestures, cursor, state machine
 * and UI together. Integration layer: owned by Claude, reviewed by Sol.
 *
 * Two loops:
 *  - frame loop (once per NEW camera frame): hand tracking → gesture →
 *    pointer target. Inference is synchronous, so it never queues.
 *  - animation loop (requestAnimationFrame): CursorView.update() only.
 */

import './styles.css';
import type { AirUi, AirViewState } from '../contracts';
import { INITIAL_STATE, reduce, type AirEvent } from '../core/airState';
import { FpsCounter } from '../core/fps';
import { classifyGesture, GestureStabilizer } from '../core/gestures';
import { LM } from '../core/hand';
import { PointerController } from '../core/pointer';
import { CameraController, classifyCameraError } from '../vision/camera';
import { FrameSource } from '../vision/frameSource';
import { HandTracker } from '../vision/handTracker';
import { createPlaceholderUi } from './placeholderUi';

const FPS_PUBLISH_MS = 500;
const START_VISIBLE = new Set<AirViewState['phase']>(['idle', 'requesting', 'denied', 'unavailable', 'error']);

export function startApp(root: HTMLElement, ui: AirUi = createPlaceholderUi()): void {
  const camera = new CameraController();
  const tracker = new HandTracker();
  const gestures = new GestureStabilizer();
  const pointer = new PointerController();
  const fps = new FpsCounter();
  let lastFpsPublish = 0;
  let state: AirViewState = INITIAL_STATE;
  let debug = new URLSearchParams(window.location.search).has('debug');
  let rafHandle: number | null = null;

  const frames = new FrameSource((video, ts) => {
    fps.tick(ts);
    if (ts - lastFpsPublish >= FPS_PUBLISH_MS) {
      lastFpsPublish = ts;
      dispatch({ type: 'FPS', fps: fps.fps });
    }
    if (!tracker.ready) return;

    const hands = tracker.detect(video, ts);
    const hand = hands[0] ?? null;
    const aspect = video.videoWidth && video.videoHeight ? video.videoWidth / video.videoHeight : 4 / 3;
    const raw = hand ? classifyGesture(hand.landmarks, aspect) : null;
    const stable = gestures.update(raw, ts);
    const viewport = { width: window.innerWidth, height: window.innerHeight };
    pointer.update(hand ? hand.landmarks[LM.INDEX_TIP] : null, ts, viewport, hand?.score ?? 0, stable === 'PINCH');
    dispatch({ type: 'HAND', gesture: stable, confidence: hand?.score ?? 0 });
    if (debug) ui.debug.drawHands(hands);
  });

  function animate(now: number): void {
    ui.cursor.update({ ...pointer.sample(now), gesture: state.gesture });
    rafHandle = requestAnimationFrame(animate);
  }

  function setAnimating(on: boolean): void {
    if (on && rafHandle === null) rafHandle = requestAnimationFrame(animate);
    if (!on && rafHandle !== null) {
      cancelAnimationFrame(rafHandle);
      rafHandle = null;
      ui.cursor.update({ x: 0, y: 0, visible: false, confidence: 0, pressed: false, gesture: '' });
    }
  }

  function render(): void {
    // Test/debug hooks on <html>.
    const html = document.documentElement.dataset;
    html.airPhase = state.phase;
    html.airTracker = state.tracker;
    html.airGesture = state.gesture;
    ui.start.setVisible(START_VISIBLE.has(state.phase));
    ui.pod.setVisible(!START_VISIBLE.has(state.phase));
    ui.start.render(state);
    ui.pod.render(state);
    setAnimating(state.phase === 'running');
  }

  function dispatch(ev: AirEvent): void {
    const nextState = reduce(state, ev);
    if (nextState !== state) {
      state = nextState;
      render();
    }
  }

  function loadTracker(): void {
    if (tracker.ready) return;
    dispatch({ type: 'TRACKER_LOADING' });
    tracker.load().then(
      () => dispatch({ type: 'TRACKER_READY' }),
      (err) => {
        console.error('[AIR] hand tracking failed to load', err);
        dispatch({ type: 'TRACKER_FAILED', message: 'Hand tracking could not start on this device. The camera still works.' });
      },
    );
  }

  async function startCamera(): Promise<void> {
    try {
      const stream = await camera.start();
      await frames.attach(stream);
      ui.pod.setStream(stream);
      dispatch({ type: 'CAMERA_STARTED' });
    } catch (err) {
      releaseCamera();
      const failure = classifyCameraError(err);
      dispatch({ type: 'CAMERA_FAILED', reason: failure.reason, message: failure.message });
    }
  }

  function releaseCamera(): void {
    frames.detach();
    ui.pod.setStream(null);
    camera.stop();
    fps.reset();
    gestures.reset();
    pointer.reset();
    if (debug) ui.debug.drawHands([]);
  }

  ui.start.mount(root);
  ui.pod.mount(root);
  ui.privacy.mount(root);
  ui.debug.mount(root);
  ui.cursor.mount(root);
  ui.debug.setEnabled(debug);

  ui.start.onStart(() => {
    if (state.phase === 'requesting') return;
    dispatch({ type: 'START_REQUESTED' });
    // Camera first so the Pod appears instantly; the model loads right after
    // (compiling it briefly occupies the main thread).
    void startCamera().then(() => {
      if (state.phase === 'running') loadTracker();
    });
  });
  ui.start.onPrivacy(() => ui.privacy.open());
  ui.pod.onStop(() => {
    releaseCamera();
    dispatch({ type: 'STOPPED' });
  });

  // Developer view: D toggles the landmark skeleton.
  window.addEventListener('keydown', (e) => {
    const typing = e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement;
    if (!typing && !e.repeat && (e.key === 'd' || e.key === 'D') && !e.ctrlKey && !e.metaKey && !e.altKey) {
      debug = !debug;
      ui.debug.setEnabled(debug);
    }
  });

  // A hidden tab gets throttled anyway: release the camera entirely and
  // resume when the person comes back.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && state.phase === 'running') {
      releaseCamera();
      dispatch({ type: 'TAB_HIDDEN' });
    } else if (document.visibilityState === 'visible' && state.phase === 'paused') {
      dispatch({ type: 'TAB_VISIBLE' });
      void startCamera().then(() => {
        if (state.phase === 'running') loadTracker();
      });
    }
  });

  render();
}

const root = document.getElementById('air');
if (root) startApp(root);
