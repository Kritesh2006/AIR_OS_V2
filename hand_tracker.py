"""
hand_tracker.py — Hand detection for AIR OS V01 (dual-backend).

MediaPipe removed the legacy `solutions` API in versions >= 0.10.21,
which is what modern `pip install mediapipe` gives you (and the only
line with Python 3.13 wheels). So this tracker supports BOTH:

  1. TASKS backend (modern, preferred): mediapipe.tasks HandLandmarker.
     Needs the `hand_landmarker.task` model file. One is bundled with
     AIR OS; if missing, it is auto-downloaded on first run.
  2. LEGACY backend: mp.solutions.hands, used automatically on older
     mediapipe installs.

Landmark drawing is done with plain OpenCV so it works on every
mediapipe version. If everything fails, the app continues in limited
mode with a readable error.
"""

import os
import time
import urllib.request

from settings import settings

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    CV2_AVAILABLE = False

MP_AVAILABLE = False
MP_BACKEND = None  # "tasks" or "legacy"
mp = None
try:
    import mediapipe as mp
    if hasattr(mp, "solutions"):
        MP_BACKEND = "legacy"
        MP_AVAILABLE = True
    else:
        # Newer mediapipe: only the tasks API exists.
        from mediapipe.tasks.python import BaseOptions
        from mediapipe.tasks.python import vision as mp_vision
        MP_BACKEND = "tasks"
        MP_AVAILABLE = True
except Exception:
    mp = None

# Where the tasks-API model lives / gets downloaded to.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH = os.path.join(_APP_DIR, "hand_landmarker.task")
MODEL_URLS = [
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task",
    # Mirror in case Google storage is unreachable:
    "https://raw.githubusercontent.com/ai4ce/SeeDo/main/hand_landmarker.task",
]

# Landmark indices (identical in both backends — 21 points).
WRIST = 0
THUMB_TIP = 4
THUMB_IP = 3
INDEX_TIP = 8
INDEX_PIP = 6
MIDDLE_TIP = 12
MIDDLE_PIP = 10
RING_TIP = 16
RING_PIP = 14
PINKY_TIP = 20
PINKY_PIP = 18

# Bone connections for drawing the skeleton with OpenCV.
HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),          # thumb
    (0, 5), (5, 6), (6, 7), (7, 8),          # index
    (5, 9), (9, 10), (10, 11), (11, 12),     # middle
    (9, 13), (13, 14), (14, 15), (15, 16),   # ring
    (13, 17), (17, 18), (18, 19), (19, 20),  # pinky
    (0, 17),                                  # palm edge
]


def _ensure_model():
    """Make sure the tasks-API model file exists; download if needed."""
    if os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 1_000_000:
        return True, None
    last_err = None
    for url in MODEL_URLS:
        try:
            tmp = MODEL_PATH + ".part"
            urllib.request.urlretrieve(url, tmp)
            if os.path.getsize(tmp) > 1_000_000:
                os.replace(tmp, MODEL_PATH)
                return True, None
            os.remove(tmp)
        except Exception as exc:
            last_err = exc
    return False, (f"Hand model missing and download failed ({last_err}). "
                   f"Place hand_landmarker.task next to main.py.")


class HandTracker:
    """Detects one hand per frame and exposes its 21 landmarks."""

    def __init__(self):
        self.available = False
        self.error = None
        self.backend = MP_BACKEND
        self._legacy = None
        self._tasks = None
        self._last_ts = 0  # tasks VIDEO mode needs increasing timestamps
        # V2: two-hand gestures are opt-in (they cost FPS). When off,
        # we track exactly one hand — identical to V1.
        self.num_hands = 2 if settings.get("two_hand_gestures") else 1
        # After each process(): list of (landmarks, "Left"/"Right").
        self.last_hands = []

        if not MP_AVAILABLE:
            self.error = "MediaPipe not installed — gestures disabled"
            return
        try:
            if MP_BACKEND == "legacy":
                self._legacy = mp.solutions.hands.Hands(
                    static_image_mode=False, max_num_hands=self.num_hands,
                    model_complexity=0,
                    min_detection_confidence=0.6,
                    min_tracking_confidence=0.5)
            else:  # tasks
                ok, err = _ensure_model()
                if not ok:
                    self.error = err
                    return
                from mediapipe.tasks.python import BaseOptions
                from mediapipe.tasks.python import vision as mp_vision
                opts = mp_vision.HandLandmarkerOptions(
                    base_options=BaseOptions(model_asset_path=MODEL_PATH),
                    running_mode=mp_vision.RunningMode.VIDEO,
                    num_hands=self.num_hands,
                    min_hand_detection_confidence=0.5,
                    min_hand_presence_confidence=0.5,
                    min_tracking_confidence=0.5)
                self._tasks = mp_vision.HandLandmarker.create_from_options(opts)
            self.available = True
        except Exception as exc:
            self.error = f"Hand tracker failed to start: {exc}"

    # ------------------------------------------------------------------ #
    def process(self, frame_bgr, draw=True, ts_ms=None):
        """
        Detect a hand. Returns (landmarks, frame):
          landmarks — list of 21 (x, y) normalized tuples, or None
          frame     — same frame with the skeleton drawn (if found)
        ts_ms — the frame's capture timestamp (monotonic ms). When
        omitted, the current time is used.
        """
        if not self.available or frame_bgr is None:
            return None, frame_bgr
        try:
            rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            if self.backend == "legacy":
                res = self._legacy.process(rgb)
                if not res.multi_hand_landmarks:
                    self.last_hands = []
                    return None, frame_bgr
                self.last_hands = []
                for i, hand in enumerate(res.multi_hand_landmarks):
                    pts = [(p.x, p.y) for p in hand.landmark]
                    label = "Unknown"
                    try:
                        label = res.multi_handedness[i].classification[0].label
                    except Exception:
                        pass
                    self.last_hands.append((pts, label))
                landmarks = self.last_hands[0][0]
            else:
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                # VIDEO mode requires strictly increasing timestamps (ms).
                ts = int(ts_ms) if ts_ms is not None \
                    else int(time.monotonic() * 1000)
                if ts <= self._last_ts:
                    ts = self._last_ts + 1
                self._last_ts = ts
                res = self._tasks.detect_for_video(mp_img, ts)
                if not res.hand_landmarks:
                    self.last_hands = []
                    return None, frame_bgr
                self.last_hands = []
                for i, hand in enumerate(res.hand_landmarks):
                    pts = [(p.x, p.y) for p in hand]
                    label = "Unknown"
                    try:
                        label = res.handedness[i][0].category_name
                    except Exception:
                        pass
                    self.last_hands.append((pts, label))
                landmarks = self.last_hands[0][0]
        except Exception as exc:
            self.error = f"Hand tracking error: {exc}"
            return None, frame_bgr

        if draw:
            for pts, _label in self.last_hands:
                self._draw(frame_bgr, pts)
        return landmarks, frame_bgr

    # ------------------------------------------------------------------ #
    def _draw(self, frame, landmarks):
        """Draw the hand skeleton with OpenCV (backend-independent)."""
        try:
            h, w = frame.shape[:2]
            px = [(int(x * w), int(y * h)) for x, y in landmarks]
            for a, b in HAND_CONNECTIONS:
                cv2.line(frame, px[a], px[b], (204, 102, 255), 2)
            for i, p in enumerate(px):
                r = 5 if i in (4, 8, 12, 16, 20) else 3
                cv2.circle(frame, p, r, (255, 255, 255), -1)
                cv2.circle(frame, p, r, (237, 58, 124), 1)
        except Exception:
            pass  # drawing failure must never break tracking

    def close(self):
        try:
            if self._legacy is not None:
                self._legacy.close()
            if self._tasks is not None:
                self._tasks.close()
        except Exception:
            pass


# ---------------------------------------------------------------------- #
# Pose helpers — pure functions on the landmark list (unit-testable).
# ---------------------------------------------------------------------- #

def finger_extended(landmarks, tip, pip, wrist=WRIST):
    """A finger is extended when its tip is farther from the wrist
    than its PIP joint (works regardless of hand rotation)."""
    from utils import distance
    return distance(landmarks[tip], landmarks[wrist]) > \
        distance(landmarks[pip], landmarks[wrist]) * 1.08


def thumb_extended(landmarks):
    """Thumb: tip farther from the pinky base than the IP joint is."""
    from utils import distance
    pinky_base = landmarks[17]
    return distance(landmarks[THUMB_TIP], pinky_base) > \
        distance(landmarks[THUMB_IP], pinky_base) * 1.08


def get_finger_states(landmarks):
    """Dict of finger name -> bool (extended?)."""
    return {
        "thumb": thumb_extended(landmarks),
        "index": finger_extended(landmarks, INDEX_TIP, INDEX_PIP),
        "middle": finger_extended(landmarks, MIDDLE_TIP, MIDDLE_PIP),
        "ring": finger_extended(landmarks, RING_TIP, RING_PIP),
        "pinky": finger_extended(landmarks, PINKY_TIP, PINKY_PIP),
    }
