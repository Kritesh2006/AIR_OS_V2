/**
 * main.ts — Wires camera, frame loop, state machine and UI together.
 * Integration layer: owned by Claude, reviewed by Sol.
 */

import './styles.css';
import type { AirUi, AirViewState } from '../contracts';
import { INITIAL_STATE, reduce, type AirEvent } from '../core/airState';
import { FpsCounter } from '../core/fps';
import { CameraController, classifyCameraError } from '../vision/camera';
import { FrameSource } from '../vision/frameSource';
import { createPlaceholderUi } from './placeholderUi';

const FPS_PUBLISH_MS = 500;
const START_VISIBLE = new Set<AirViewState['phase']>(['idle', 'requesting', 'denied', 'unavailable', 'error']);

export function startApp(root: HTMLElement, ui: AirUi = createPlaceholderUi()): void {
  const camera = new CameraController();
  const fps = new FpsCounter();
  let lastFpsPublish = 0;
  let state: AirViewState = INITIAL_STATE;

  const frames = new FrameSource((_video, ts) => {
    fps.tick(ts);
    if (ts - lastFpsPublish >= FPS_PUBLISH_MS) {
      lastFpsPublish = ts;
      dispatch({ type: 'FPS', fps: fps.fps });
    }
  });

  function render(): void {
    // Test/debug hook: the current phase is visible on <html data-air-phase>.
    document.documentElement.dataset.airPhase = state.phase;
    ui.start.setVisible(START_VISIBLE.has(state.phase));
    ui.pod.setVisible(!START_VISIBLE.has(state.phase));
    ui.start.render(state);
    ui.pod.render(state);
  }

  function dispatch(ev: AirEvent): void {
    const nextState = reduce(state, ev);
    if (nextState !== state) {
      state = nextState;
      render();
    }
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
  }

  ui.start.mount(root);
  ui.pod.mount(root);
  ui.privacy.mount(root);

  ui.start.onStart(() => {
    if (state.phase === 'requesting') return;
    dispatch({ type: 'START_REQUESTED' });
    void startCamera();
  });
  ui.start.onPrivacy(() => ui.privacy.open());
  ui.pod.onStop(() => {
    releaseCamera();
    dispatch({ type: 'STOPPED' });
  });

  // A hidden tab gets throttled anyway: release the camera entirely and
  // resume when the person comes back.
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden' && state.phase === 'running') {
      releaseCamera();
      dispatch({ type: 'TAB_HIDDEN' });
    } else if (document.visibilityState === 'visible' && state.phase === 'paused') {
      dispatch({ type: 'TAB_VISIBLE' });
      void startCamera();
    }
  });

  render();
}

const root = document.getElementById('air');
if (root) startApp(root);
