/**
 * placeholderUi.ts — Minimal W0 implementation of the AirUi contract so the
 * pipeline works end to end. Sol's /web/src/ui replaces it at integration;
 * it exists only so W0 is deployable and testable.
 */

import type { AirUi, AirViewState, PodView, PrivacyView, StartScreenView } from '../contracts';

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
  private stop = el('button', { className: 'pod-stop', text: '×', testId: 'pod-stop' });

  mount(root: HTMLElement): void {
    this.video.muted = true;
    this.video.playsInline = true;
    this.video.setAttribute('playsinline', '');
    this.stop.title = 'Stop AIR (turns the camera off)';
    this.root.append(this.video, el('div', { className: 'pod-bar' }, [this.status, this.stop]));
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

export function createPlaceholderUi(): AirUi {
  return { start: new PlaceholderStart(), pod: new PlaceholderPod(), privacy: new PlaceholderPrivacy() };
}
