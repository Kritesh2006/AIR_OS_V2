"""
settings.py — Central configuration for AIR OS V01.

All tunable values live here so users can adjust behaviour without
digging through code. Settings are loaded from / saved to
`airos_settings.json` next to the app; missing keys fall back to
the defaults below.
"""

import json
import os

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "airos_settings.json")

DEFAULTS = {
    # ---- Camera ----
    "camera_index": 0,          # which webcam to use (0 = default)
    "camera_width": 640,
    "camera_height": 480,
    "mirror_camera": True,      # mirror preview so it acts like a mirror

    # ---- Gestures ----
    "pinch_threshold": 0.055,   # thumb-index distance (normalized) that counts as a pinch
    "fist_hold_seconds": 1.0,   # hold a fist this long to close the active window
    "gesture_cooldown": 1.0,    # seconds between repeated discrete gestures
    "circle_min_radius": 0.03,  # min radius for the volume-circle gesture
    "swipe_min_distance": 0.28, # normalized distance for a swipe
    "volume_step": 4,           # % volume change per detected circle

    # ---- Mouse ----
    "mouse_smoothing": 0.35,    # 0..1, lower = smoother but laggier
    "mouse_speed": 1.6,         # cursor speed multiplier

    # ---- Voice ----
    "voice_enabled": True,
    "voice_energy_threshold": 300,   # mic sensitivity for speech detection
    "voice_pause_threshold": 0.6,    # silence (s) that ends a phrase

    # ---- UI ----
    "show_preview": True,
    "hud_opacity": 0.92,
    "theme": "dark",

    # ================= AIR OS V2 settings =================
    # ---- Mini HUD (top-left overlay) ----
    "air_hud_enabled": True,
    "air_hud_opacity": 0.92,

    # ---- Wake word + passcode ----
    # When True, AIR starts asleep: say "wake up", then the passcode.
    # Set to False to restore V1 behavior (always listening, no lock).
    "wake_word_enabled": True,
    "wake_word": "wake up",
    "passcode": "2331",

    # ---- Gesture sensitivity / DPI ----
    # gesture_sensitivity: >1.0 = triggers easier (bigger pinch zone,
    # shorter swipes); <1.0 = stricter. Applied on top of the raw
    # thresholds so you tune ONE number instead of many.
    "gesture_sensitivity": 1.0,
    "scroll_speed": 3,          # scroll clicks per scroll-gesture step

    # ---- Experimental gestures (OFF by default — see README) ----
    # Three-finger pinch (thumb+index+middle together) = click.
    # Disabled because it can collide with the V1 middle-finger TAP
    # click while pinching. Enable here if you prefer it.
    "three_finger_pinch_click": False,
    # Two-hand gestures (left fist + right index = scroll, left fist +
    # right palm wave = switch tabs). Needs two hands tracked, which
    # costs FPS on slower laptops. Enable here to try it.
    "two_hand_gestures": False,

    # ---- System resource monitor ----
    "monitor_enabled": True,
    "cpu_alert_percent": 85,     # alert when total CPU above this...
    "ram_alert_percent": 90,     # ...or RAM above this
    "monitor_sustained_samples": 3,   # for this many samples in a row
    "monitor_interval_seconds": 5,    # seconds between samples
    "monitor_alert_cooldown": 180,    # don't nag more than every 3 min
}


class Settings:
    """Dict-like settings object with load/save and attribute access."""

    def __init__(self):
        self._data = dict(DEFAULTS)
        self.load()

    def load(self):
        """Load settings file if present; ignore corrupt files safely."""
        try:
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                if isinstance(saved, dict):
                    for k, v in saved.items():
                        if k in DEFAULTS:
                            self._data[k] = v
        except (OSError, json.JSONDecodeError):
            # A broken settings file must never crash the app.
            self._data = dict(DEFAULTS)

    def save(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except OSError:
            pass  # read-only disk etc. — non-fatal

    def get(self, key, default=None):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value

    def __getattr__(self, name):
        # Called only when normal attribute lookup fails.
        data = object.__getattribute__(self, "_data")
        if name in data:
            return data[name]
        raise AttributeError(name)


# Single shared instance used across modules.
settings = Settings()
