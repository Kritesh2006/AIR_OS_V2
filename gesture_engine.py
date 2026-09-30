"""
gesture_engine.py — Turns hand landmarks into actions.

This is a pure state machine: it takes the 21 landmarks each frame
and decides what gesture is happening, then calls the appropriate
controller. It has NO dependency on MediaPipe or the camera, so it
can be fully unit-tested with synthetic landmark data.

Gesture map (see README for the user-facing version):
  Index-only circle CW          -> volume up
  Index-only circle CCW         -> volume down
  Thumb+index pinch             -> mouse move mode
  Pinch + middle tap            -> left click
  Pinch + ring tap              -> double click
  Pinch + pinky tap             -> right click
  Fist (quick)                  -> close the confirmation overlay
  Fist held 1s                  -> close active window (Alt+F4)
  Open palm (held still)        -> pause / resume gesture tracking
  Peace sign                    -> toggle virtual keyboard
  Four fingers (no thumb)       -> screenshot
  Thumbs up                     -> play / pause media
  Fast swipe left/right         -> browser back / forward
  Fast swipe down / up          -> show desktop / task view
"""

import time

from hand_tracker import (INDEX_TIP, WRIST, get_finger_states)
from settings import settings
from utils import Cooldown, CircleDetector, SwipeDetector, distance


class GestureEngine:
    """Per-frame gesture recognizer + action dispatcher."""

    def __init__(self, mouse, keyboard, system, callbacks=None):
        """
        callbacks: dict of optional UI hooks —
          on_gesture(name)         current pose label for the HUD
          on_action(description)   last action performed, for the HUD
          toggle_keyboard()        show/hide virtual keyboard
          close_overlay()          dismiss the confirmation dialog
          set_paused(bool)         reflect pause state in the HUD
        """
        self.mouse = mouse
        self.keyboard = keyboard
        self.system = system
        self.cb = callbacks or {}

        self.paused = False
        self.current_gesture = "none"
        self.last_action = "—"

        # Detectors / timers
        # gesture_sensitivity (V2): one knob that scales everything.
        # >1.0 => gestures trigger more easily, <1.0 => stricter.
        sens = max(0.3, min(3.0, float(
            settings.get("gesture_sensitivity", 1.0))))
        self.sens = sens
        self._circle = CircleDetector(
            min_radius=settings.circle_min_radius / sens)
        self._swipe = SwipeDetector(
            min_dist=settings.swipe_min_distance / sens)
        self._cool = {
            "discrete": Cooldown(settings.gesture_cooldown),
            "swipe": Cooldown(0.8),
            "palm": Cooldown(1.5),
            "circle": Cooldown(0.35),
            "click": Cooldown(0.4),
        }

        # State
        self._scroll_anchor = None   # V2 two-hand scroll reference
        self._pinching = False
        self._fist_since = None
        self._fist_consumed = False
        self._palm_since = None
        self._palm_anchor = None
        self._tap_state = {"middle": True, "ring": True, "pinky": True}

    # ------------------------------------------------------------------ #
    def _emit(self, name, *args):
        fn = self.cb.get(name)
        if fn:
            try:
                fn(*args)
            except Exception:
                pass  # UI hooks must never break gesture processing

    def _action(self, text):
        self.last_action = text
        self._emit("on_action", text)

    def _set_gesture(self, name):
        self.current_gesture = name
        self._emit("on_gesture", name)

    # ------------------------------------------------------------------ #
    def process_multi(self, hands):
        """V2 two-hand entry point (used when settings.two_hand_gestures
        is True). `hands` = list of (landmarks, "Left"/"Right").
        With 0 or 1 hands — or with the feature disabled — behavior is
        EXACTLY the single-hand V1 pipeline.

        Two-hand gestures (left hand = modifier, right hand = action):
          left FIST + right INDEX up    -> scroll (index moves up/down)
          left FIST + right OPEN PALM,
             moving fast horizontally   -> switch tabs (Alt+Tab)
        Note: labels are the USER'S left/right (the preview is mirrored,
        which makes MediaPipe's handedness match the real hand)."""
        if not settings.get("two_hand_gestures") or not hands or \
                len(hands) < 2:
            self.process(hands[0][0] if hands else None)
            return

        left = right = None
        for pts, label in hands[:2]:
            if label == "Left":
                left = pts
            elif label == "Right":
                right = pts
        if left is None or right is None:
            self.process(hands[0][0])
            return

        lf = get_finger_states(left)
        rf = get_finger_states(right)
        left_fist = sum(lf.values()) == 0

        if left_fist and rf["index"] and not rf["middle"] and \
                not rf["ring"] and not rf["pinky"]:
            # Scroll mode: right index height drives the wheel.
            self._set_gesture("two-hand scroll")
            tip_y = right[INDEX_TIP][1]
            if self._scroll_anchor is None:
                self._scroll_anchor = tip_y
                return
            delta = self._scroll_anchor - tip_y  # up = positive
            if abs(delta) > 0.04:
                step = int(settings.get("scroll_speed", 3))
                self.mouse.scroll(step if delta > 0 else -step)
                self._scroll_anchor = tip_y
                self._action("Scroll " + ("up" if delta > 0 else "down"))
            return
        else:
            self._scroll_anchor = None

        if left_fist and sum(rf.values()) == 5:
            # Tab switch: right palm waving sideways fast.
            self._set_gesture("two-hand wave")
            swipe = self._swipe.update(right[WRIST])
            if swipe in ("left", "right") and self._cool["swipe"].trigger():
                self.keyboard.hotkey("alt", "tab")
                self._action("Switched tab/window")
            return

        # No two-hand pattern matched: fall back to the right hand
        # running the normal V1 single-hand pipeline.
        self.process(right)

    # ------------------------------------------------------------------ #
    def process(self, landmarks):
        """Call once per frame. `landmarks` may be None (no hand)."""
        if landmarks is None:
            self._release_all()
            self._set_gesture("none")
            return

        fingers = get_finger_states(landmarks)
        n_ext = sum(fingers.values())
        pinch_dist = distance(landmarks[4], landmarks[8])
        # A fist also brings the thumb and index tips close together, so a
        # pinch additionally requires the index or thumb to be reaching out
        # (i.e. NOT a fully curled fist).
        is_pinch = pinch_dist < settings.pinch_threshold * self.sens and \
            (fingers["index"] or fingers["thumb"])
        wrist = landmarks[WRIST]

        # ---- 1. Swipes: highest priority, work even while paused-ish ---
        swipe = self._swipe.update(wrist)
        if swipe and not self.paused and not is_pinch:
            if self._cool["swipe"].trigger():
                self._set_gesture(f"swipe {swipe}")
                self._do_swipe(swipe)
            return

        # ---- 2. Open palm: pause/resume (works even when paused!) ------
        is_palm = n_ext == 5 and not is_pinch
        if is_palm:
            self._handle_palm(wrist)
            # While paused, palm is the ONLY gesture we keep watching.
            if self.paused:
                return
            self._set_gesture("open palm")
            self._reset_non_palm()
            return
        else:
            self._palm_since = None
            self._palm_anchor = None
            self._palm_latched = False  # palm gone => next palm can toggle

        if self.paused:
            self._set_gesture("paused")
            return

        # ---- 3. Pinch: mouse mode + finger-tap clicks ------------------
        if is_pinch:
            self._static_pose = None
            self._handle_pinch(landmarks, fingers)
            return
        elif self._pinching:
            self._pinching = False
            self.mouse.end_move()
            self._reset_taps()

        # ---- 4. Fist: overlay close / hold to close window -------------
        is_fist = n_ext == 0
        if is_fist:
            self._static_pose = None
            self._handle_fist()
            return
        else:
            if self._fist_since and not self._fist_consumed:
                # Quick fist that was released before 1s => close overlay.
                self._emit("close_overlay")
                self._action("Closed overlay")
            self._fist_since = None
            self._fist_consumed = False

        # ---- 5. Index-only: volume circles ------------------------------
        if fingers["index"] and not fingers["middle"] and \
                not fingers["ring"] and not fingers["pinky"]:
            self._static_pose = None
            self._set_gesture("index point")
            spin = self._circle.update(landmarks[INDEX_TIP])
            if spin != 0 and self._cool["circle"].trigger():
                up = spin > 0  # clockwise on screen
                self.system.volume_step(up=up, step=settings.volume_step)
                self._action("Volume up" if up else "Volume down")
            return
        else:
            self._circle.reset()

        # ---- 6. Static poses --------------------------------------------
        # Each static pose fires ONCE per appearance: holding a peace sign
        # must not keep toggling the keyboard open and closed. The pose
        # must change (or the hand leave) before it can fire again.
        if fingers["index"] and fingers["middle"] and \
                not fingers["ring"] and not fingers["pinky"]:
            self._set_gesture("peace sign")
            if self._static_fire("peace") and self._cool["discrete"].trigger():
                self._emit("toggle_keyboard")
                self._action("Toggled virtual keyboard")
            return

        if not fingers["thumb"] and fingers["index"] and fingers["middle"] \
                and fingers["ring"] and fingers["pinky"]:
            self._set_gesture("four fingers")
            if self._static_fire("four") and self._cool["discrete"].trigger():
                path = self.system.screenshot()
                self._action("Screenshot saved" if path else "Screenshot failed")
            return

        # V2: pinky only = hide/show the AIR mini HUD.
        if fingers["pinky"] and not fingers["thumb"] and \
                not fingers["index"] and not fingers["middle"] and \
                not fingers["ring"]:
            self._set_gesture("pinky up")
            if self._static_fire("pinky") and self._cool["discrete"].trigger():
                self._emit("toggle_air_hud")
                self._action("Toggled AIR HUD")
            return

        if fingers["thumb"] and n_ext == 1:
            self._set_gesture("thumbs up")
            if self._static_fire("thumbs") and self._cool["discrete"].trigger():
                self.system.play_pause_media()
                self._action("Play/Pause media")
            return

        self._static_pose = None  # non-static pose => latches release
        self._set_gesture("hand detected")

    def _static_fire(self, name):
        """True exactly once per continuous appearance of a static pose."""
        if getattr(self, "_static_pose", None) == name:
            return False
        self._static_pose = name
        return True

    # ------------------------------------------------------------------ #
    def _handle_pinch(self, landmarks, fingers):
        self._set_gesture("pinch (mouse mode)")
        if not self._pinching:
            self._pinching = True
            # Anchor on the midpoint of thumb+index for stability.
            mid = ((landmarks[4][0] + landmarks[8][0]) / 2,
                   (landmarks[4][1] + landmarks[8][1]) / 2)
            self.mouse.begin_move(mid)
            self._reset_taps(fingers)
            self._action("Mouse mode ON")
        else:
            mid = ((landmarks[4][0] + landmarks[8][0]) / 2,
                   (landmarks[4][1] + landmarks[8][1]) / 2)
            self.mouse.move(mid)

        # V2 (optional, settings.three_finger_pinch_click): bringing the
        # MIDDLE fingertip into the pinch as well = click. Off by default
        # because it can collide with the V1 middle-finger TAP click.
        if settings.get("three_finger_pinch_click"):
            mid_dist = distance(landmarks[4], landmarks[12])
            if mid_dist < settings.pinch_threshold * self.sens and \
                    self._cool["click"].trigger():
                self.mouse.left_click()
                self._action("Left click (3-finger pinch)")

        # Finger taps while pinching: extended -> curled = tap.
        for finger, action, label in (
                ("middle", self.mouse.left_click, "Left click"),
                ("ring", self.mouse.double_click, "Double click"),
                ("pinky", self.mouse.right_click, "Right click")):
            was_ext = self._tap_state[finger]
            now_ext = fingers[finger]
            if was_ext and not now_ext and self._cool["click"].trigger():
                action()
                self._action(label)
            self._tap_state[finger] = now_ext

    def _handle_fist(self):
        self._set_gesture("fist")
        now = time.time()
        if self._fist_since is None:
            self._fist_since = now
            self._fist_consumed = False
        elif not self._fist_consumed and \
                now - self._fist_since >= settings.fist_hold_seconds:
            self._fist_consumed = True
            self.system.close_active_window()
            self._action("Closed active window")

    def _handle_palm(self, wrist):
        """Palm must be held roughly still for 0.6 s to toggle pause.
        A latch ensures ONE toggle per palm appearance — holding the
        palm up does not keep flipping pause on and off; the hand must
        leave (or change pose) before the palm can toggle again."""
        if getattr(self, "_palm_latched", False):
            return
        now = time.time()
        if self._palm_anchor is None:
            self._palm_anchor = wrist
            self._palm_since = now
            return
        if distance(wrist, self._palm_anchor) > 0.08:
            self._palm_anchor = wrist
            self._palm_since = now
            return
        if now - self._palm_since >= 0.6 and self._cool["palm"].trigger():
            self.paused = not self.paused
            self._palm_latched = True
            self._emit("set_paused", self.paused)
            self._action("Gestures PAUSED" if self.paused else "Gestures RESUMED")
            self._palm_since = now

    def _do_swipe(self, direction):
        if direction == "left":
            self.system.browser_back()
            self._action("Browser back")
        elif direction == "right":
            self.system.browser_forward()
            self._action("Browser forward")
        elif direction == "down":
            self.system.show_desktop()
            self._action("Show desktop")
        elif direction == "up":
            self.system.task_view()
            self._action("Task view")

    # ------------------------------------------------------------------ #
    def _reset_taps(self, fingers=None):
        for f in self._tap_state:
            self._tap_state[f] = fingers[f] if fingers else True

    def _reset_non_palm(self):
        self._circle.reset()
        self._fist_since = None
        if self._pinching:
            self._pinching = False
            self.mouse.end_move()

    def _release_all(self):
        """Hand left the frame: release everything safely."""
        self._reset_non_palm()
        self._palm_since = None
        self._palm_anchor = None
        self._palm_latched = False
        self._static_pose = None
        self._swipe.reset()
