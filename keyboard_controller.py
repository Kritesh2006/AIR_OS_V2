"""
keyboard_controller.py — Sends keystrokes to the active window.

Used by the virtual keyboard and by system actions (Win+D, Win+Tab,
media keys, etc.). Prefers the `keyboard` library (works even when
our window has focus quirks) and falls back to pyautogui.
"""

try:
    import keyboard as kb_lib
    KB_AVAILABLE = True
except Exception:
    # `keyboard` needs admin on some systems; fall back gracefully.
    kb_lib = None
    KB_AVAILABLE = False

try:
    import pyautogui
    PYAUTOGUI_AVAILABLE = True
except Exception:
    pyautogui = None
    PYAUTOGUI_AVAILABLE = False


class KeyboardController:
    """Types text and presses key combos on the real system."""

    def __init__(self):
        self.available = KB_AVAILABLE or PYAUTOGUI_AVAILABLE
        self.error = None if self.available else \
            "No keyboard backend — install `keyboard` or `pyautogui`"
        # Modifier latch state for the virtual keyboard (shift/ctrl/alt).
        self.modifiers = {"shift": False, "ctrl": False, "alt": False}

    # ------------------------------------------------------------------ #
    def type_text(self, text):
        """Type a string into the active window."""
        try:
            if KB_AVAILABLE:
                kb_lib.write(text)
            elif PYAUTOGUI_AVAILABLE:
                pyautogui.typewrite(text, interval=0.01, _pause=False)
        except Exception as exc:
            self.error = f"Keyboard error: {exc}"

    def press_key(self, key):
        """Press a single named key, applying any latched modifiers."""
        try:
            mods = [m for m, on in self.modifiers.items() if on]
            combo = "+".join(mods + [key]) if mods else key
            if KB_AVAILABLE:
                kb_lib.press_and_release(combo)
            elif PYAUTOGUI_AVAILABLE:
                if mods:
                    pyautogui.hotkey(*mods, key, _pause=False)
                else:
                    pyautogui.press(key, _pause=False)
            # Shift is a one-shot latch (like sticky keys); release it.
            self.modifiers["shift"] = False
        except Exception as exc:
            self.error = f"Keyboard error: {exc}"

    def hotkey(self, *keys):
        """Press a combination like ('win', 'd')."""
        try:
            if KB_AVAILABLE:
                kb_lib.press_and_release("+".join(
                    "windows" if k == "win" else k for k in keys))
            elif PYAUTOGUI_AVAILABLE:
                pyautogui.hotkey(*keys, _pause=False)
        except Exception as exc:
            self.error = f"Keyboard error: {exc}"

    def toggle_modifier(self, mod):
        """Latch/unlatch shift, ctrl or alt for the next key press."""
        if mod in self.modifiers:
            self.modifiers[mod] = not self.modifiers[mod]
        return self.modifiers.get(mod, False)
