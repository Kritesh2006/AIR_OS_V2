"""
mouse_controller.py — Moves and clicks the real mouse cursor.

Wraps pyautogui with smoothing and relative "trackpad style" motion:
while pinching, moving your hand moves the cursor. All failures are
caught so a mouse hiccup never crashes the app.
"""

try:
    import pyautogui
    pyautogui.FAILSAFE = False  # we manage safety ourselves (Open Palm = pause)
    PYAUTOGUI_AVAILABLE = True
except Exception:
    pyautogui = None
    PYAUTOGUI_AVAILABLE = False

from settings import settings
from utils import Smoother, clamp


class MouseController:
    """Relative-motion cursor control driven by hand position."""

    def __init__(self):
        self.available = PYAUTOGUI_AVAILABLE
        self.error = None if PYAUTOGUI_AVAILABLE else "pyautogui missing — mouse disabled"
        self._smoother = Smoother(alpha=settings.mouse_smoothing)
        self._anchor_hand = None   # hand pos (normalized) when pinch began
        self._anchor_mouse = None  # cursor pos (pixels) when pinch began
        if self.available:
            try:
                self.screen_w, self.screen_h = pyautogui.size()
            except Exception:
                self.available = False
                self.error = "Could not read screen size"
                self.screen_w, self.screen_h = 1920, 1080
        else:
            self.screen_w, self.screen_h = 1920, 1080

    # ------------------------------------------------------------------ #
    def begin_move(self, hand_point):
        """Call when a pinch starts: anchors hand pos to cursor pos."""
        if not self.available:
            return
        try:
            self._anchor_hand = hand_point
            self._anchor_mouse = pyautogui.position()
            self._smoother.reset()
        except Exception as exc:
            self.error = f"Mouse error: {exc}"

    def move(self, hand_point):
        """Call each frame while pinching: moves cursor relative to anchor."""
        if not self.available or self._anchor_hand is None:
            return
        try:
            smoothed = self._smoother.update(hand_point)
            dx = (smoothed[0] - self._anchor_hand[0]) * self.screen_w * settings.mouse_speed
            dy = (smoothed[1] - self._anchor_hand[1]) * self.screen_h * settings.mouse_speed
            x = clamp(self._anchor_mouse[0] + dx, 0, self.screen_w - 1)
            y = clamp(self._anchor_mouse[1] + dy, 0, self.screen_h - 1)
            pyautogui.moveTo(x, y, _pause=False)
        except Exception as exc:
            self.error = f"Mouse error: {exc}"

    def end_move(self):
        """Call when the pinch is released."""
        self._anchor_hand = None
        self._anchor_mouse = None
        self._smoother.reset()

    # ------------------------------------------------------------------ #
    def left_click(self):
        self._safe(lambda: pyautogui.click(_pause=False))

    def double_click(self):
        self._safe(lambda: pyautogui.doubleClick(_pause=False))

    def right_click(self):
        self._safe(lambda: pyautogui.rightClick(_pause=False))

    def scroll(self, clicks):
        """Scroll the wheel: positive = up, negative = down."""
        self._safe(lambda: pyautogui.scroll(int(clicks), _pause=False))

    def position(self):
        """Current cursor position (x, y) or (0, 0) if unavailable."""
        if not self.available:
            return (0, 0)
        try:
            p = pyautogui.position()
            return (p.x, p.y)
        except Exception:
            return (0, 0)

    def _safe(self, fn):
        if not self.available:
            return
        try:
            fn()
        except Exception as exc:
            self.error = f"Mouse error: {exc}"
