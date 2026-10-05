"""
sensor_worker.py — The SensorWorker thread (see docs/ARCHITECTURE.md §3).

Owns everything that interprets the camera: hand tracking, the gesture
engine (through a router) and, from Phase 2, the interaction session.
It never touches Tk. Output goes through LatestState (newest snapshot)
and EventQueue (events that must not be dropped); input arrives through
CommandQueue.

Loop:
  drain commands → newest camera frame (skip if seq unchanged)
  → hand tracking with the frame's own ts_ms → router.on_frame()
  → publish UiSnapshot
"""

import threading
import time
import traceback

from channels import CommandKind, EventKind
from contracts import FrameResult, HandObs, InteractionSnapshot, PodStatus, UiSnapshot
from settings import settings
from utils import FPSCounter

try:
    import cv2
except ImportError:
    cv2 = None


def make_preview(frame_bgr, max_size):
    """Downscale a BGR frame into a NEW small RGB array that fits in
    max_size (w, h). Returns None if OpenCV is unavailable."""
    if cv2 is None or frame_bgr is None:
        return None
    try:
        fh, fw = frame_bgr.shape[:2]
        scale = min(max_size[0] / fw, max_size[1] / fh)
        size = (max(1, int(fw * scale)), max(1, int(fh * scale)))
        small = cv2.resize(frame_bgr, size, interpolation=cv2.INTER_AREA)
        return cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    except Exception:
        return None


class PassthroughRouter:
    """Phase 1 stand-in for ModeRouter: NORMAL mode only, so every
    gesture behaves exactly like V2. Phase 2 replaces it with
    interaction.ModeRouter, which has the same interface."""

    needs_face = False

    def __init__(self, engine, events):
        self.engine = engine
        self.events = events
        self.legacy_popup_open = False
        self._hand_present = False

    @property
    def gesture_label(self):
        return self.engine.current_gesture

    def on_frame(self, fr):
        hands = fr.hands
        self._hand_present = bool(hands)
        if settings.get("two_hand_gestures"):
            self.engine.process_multi(
                [(list(h.landmarks), h.handedness) for h in hands])
        else:
            self.engine.process(list(hands[0].landmarks) if hands else None)

    def on_command(self, cmd):
        if cmd.kind == CommandKind.SET_GESTURES_PAUSED:
            paused = bool(cmd.data.get("paused"))
            self.engine.paused = paused
            self.events.emit(EventKind.STATUS, key="gesture",
                             text="PAUSED" if paused else "ON",
                             good=not paused)
        elif cmd.kind == CommandKind.SET_LEGACY_POPUP_OPEN:
            self.legacy_popup_open = bool(cmd.data.get("open"))
        # KEY_* commands have no meaning until Phase 2.

    def snapshot(self):
        status = PodStatus.PAUSED if self.engine.paused else PodStatus.READY
        return InteractionSnapshot.idle(status, self._hand_present)

    def shutdown(self):
        pass


class SensorWorker(threading.Thread):
    """Background thread: camera frames in, snapshots and events out."""

    IDLE_PUBLISH_S = 0.1    # snapshot rate when no frames arrive

    def __init__(self, camera, hand_tracker, router, state, events,
                 commands, face_tracker=None, error_sources=(),
                 preview_size=(192, 144), preview_enabled=True):
        super().__init__(name="SensorWorker", daemon=True)
        self.camera = camera
        self.tracker = hand_tracker
        self.face_tracker = face_tracker
        self.router = router
        self.state = state
        self.events = events
        self.commands = commands
        self.error_sources = tuple(error_sources)
        self.preview_size = preview_size
        self.preview_enabled = preview_enabled

        self.fps = FPSCounter()
        self._stop_requested = False
        self._last_seq = None
        self._publish_seq = 0
        self._last_publish = 0.0
        self._camera_down_reported = False

    # ------------------------------------------------------------------ #
    def stop(self):
        """Ask the worker to stop (thread-safe). WORKER_STOPPED follows."""
        self.commands.send(CommandKind.SHUTDOWN)

    def run(self):
        try:
            while not self._stop_requested:
                try:
                    self._handle_commands()
                    if self._stop_requested:
                        break
                    processed = self._step()
                    self._surface_errors()
                    if not processed:
                        if time.monotonic() - self._last_publish >= \
                                self.IDLE_PUBLISH_S:
                            self._publish(None)
                        time.sleep(0.004 if self.camera.available
                                   else 1 / 30)
                except Exception:
                    # The loop must never die — log and keep going.
                    traceback.print_exc()
                    time.sleep(0.05)
        finally:
            self._cleanup()
            self.events.emit(EventKind.WORKER_STOPPED)

    # ------------------------------------------------------------------ #
    def _handle_commands(self):
        for cmd in self.commands.drain():
            if cmd.kind == CommandKind.SHUTDOWN:
                self._stop_requested = True
            elif cmd.kind == CommandKind.SET_PREVIEW_ENABLED:
                self.preview_enabled = bool(cmd.data.get("on"))
            else:
                self.router.on_command(cmd)

    def _step(self):
        """Process the newest frame if there is one. True if processed."""
        if not self.camera.available:
            self._report_camera_down()
            return False
        ok, frame, ts_ms, seq = self.camera.read_latest()
        if not ok or seq == self._last_seq:
            return False
        self._last_seq = seq
        self.fps.tick()

        _landmarks, frame = self.tracker.process(
            frame, draw=self.preview_enabled, ts_ms=ts_ms)
        hands = tuple(HandObs(tuple(tuple(p) for p in pts), label)
                      for pts, label in getattr(self.tracker,
                                                "last_hands", []))
        face = None
        if self.face_tracker is not None and self.router.needs_face:
            face = self.face_tracker.process(frame, ts_ms)
        self.router.on_frame(FrameResult(seq, ts_ms, frame, hands, face))

        preview = make_preview(frame, self.preview_size) \
            if self.preview_enabled else None
        self._publish(preview)
        return True

    def _publish(self, preview):
        self._publish_seq += 1
        self._last_publish = time.monotonic()
        self.state.publish(UiSnapshot(
            seq=self._publish_seq,
            fps=self.fps.fps if self.camera.available else 0.0,
            gesture_label=self.router.gesture_label,
            preview_rgb=preview,
            interaction=self.router.snapshot()))

    def _report_camera_down(self):
        """Camera died mid-session: report it once."""
        err = getattr(self.camera, "error", None)
        if err and not self._camera_down_reported:
            self._camera_down_reported = True
            self.events.emit(EventKind.STATUS, key="camera", text="OFF",
                             good=False)
            self.events.emit(EventKind.STATUS, key="gesture", text="OFF",
                             good=False)
            self.events.emit(EventKind.ERROR, text=err)
            self.camera.error = None

    def _surface_errors(self):
        for src in self.error_sources:
            err = getattr(src, "error", None)
            if err:
                self.events.emit(EventKind.ERROR, text=err)
                src.error = None

    def _cleanup(self):
        for fn in (getattr(self.router, "shutdown", None),
                   getattr(self.face_tracker, "close", None),
                   getattr(self.tracker, "close", None),
                   getattr(self.camera, "stop", None)):
            if fn is None:
                continue
            try:
                fn()
            except Exception:
                traceback.print_exc()
