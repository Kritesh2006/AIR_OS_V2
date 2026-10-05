/**
 * frameSource.ts — Delivers each NEW camera frame exactly once, with its
 * timestamp. W0 only counts frames for FPS; W1 runs hand tracking here.
 *
 * Uses requestVideoFrameCallback where available (fires once per decoded
 * frame) and falls back to requestAnimationFrame + currentTime checks.
 */

export type FrameHandler = (video: HTMLVideoElement, timestampMs: number) => void;

type VideoWithRvfc = HTMLVideoElement & {
  requestVideoFrameCallback?: (cb: (now: number, meta: { mediaTime: number }) => void) => number;
  cancelVideoFrameCallback?: (handle: number) => void;
};

export class FrameSource {
  readonly video: VideoWithRvfc;
  private handle: number | null = null;
  private lastMediaTime = -1;
  private running = false;

  constructor(private readonly onFrame: FrameHandler, doc: Document = document) {
    // Private, never-displayed element used for processing. The Pod shows
    // the stream in its own <video>.
    this.video = doc.createElement('video') as VideoWithRvfc;
    this.video.muted = true;
    this.video.playsInline = true;
    this.video.setAttribute('playsinline', '');
  }

  async attach(stream: MediaStream): Promise<void> {
    this.detach();
    this.video.srcObject = stream;
    await this.video.play();
    this.running = true;
    this.lastMediaTime = -1;
    this.schedule();
  }

  detach(): void {
    this.running = false;
    if (this.handle !== null) {
      if (this.video.cancelVideoFrameCallback) this.video.cancelVideoFrameCallback(this.handle);
      else cancelAnimationFrame(this.handle);
      this.handle = null;
    }
    this.video.pause();
    this.video.srcObject = null;
  }

  private schedule(): void {
    if (!this.running) return;
    if (this.video.requestVideoFrameCallback) {
      this.handle = this.video.requestVideoFrameCallback((now) => {
        this.emit(now);
        this.schedule();
      });
    } else {
      this.handle = requestAnimationFrame((now) => {
        if (this.video.currentTime !== this.lastMediaTime) {
          this.lastMediaTime = this.video.currentTime;
          this.emit(now);
        }
        this.schedule();
      });
    }
  }

  private emit(now: number): void {
    try {
      this.onFrame(this.video, now);
    } catch (err) {
      // One bad frame must never stop the loop.
      console.error('[AIR] frame handler failed', err);
    }
  }
}
