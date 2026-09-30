"""
virtual_keyboard.py — Floating on-screen keyboard for AIR OS V01.

A dark, modern, resizable, always-on-top window. Two ways to type:
  1. Hover a key with the gesture-driven cursor and PINCH-TAP
     (pinch + middle-finger tap = left click) — the click lands on
     the key under the cursor.
  2. Ordinary mouse clicks work too.

On Windows the window is created with WS_EX_NOACTIVATE so clicking
keys does NOT steal focus from the app you're typing into.
"""

import ctypes
import sys
import tkinter as tk

try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
except ImportError:
    ctk = None
    CTK_AVAILABLE = False

IS_WINDOWS = sys.platform == "win32"

# Keyboard layout rows: (label, key_name, width_units)
LAYOUT = [
    [("1", "1", 1), ("2", "2", 1), ("3", "3", 1), ("4", "4", 1), ("5", "5", 1),
     ("6", "6", 1), ("7", "7", 1), ("8", "8", 1), ("9", "9", 1), ("0", "0", 1),
     ("⌫", "backspace", 2)],
    [("q", "q", 1), ("w", "w", 1), ("e", "e", 1), ("r", "r", 1), ("t", "t", 1),
     ("y", "y", 1), ("u", "u", 1), ("i", "i", 1), ("o", "o", 1), ("p", "p", 1)],
    [("a", "a", 1), ("s", "s", 1), ("d", "d", 1), ("f", "f", 1), ("g", "g", 1),
     ("h", "h", 1), ("j", "j", 1), ("k", "k", 1), ("l", "l", 1),
     ("↵ Enter", "enter", 2)],
    [("⇧ Shift", "shift", 2), ("z", "z", 1), ("x", "x", 1), ("c", "c", 1),
     ("v", "v", 1), ("b", "b", 1), ("n", "n", 1), ("m", "m", 1),
     (",", ",", 1), (".", ".", 1)],
    [("Ctrl", "ctrl", 2), ("Alt", "alt", 2), ("Space", "space", 6),
     ("✕ Close", "__close__", 2)],
]

MODIFIERS = ("shift", "ctrl", "alt")


class VirtualKeyboard:
    """Floating gesture-typeable keyboard window."""

    def __init__(self, parent, keyboard_controller):
        self.kb = keyboard_controller
        self.parent = parent
        self.window = None
        self._mod_buttons = {}
        self.visible = False

    # ------------------------------------------------------------------ #
    def toggle(self):
        if self.visible:
            self.hide()
        else:
            self.show()

    def show(self):
        if self.window is not None:
            try:
                self.window.deiconify()
                self.visible = True
                return
            except Exception:
                self.window = None
        self._build()
        self.visible = True

    def hide(self):
        if self.window is not None:
            try:
                self.window.withdraw()
            except Exception:
                pass
        self.visible = False

    # ------------------------------------------------------------------ #
    def _build(self):
        Toplevel = ctk.CTkToplevel if CTK_AVAILABLE else tk.Toplevel
        win = Toplevel(self.parent)
        win.title("AIR OS Keyboard")
        win.geometry("760x300+240+560")
        win.minsize(480, 200)
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", 0.94)
        except Exception:
            pass
        if not CTK_AVAILABLE:
            win.configure(bg="#0f1117")
        win.protocol("WM_DELETE_WINDOW", self.hide)

        # Keep grid responsive => keyboard is resizable.
        for r in range(len(LAYOUT)):
            win.grid_rowconfigure(r, weight=1)
        max_units = max(sum(w for _, _, w in row) for row in LAYOUT)
        for c in range(max_units):
            win.grid_columnconfigure(c, weight=1)

        for r, row in enumerate(LAYOUT):
            col = 0
            for label, key, width in row:
                btn = self._make_button(win, label, key)
                btn.grid(row=r, column=col, columnspan=width,
                         sticky="nsew", padx=3, pady=3)
                if key in MODIFIERS:
                    self._mod_buttons[key] = btn
                col += width

        self.window = win
        self._apply_noactivate()

    def _make_button(self, win, label, key):
        cmd = lambda k=key: self._press(k)
        if CTK_AVAILABLE:
            return ctk.CTkButton(
                win, text=label, command=cmd,
                fg_color="#1b1f2a", hover_color="#2e3650",
                border_width=1, border_color="#333a4d",
                corner_radius=10, font=("Segoe UI", 15),
                text_color="#e8eaf2")
        return tk.Button(win, text=label, command=cmd,
                         bg="#1b1f2a", fg="#e8eaf2",
                         activebackground="#2e3650", relief="flat",
                         font=("Segoe UI", 12))

    def _apply_noactivate(self):
        """Windows-only: stop the keyboard stealing focus on click."""
        if not IS_WINDOWS or self.window is None:
            return
        try:
            self.window.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.window.winfo_id())
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE)
        except Exception:
            pass  # cosmetic only — typing still works via `keyboard` lib

    # ------------------------------------------------------------------ #
    def _press(self, key):
        if key == "__close__":
            self.hide()
            return
        if key in MODIFIERS:
            latched = self.kb.toggle_modifier(key)
            self._style_modifier(key, latched)
            return
        if key == "space":
            self.kb.press_key("space")
        elif key == "enter":
            self.kb.press_key("enter")
        elif key == "backspace":
            self.kb.press_key("backspace")
        else:
            # Letters / numbers / punctuation. Shift latch handles caps.
            self.kb.press_key(key)
        # Reflect one-shot shift release in the UI.
        if not self.kb.modifiers.get("shift"):
            self._style_modifier("shift", False)

    def _style_modifier(self, key, latched):
        btn = self._mod_buttons.get(key)
        if btn is None:
            return
        try:
            if CTK_AVAILABLE:
                btn.configure(fg_color="#7c3aed" if latched else "#1b1f2a")
            else:
                btn.configure(bg="#7c3aed" if latched else "#1b1f2a")
        except Exception:
            pass
