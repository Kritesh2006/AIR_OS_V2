/**
 * camera.ts — The only place AIR calls getUserMedia. Frames stay in the
 * browser; nothing here sends data anywhere.
 */

import type { CameraFailureReason } from '../core/airState';

export interface CameraFailure {
  reason: CameraFailureReason;
  message: string;
}

export class CameraError extends Error {
  constructor(readonly failure: CameraFailure) {
    super(failure.message);
    this.name = 'CameraError';
  }
}

/** Ask for a modest resolution: tracking does not need more, phones thank us. */
export const DEFAULT_CONSTRAINTS: MediaStreamConstraints = {
  audio: false,
  video: {
    facingMode: 'user',
    width: { ideal: 640 },
    height: { ideal: 480 },
    frameRate: { ideal: 30, max: 30 },
  },
};

/** Map a getUserMedia rejection to something we can explain to a person. */
export function classifyCameraError(err: unknown): CameraFailure {
  if (err instanceof CameraError) return err.failure;
  const name = (err as { name?: string } | null)?.name ?? '';
  switch (name) {
    case 'NotAllowedError':
    case 'SecurityError':
    case 'PermissionDeniedError':
      return {
        reason: 'denied',
        message: 'Camera access was blocked. Allow the camera for this site in your browser settings, then press Start AIR again.',
      };
    case 'NotFoundError':
    case 'DevicesNotFoundError':
    case 'OverconstrainedError':
      return { reason: 'unavailable', message: 'No usable camera was found on this device.' };
    case 'NotReadableError':
    case 'TrackStartError':
      return {
        reason: 'unavailable',
        message: 'The camera is busy. Close other apps or tabs using it (Zoom, Teams, …) and try again.',
      };
    default:
      return { reason: 'error', message: `Could not start the camera${name ? ` (${name})` : ''}.` };
  }
}

export class CameraController {
  private current: MediaStream | null = null;

  constructor(
    private readonly media: Pick<MediaDevices, 'getUserMedia'> | undefined = globalThis.navigator?.mediaDevices,
    private readonly secure: boolean = globalThis.isSecureContext ?? true,
    private readonly constraints: MediaStreamConstraints = DEFAULT_CONSTRAINTS,
  ) {}

  get stream(): MediaStream | null {
    return this.current;
  }

  /** Start (or return the already running) camera stream. Throws CameraError. */
  async start(): Promise<MediaStream> {
    if (this.current) return this.current;
    if (!this.secure) {
      throw new CameraError({
        reason: 'unavailable',
        message: 'AIR needs a secure (https://) page to use the camera.',
      });
    }
    if (!this.media?.getUserMedia) {
      throw new CameraError({ reason: 'unavailable', message: 'This browser does not support camera access.' });
    }
    try {
      this.current = await this.media.getUserMedia(this.constraints);
      return this.current;
    } catch (err) {
      throw new CameraError(classifyCameraError(err));
    }
  }

  /** Release the camera completely (the browser's camera light turns off). */
  stop(): void {
    this.current?.getTracks().forEach((t) => t.stop());
    this.current = null;
  }
}
