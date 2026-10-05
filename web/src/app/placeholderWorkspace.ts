/**
 * placeholderWorkspace.ts — Minimal W2 WorkspaceView: tiled demo windows,
 * a fist-arming indicator, and the close-selection overlay (dim layer +
 * cards at the rects the interaction core computed). Sol's src/ui
 * replaces it; it only draws what the snapshot says.
 */

import type { AirWindow, InteractionSnapshot, WorkspaceView } from '../contracts';

function div(className: string, testId?: string, text?: string): HTMLDivElement {
  const d = document.createElement('div');
  d.className = className;
  if (testId) d.dataset.testid = testId;
  if (text) d.textContent = text;
  return d;
}

function button(className: string, testId: string, text: string): HTMLButtonElement {
  const b = document.createElement('button');
  b.className = className;
  b.dataset.testid = testId;
  b.textContent = text;
  return b;
}

interface CardEls {
  root: HTMLDivElement;
  dwell: HTMLDivElement;
  confirmBar: HTMLDivElement;
  confirm: HTMLButtonElement;
}

export class PlaceholderWorkspace implements WorkspaceView {
  private root = div('workspace', 'workspace');
  private desk = div('desk');
  private reset = button('reset-windows', 'reset-windows', '↺ Restore windows');
  private help = div('desk-help', undefined, 'Hold a ✊ fist for 1 second to close a window');
  private arm = div('arm-indicator', 'arm-indicator');
  private armBar = div('progress-fill');
  private overlay = div('selection-overlay', 'selection-overlay');
  private overlayTitle = div('selection-title');
  private cancel = button('cancel-button', 'cancel-button', 'Cancel');
  private cardLayer = div('card-layer');
  private cards = new Map<string, CardEls>();
  private lastTargets: InteractionSnapshot['targets'] | null = null;
  private onTarget: (id: string) => void = () => undefined;
  private onConfirm: () => void = () => undefined;

  mount(root: HTMLElement): void {
    const armTrack = div('progress-track');
    armTrack.appendChild(this.armBar);
    this.arm.append(div('arm-label', undefined, '✊ Close a window?'), armTrack);
    this.arm.hidden = true;

    const header = div('selection-header');
    header.append(this.overlayTitle, this.cancel);
    this.overlay.append(header, this.cardLayer);
    this.overlay.hidden = true;

    this.root.append(this.help, this.desk, this.reset, this.arm, this.overlay);
    this.root.hidden = true;
    root.appendChild(this.root);
  }

  setVisible(visible: boolean): void {
    this.root.hidden = !visible;
  }

  setWindows(windows: readonly AirWindow[], total: number): void {
    this.desk.replaceChildren(
      ...windows.map((w) => {
        const win = div('air-window', 'air-window');
        win.dataset.windowId = w.id;
        const bar = div('air-window-bar');
        bar.append(div('air-window-dots', undefined, '● ● ●'), div('air-window-title', undefined, `${w.icon} ${w.app} — ${w.title}`));
        const body = div('air-window-body');
        w.lines.forEach((l) => body.appendChild(div('air-window-line', undefined, l)));
        win.append(bar, body);
        return win;
      }),
    );
    this.reset.hidden = windows.length === total;
  }

  render(s: InteractionSnapshot): void {
    // Fist arming.
    this.arm.hidden = s.state !== 'ARMING';
    this.armBar.style.transform = `scaleX(${s.armProgress})`;

    // Selection overlay.
    const selecting = s.mode === 'CLOSE_SELECTION';
    this.overlay.hidden = !selecting;
    if (!selecting) {
      this.lastTargets = null;
      this.cards.clear();
      this.cardLayer.replaceChildren();
      return;
    }
    this.overlayTitle.textContent = s.lockedId ? 'Confirm to close' : 'Point at the window to close';
    if (s.targets !== this.lastTargets) this.buildCards(s);
    for (const [id, c] of this.cards) {
      const hovered = s.hoveredId === id;
      const locked = s.lockedId === id;
      c.root.dataset.hovered = String(hovered);
      c.root.dataset.locked = String(locked);
      c.dwell.style.transform = `scaleX(${hovered && !locked ? s.dwellProgress : 0})`;
      c.confirm.hidden = !locked;
      c.confirmBar.style.transform = `scaleX(${locked ? s.confirmProgress : 0})`;
    }
  }

  private buildCards(s: InteractionSnapshot): void {
    this.lastTargets = s.targets;
    this.cards.clear();
    this.cardLayer.replaceChildren(
      ...s.targets.map((t) => {
        const r = s.rects[t.id];
        const card = div('select-card', 'select-card');
        card.dataset.targetId = t.id;
        card.style.transform = `translate(${r.x}px, ${r.y}px)`;
        card.style.width = `${r.w}px`;
        card.style.height = `${r.h}px`;
        const dwell = div('progress-fill dwell');
        const dwellTrack = div('progress-track card-track');
        dwellTrack.appendChild(dwell);
        const confirmBar = div('progress-fill confirm');
        const confirm = button('confirm-button', 'confirm-button', '✓ Close');
        confirm.hidden = true;
        confirm.appendChild(confirmBar);
        confirm.addEventListener('click', (e) => {
          e.stopPropagation();
          this.onConfirm();
        });
        card.addEventListener('click', () => this.onTarget(t.id));
        card.append(div('card-icon', undefined, t.icon), div('card-label', undefined, t.label), div('card-sub', undefined, t.sublabel), dwellTrack, confirm);
        this.cards.set(t.id, { root: card, dwell, confirmBar, confirm });
        return card;
      }),
    );
  }

  onTargetTap(cb: (id: string) => void): void {
    this.onTarget = cb;
  }

  onConfirmTap(cb: () => void): void {
    this.onConfirm = cb;
  }

  onCancelTap(cb: () => void): void {
    this.cancel.addEventListener('click', cb);
  }

  onReset(cb: () => void): void {
    this.reset.addEventListener('click', cb);
  }
}
