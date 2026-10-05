/**
 * demoWindows.ts — The in-page AIR windows W2 can select and close, and
 * the ActionProvider that closes them. Nothing here touches the real OS;
 * a browser page can only close what it owns.
 */

import type { AirWindow } from '../contracts';
import type { ActionProvider, ActionResult, Target } from '../core/actions';

export const DEMO_WINDOWS: readonly AirWindow[] = Object.freeze([
  { id: 'notes', app: 'Notes', title: 'Ideas for AIR OS', icon: '📝', lines: ['Blink to confirm', 'Desktop companion', 'Phone PWA'] },
  { id: 'music', app: 'Music', title: 'Now playing — Lo-fi Focus', icon: '🎵', lines: ['▶ 1:24 / 3:58', 'Next: Night Drive'] },
  { id: 'browser', app: 'Browser', title: 'kritesh2006.github.io', icon: '🌐', lines: ['AIR OS — gesture control', 'Runs in your browser'] },
  { id: 'terminal', app: 'Terminal', title: 'air@os: ~', icon: '⌨️', lines: ['$ npm run check', '✓ all tests passed'] },
  { id: 'photos', app: 'Photos', title: 'Camera roll', icon: '🖼️', lines: ['128 photos', 'Last: today'] },
  { id: 'mail', app: 'Mail', title: 'Inbox (3)', icon: '✉️', lines: ['Sol: GO W2 🔥', 'Claude: deployed'] },
].map((w) => Object.freeze({ ...w, lines: Object.freeze([...w.lines]) })));

export class WindowStore {
  private open: AirWindow[] = [...DEMO_WINDOWS];
  private listeners: Array<(w: readonly AirWindow[]) => void> = [];

  get windows(): readonly AirWindow[] {
    return this.open;
  }

  get total(): number {
    return DEMO_WINDOWS.length;
  }

  onChange(cb: (w: readonly AirWindow[]) => void): void {
    this.listeners.push(cb);
  }

  close(id: string): boolean {
    const before = this.open.length;
    this.open = this.open.filter((w) => w.id !== id);
    if (this.open.length === before) return false;
    this.emit();
    return true;
  }

  reset(): void {
    this.open = [...DEMO_WINDOWS];
    this.emit();
  }

  private emit(): void {
    this.listeners.forEach((cb) => cb(this.open));
  }
}

/** Web counterpart of desktop CloseWindowProvider, for in-page windows. */
export class InPageWindowProvider implements ActionProvider {
  readonly id = 'close-window';
  readonly risk = 'high' as const;

  constructor(private readonly store: WindowStore) {}

  listTargets(): Target[] {
    return this.store.windows.map((w) => ({ id: w.id, label: w.app, sublabel: w.title, icon: w.icon }));
  }

  execute(target: Target): ActionResult {
    // Revalidate: the window may have gone since the targets were listed.
    if (!this.store.windows.some((w) => w.id === target.id)) {
      return { status: 'GONE_BEFORE', detail: `${target.label} was already closed` };
    }
    return this.store.close(target.id)
      ? { status: 'CLOSED', detail: `Closed ${target.label}` }
      : { status: 'FAILED', detail: `Could not close ${target.label}` };
  }
}
