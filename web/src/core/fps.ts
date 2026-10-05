/** Rolling frames-per-second counter over the last `window` frames. */
export class FpsCounter {
  private readonly times: number[] = [];

  constructor(private readonly window = 30) {}

  /** Record a frame at `tsMs` (any monotonic clock). */
  tick(tsMs: number): void {
    this.times.push(tsMs);
    if (this.times.length > this.window) this.times.shift();
  }

  get fps(): number {
    const n = this.times.length;
    if (n < 2) return 0;
    const span = this.times[n - 1] - this.times[0];
    return span > 0 ? ((n - 1) * 1000) / span : 0;
  }

  reset(): void {
    this.times.length = 0;
  }
}
