import { describe, expect, it } from 'vitest';
import { CameraController, CameraError, classifyCameraError } from '../../src/vision/camera';

const err = (name: string) => Object.assign(new Error(name), { name });

function fakeStream() {
  const stopped: boolean[] = [];
  const track = { stop: () => stopped.push(true) };
  return { stream: { getTracks: () => [track] } as unknown as MediaStream, stopped };
}

describe('classifyCameraError', () => {
  it.each([
    ['NotAllowedError', 'denied'],
    ['SecurityError', 'denied'],
    ['NotFoundError', 'unavailable'],
    ['OverconstrainedError', 'unavailable'],
    ['NotReadableError', 'unavailable'],
    ['AbortError', 'error'],
  ])('%s → %s', (name, reason) => {
    expect(classifyCameraError(err(name)).reason).toBe(reason);
  });

  it('explains a busy camera', () => {
    expect(classifyCameraError(err('NotReadableError')).message).toMatch(/busy/);
  });
});

describe('CameraController', () => {
  it('refuses on an insecure page without calling getUserMedia', async () => {
    let called = false;
    const cam = new CameraController({ getUserMedia: async () => { called = true; return fakeStream().stream; } }, false);
    await expect(cam.start()).rejects.toBeInstanceOf(CameraError);
    expect(called).toBe(false);
  });

  it('reports a browser without camera support', async () => {
    const cam = new CameraController(undefined, true);
    await expect(cam.start()).rejects.toMatchObject({ failure: { reason: 'unavailable' } });
  });

  it('wraps a permission rejection', async () => {
    const cam = new CameraController({ getUserMedia: async () => { throw err('NotAllowedError'); } }, true);
    await expect(cam.start()).rejects.toMatchObject({ failure: { reason: 'denied' } });
    expect(cam.stream).toBeNull();
  });

  it('starts once, reuses the stream, and stop() releases every track', async () => {
    const { stream, stopped } = fakeStream();
    let calls = 0;
    const cam = new CameraController({ getUserMedia: async () => { calls++; return stream; } }, true);
    expect(await cam.start()).toBe(stream);
    expect(await cam.start()).toBe(stream);
    expect(calls).toBe(1);
    cam.stop();
    expect(stopped).toEqual([true]);
    expect(cam.stream).toBeNull();
  });

  it('never asks for audio', async () => {
    let seen: MediaStreamConstraints | undefined;
    const cam = new CameraController({ getUserMedia: async (c) => { seen = c; return fakeStream().stream; } }, true);
    await cam.start();
    expect(seen?.audio).toBe(false);
  });
});
