"""
utils.py — Shared helper utilities for AIR OS V01.

Contains:
- FPSCounter: rolling FPS measurement
- Smoother: exponential smoothing for cursor movement
- CircleDetector: detects clockwise / anti-clockwise circular motion
  of a tracked point (used for the index-finger volume gesture)
- SwipeDetector: detects fast directional hand swipes
- Cooldown: simple action rate-limiter
- clamp / distance helpers
"""

import math
import time
from collections import deque


def clamp(value, lo, hi):
    """Clamp value into [lo, hi]."""
    return max(lo, min(hi, value))


def distance(p1, p2):
    """Euclidean distance between two (x, y) points."""
    return math.hypot(p1[0] - p2[0], p1[1] - p2[1])


class FPSCounter:
    """Rolling-average FPS counter. Call tick() once per frame."""

    def __init__(self, window=30):
        self._times = deque(maxlen=window)

    def tick(self):
        self._times.append(time.time())

    @property
    def fps(self):
        if len(self._times) < 2:
            return 0.0
        span = self._times[-1] - self._times[0]
        if span <= 0:
            return 0.0
        return (len(self._times) - 1) / span


class Smoother:
    """Exponential smoothing for a 2D point (reduces cursor jitter)."""

    def __init__(self, alpha=0.35):
        # alpha closer to 1 = more responsive, closer to 0 = smoother
        self.alpha = alpha
        self._last = None

    def update(self, point):
        if self._last is None:
            self._last = point
            return point
        x = self.alpha * point[0] + (1 - self.alpha) * self._last[0]
        y = self.alpha * point[1] + (1 - self.alpha) * self._last[1]
        self._last = (x, y)
        return self._last

    def reset(self):
        self._last = None


class Cooldown:
    """Blocks an action from repeating until `seconds` have passed."""

    def __init__(self, seconds):
        self.seconds = seconds
        self._last = 0.0

    def ready(self):
        return (time.time() - self._last) >= self.seconds

    def trigger(self):
        """Returns True (and starts cooldown) if ready, else False."""
        if self.ready():
            self._last = time.time()
            return True
        return False


class CircleDetector:
    """
    Detects circular motion of a point (e.g. the index fingertip).

    How it works:
    - Keeps a short history of positions.
    - Computes the centroid of the history.
    - Accumulates the signed angle swept around that centroid.
    - When |accumulated angle| exceeds `min_angle` (default ~0.75 of a
      full turn) AND the motion radius is large enough, a circle is
      reported: +1 = clockwise (screen coords), -1 = anti-clockwise.

    Note on direction: screen Y grows downward, so a *clockwise* circle
    as the user sees it produces a *positive* accumulated angle here.
    """

    def __init__(self, history=32, min_radius=0.03, min_angle=math.tau * 0.75):
        self._pts = deque(maxlen=history)
        self.min_radius = min_radius
        self.min_angle = min_angle
        self._accum = 0.0
        self._last_angle = None

    def reset(self):
        self._pts.clear()
        self._accum = 0.0
        self._last_angle = None

    def update(self, point):
        """
        Feed one (x, y) point (normalized 0..1 coordinates).
        Returns +1 (clockwise), -1 (anti-clockwise) or 0 (no circle yet).
        """
        self._pts.append(point)
        if len(self._pts) < 8:
            return 0

        cx = sum(p[0] for p in self._pts) / len(self._pts)
        cy = sum(p[1] for p in self._pts) / len(self._pts)

        # Average radius — ignore tiny jitter that isn't a real circle.
        avg_r = sum(distance(p, (cx, cy)) for p in self._pts) / len(self._pts)
        if avg_r < self.min_radius:
            self._accum = 0.0
            self._last_angle = None
            return 0

        angle = math.atan2(point[1] - cy, point[0] - cx)
        if self._last_angle is not None:
            d = angle - self._last_angle
            # Wrap into (-pi, pi] so crossing the +/-pi boundary is smooth.
            while d > math.pi:
                d -= math.tau
            while d < -math.pi:
                d += math.tau
            self._accum += d
        self._last_angle = angle

        if self._accum >= self.min_angle:
            self.reset()
            return 1   # clockwise on screen
        if self._accum <= -self.min_angle:
            self.reset()
            return -1  # anti-clockwise on screen
        return 0


class SwipeDetector:
    """
    Detects fast directional swipes of the whole hand (wrist landmark).

    A swipe fires when the wrist travels more than `min_dist`
    (normalized units) within `max_time` seconds, mostly along one axis.
    Returns one of: 'left', 'right', 'up', 'down', or None.
    """

    def __init__(self, min_dist=0.28, max_time=0.45):
        self.min_dist = min_dist
        self.max_time = max_time
        self._hist = deque(maxlen=24)  # (time, x, y)

    def reset(self):
        self._hist.clear()

    def update(self, point):
        now = time.time()
        self._hist.append((now, point[0], point[1]))

        # Drop samples older than max_time.
        while self._hist and now - self._hist[0][0] > self.max_time:
            self._hist.popleft()
        if len(self._hist) < 4:
            return None

        t0, x0, y0 = self._hist[0]
        dx = point[0] - x0
        dy = point[1] - y0

        if abs(dx) >= self.min_dist and abs(dx) > abs(dy) * 1.6:
            self._hist.clear()
            return 'right' if dx > 0 else 'left'
        if abs(dy) >= self.min_dist and abs(dy) > abs(dx) * 1.6:
            self._hist.clear()
            return 'down' if dy > 0 else 'up'
        return None
