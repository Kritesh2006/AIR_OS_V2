/**
 * handTracker.ts — MediaPipe HandLandmarker running locally in the page.
 *
 * Model and wasm runtime are served from this site (see
 * scripts/prepare-assets.mjs); nothing is fetched from third parties and
 * no frame leaves the browser. Tries the GPU delegate first and falls back
 * to CPU if it cannot be created or fails at runtime.
 */

import { FilesetResolver, HandLandmarker, type HandLandmarkerResult } from '@mediapipe/tasks-vision';
import type { HandObservation } from '../core/hand';

export type Delegate = 'GPU' | 'CPU';

function assetUrl(path: string): string {
  return new URL(`${import.meta.env.BASE_URL}${path}`, window.location.href).href;
}

export function toObservations(res: HandLandmarkerResult): HandObservation[] {
  return res.landmarks.map((lm, i) => ({
    landmarks: lm.map((p) => ({ x: p.x, y: p.y, z: p.z })),
    handedness: res.handedness[i]?.[0]?.categoryName ?? 'Unknown',
    score: res.handedness[i]?.[0]?.score ?? 1,
  }));
}

export class HandTracker {
  private landmarker: HandLandmarker | null = null;
  private loading: Promise<Delegate> | null = null;
  private lastTs = -1;
  delegate: Delegate | null = null;

  get ready(): boolean {
    return this.landmarker !== null;
  }

  /** Load once; later calls return the same promise. */
  load(): Promise<Delegate> {
    this.loading ??= this.create('GPU').catch(() => this.create('CPU'));
    this.loading.catch(() => {
      this.loading = null; // allow a retry on the next Start
    });
    return this.loading;
  }

  private async create(delegate: Delegate): Promise<Delegate> {
    const fileset = await FilesetResolver.forVisionTasks(assetUrl('mediapipe/wasm'));
    const lm = await HandLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: assetUrl('models/hand_landmarker.task'), delegate },
      runningMode: 'VIDEO',
      numHands: 1,
      minHandDetectionConfidence: 0.5,
      minHandPresenceConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });
    this.landmarker?.close();
    this.landmarker = lm;
    this.delegate = delegate;
    return delegate;
  }

  /**
   * Run on one NEW video frame. Synchronous, so calls never queue up: the
   * frame loop simply skips frames that arrive while this runs.
   */
  detect(video: HTMLVideoElement, tsMs: number): HandObservation[] {
    if (!this.landmarker) return [];
    // VIDEO mode needs strictly increasing timestamps.
    const ts = Math.max(Math.round(tsMs), this.lastTs + 1);
    this.lastTs = ts;
    try {
      return toObservations(this.landmarker.detectForVideo(video, ts));
    } catch (err) {
      if (this.delegate === 'GPU') {
        console.warn('[AIR] GPU hand tracking failed, switching to CPU', err);
        this.landmarker.close();
        this.landmarker = null;
        this.loading = this.create('CPU');
        void this.loading.catch((e) => console.error('[AIR] CPU fallback failed', e));
        return [];
      }
      throw err;
    }
  }
}
