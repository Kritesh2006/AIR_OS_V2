"""
camera.py — Threaded webcam capture for AIR OS V01.

Runs the camera in a background thread so the UI never blocks.
If the camera is missing or fails, the app keeps running in
"limited mode" (no gestures) and reports a readable error.
"""

import threading
import time

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    CV2_AVAILABLE = False

from settings import settings


class CameraManager:
    """
    Background webcam reader.

    Usage:
        cam = CameraManager()
        cam.start()
        ok, frame = cam.read()   # latest BGR frame (or None)
        cam.stop()
    """

    def __init__(self):
        self._cap = None
        self._thread = None
        self._running = False
        self._lock = threading.Lock()
        self._frame = None
        self.available = False
        self.error = None  # human-readable error string, shown in HUD

    # ------------------------------------------------------------------ #
    def start(self):
        """Open the camera and start the capture thread. Never raises."""
        if not CV2_AVAILABLE:
            self.error = "OpenCV not installed — camera disabled"
            return False
        try:
            index = settings.camera_index
            # CAP_DSHOW opens much faster on Windows; harmless elsewhere.
            backend = getattr(cv2, "CAP_DSHOW", 0)
            self._cap = cv2.VideoCapture(index, backend)
            if not self._cap or not self._cap.isOpened():
                # Retry with the default backend before giving up.
                self._cap = cv2.VideoCapture(index)
            if not self._cap or not self._cap.isOpened():
                self.error = f"No camera found at index {index}"
                self._cap = None
                return False

            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, settings.camera_width)
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, settings.camera_height)

            self._running = True
            self.available = True
            self.error = None
            self._thread = threading.Thread(target=self._loop,
                                            name="CameraThread",
                                            daemon=True)
            self._thread.start()
            return True
        except Exception as exc:  # any driver weirdness => limited mode
            self.error = f"Camera error: {exc}"
            self.available = False
            return False

    def _loop(self):
        """Continuously grab frames; store only the newest one."""
        fail_streak = 0
        while self._running:
            try:
                ok, frame = self._cap.read()
            except Exception:
                ok, frame = False, None

            if ok and frame is not None:
                fail_streak = 0
                if settings.mirror_camera:
                    frame = cv2.flip(frame, 1)
                with self._lock:
                    self._frame = frame
            else:
                fail_streak += 1
                if fail_streak > 60:
                    # Camera was unplugged mid-session.
                    self.error = "Camera stopped responding (unplugged?)"
                    self.available = False
                    self._running = False
                    break
                time.sleep(0.02)

    # ------------------------------------------------------------------ #
    def read(self):
        """Return (ok, latest_frame). Frame is a BGR numpy array."""
        with self._lock:
            if self._frame is None:
                return False, None
            return True, self._frame.copy()

    def stop(self):
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        self.available = False
