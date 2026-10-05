/**
 * placeholderUi.ts — Minimal W0 implementation of the AirUi contract so the
 * pipeline works end to end. Sol's /web/src/ui replaces it at integration;
 * it exists only so W0 is deployable and testable.
 */

import type {
  AirUi,
  AirViewState,
  CursorSample,
  CursorView,
  DebugLayerView,
  GestureName,
  HandObservation,
  PodView,
  PrivacyView,
  StartScreenView,
} from '../contracts';
import { HAND_CONNECTIONS } from '../core/hand';
import { PlaceholderWorkspace } from './placeholderWorkspace';

const GESTURE_ICON: Record<GestureName, string> = {
  'OPEN PALM': '🖐',
  FIST: '✊',
  POINT: '☝',
  PEACE: '✌',
  PINCH: '🤏',
  HAND: '✋',
};

function el<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  props: { className?: string; text?: string; testId?: string } = {},
  children: Node[] = [],
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (props.className) node.className = props.className;
  if (props.text) node.textContent = props.text;
  if (props.testId) node.dataset.testid = props.testId;
  children.forEach((c) => node.appendChild(c));
  return node;
}

class PlaceholderStart implements StartScreenView {
  private root = el('section', { className: 'start' });
  private button = el('button', { className: 'start-button', text: 'Start AIR', testId: 'start-button' });
  private message = el('p', { className: 'start-message', testId: 'start-message' });
  private privacy = el('button', { className: 'link', text: 'How AIR uses your camera', testId: 'privacy-link' });

  mount(root: HTMLElement): void {
    this.root.append(
      el('h1', { className: 'start-title', text: 'AIR OS' }),
      el('p', { className: 'start-sub', text: 'Control with your hands. Runs entirely in your browser.' }),
      this.button,
      this.message,
      this.privacy,
    );
    root.appendChild(this.root);
  }

  onStart(cb: () => void): void {
    this.button.addEventListener('click', cb);
  }

  onPrivacy(cb: () => void): void {
    this.privacy.addEventListener('click', cb);
  }

  render(state: AirViewState): void {
    this.button.disabled = state.phase === 'requesting';
    this.button.textContent = state.phase === 'idle' ? 'Start AIR' : state.phase === 'requesting' ? 'Starting…' : 'Try again';
    this.message.textContent = state.message;
    this.message.classList.toggle('is-error', ['denied', 'unavailable', 'error'].includes(state.phase));
  }

  setVisible(visible: boolean): void {
    this.root.hidden = !visible;
  }
}

class PlaceholderPod implements PodView {
  private root = el('aside', { className: 'pod', testId: 'pod' });
  private video = el('video', { className: 'pod-video', testId: 'pod-video' });
  private status = el('span', { className: 'pod-status', testId: 'pod-status' });
  private gesture = el('div', { className: 'pod-gesture', testId: 'pod-gesture' });
  private stop = el('button', { className: 'pod-stop', text: '×', testId: 'pod-stop' });

  mount(root: HTMLElement): void {
    this.video.muted = true;
    this.video.playsInline = true;
    this.video.setAttribute('playsinline', '');
    this.stop.title = 'Stop AIR (turns the camera off)';
    this.root.append(this.video, el('div', { className: 'pod-bar' }, [this.status, this.stop]), this.gesture);
    this.root.hidden = true;
    root.appendChild(this.root);
  }

  setStream(stream: MediaStream | null): void {
    this.video.srcObject = stream;
    if (stream) void this.video.play().catch(() => undefined);
  }

  onStop(cb: () => void): void {
    this.stop.addEventListener('click', cb);
  }

  render(state: AirViewState): void {
    this.status.textContent = `AIR • ${state.podStatus}`;
    this.root.dataset.phase = state.phase;
    this.root.dataset.hand = String(state.handPresent);
    this.gesture.textContent =
      state.tracker === 'loading' ? 'Loading hand tracking…'
      : state.tracker === 'unavailable' ? 'Hand tracking unavailable'
      : state.hint ? state.hint
      : state.gesture ? `${GESTURE_ICON[state.gesture]} ${state.gesture}`
      : state.phase === 'running' ? 'Raise your hand' : '';
  }

  setVisible(visible: boolean): void {
    this.root.hidden = !visible;
  }
}

class PlaceholderPrivacy implements PrivacyView {
  private root = el('dialog', { className: 'privacy', testId: 'privacy-dialog' });

  mount(root: HTMLElement): void {
    const close = el('button', { text: 'Close', testId: 'privacy-close' });
    close.addEventListener('click', () => this.close());
    this.root.append(
      el('h2', { text: 'Your camera stays on your device' }),
      el('p', {
        text:
          'AIR processes the camera image locally in this browser tab to follow your hand. ' +
          'No video or images are uploaded, stored or shared. There is no account and no API key.',
      }),
      el('p', { text: 'The camera turns off when you press × on the AIR Pod or leave this tab.' }),
      close,
    );
    root.appendChild(this.root);
  }

  open(): void {
    if (!this.root.open) this.root.showModal();
  }

  close(): void {
    this.root.close();
  }
}

class PlaceholderCursor implements CursorView {
  private root = el('div', { className: 'air-cursor', testId: 'air-cursor' });

  mount(root: HTMLElement): void {
    this.root.setAttribute('aria-hidden', 'true');
    root.appendChild(this.root);
  }

  update(c: CursorSample & { readonly gesture: GestureName | '' }): void {
    this.root.style.transform = `translate3d(${c.x}px, ${c.y}px, 0)`;
    this.root.style.opacity = c.visible ? String(0.45 + 0.55 * c.confidence) : '0';
    this.root.dataset.visible = String(c.visible);
    this.root.dataset.gesture = c.gesture;
    this.root.classList.toggle('is-pressed', c.pressed);
  }
}

class PlaceholderDebug implements DebugLayerView {
  private canvas = el('canvas', { className: 'debug-layer', testId: 'debug-layer' });
  private enabled = false;

  mount(root: HTMLElement): void {
    this.canvas.hidden = true;
    root.appendChild(this.canvas);
  }

  setEnabled(on: boolean): void {
    this.enabled = on;
    this.canvas.hidden = !on;
    if (!on) this.canvas.getContext('2d')?.clearRect(0, 0, this.canvas.width, this.canvas.height);
  }

  drawHands(hands: readonly HandObservation[]): void {
    if (!this.enabled) return;
    const w = (this.canvas.width = window.innerWidth);
    const h = (this.canvas.height = window.innerHeight);
    const ctx = this.canvas.getContext('2d');
    if (!ctx) return;
    ctx.clearRect(0, 0, w, h);
    const px = (p: { x: number; y: number }) => [(1 - p.x) * w, p.y * h] as const; // mirrored
    for (const hand of hands) {
      ctx.strokeStyle = 'rgba(124, 58, 237, 0.9)';
      ctx.lineWidth = 3;
      for (const [a, b] of HAND_CONNECTIONS) {
        const [ax, ay] = px(hand.landmarks[a]);
        const [bx, by] = px(hand.landmarks[b]);
        ctx.beginPath();
        ctx.moveTo(ax, ay);
        ctx.lineTo(bx, by);
        ctx.stroke();
      }
      ctx.fillStyle = '#e8eaf2';
      for (const p of hand.landmarks) {
        const [x, y] = px(p);
        ctx.beginPath();
        ctx.arc(x, y, 4, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }
}

export function createPlaceholderUi(): AirUi {
  return {
    start: new PlaceholderStart(),
    pod: new PlaceholderPod(),
    privacy: new PlaceholderPrivacy(),
    cursor: new PlaceholderCursor(),
    debug: new PlaceholderDebug(),
    workspace: new PlaceholderWorkspace(),
  };
}
