"""
air_hud.py — AIR OS V2 mini HUD (top-left overlay).

A small, frameless, always-on-top strip in the top-left corner of the
screen. This is AIR's main way of talking to you:

    ● Listening...
    ● Opening Gmail...
    ● Which browser?  [Chrome] [Edge] [Default]
    ● Done ✓
    ● Chrome is using high memory. Close it?  [Yes] [No]

Design rules:
  - tiny and calm — never a big popup, never steals focus
  - can be hidden (— button, voice, or the pinky-up gesture)
    and restored (same gesture, or the "AIR HUD" button in the
    main window)
  - choice questions render as small tappable buttons AND can be
    answered by voice — the HUD never blocks anything.

All public methods are thread-safe: they marshal themselves onto the
Tk main thread with `after`, so the voice thread and monitor thread
can call them directly.
"""

import tkinter as tk

try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
except ImportError:
    ctk = None
    CTK_AVAILABLE = False

from settings import settings

BG = "#0b0d13"
PANEL = "#111522"
BORDER = "#2b3350"
TEXT = "#e8eaf2"
DIM = "#8b93a7"
ACCENT = "#7c3aed"
OK = "#34d399"
WARN = "#fbbf24"

IDLE_TEXT = "AIR ready"


class AirHUD:
    """Small always-on-top message strip in the top-left corner."""

    def __init__(self, root):
        self.root = root          # the main Tk root (for .after scheduling)
        self.window = None
        self.visible = False
        self._msg_label = None
        self._dot = None
        self._btn_row = None
        self._choice_cb = None    # fn(answer) for the current question
        self._clear_job = None
        if settings.air_hud_enabled:
            self._ui(self._build)
            self.visible = True

    # ------------------------------------------------------------------ #
    # Thread-safe marshalling: every public call funnels through here.
    # ------------------------------------------------------------------ #
    def _ui(self, fn, *args):
        try:
            self.root.after(0, lambda: fn(*args))
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def _build(self):
        Toplevel = ctk.CTkToplevel if CTK_AVAILABLE else tk.Toplevel
        win = Toplevel(self.root)
        win.overrideredirect(True)          # frameless
        win.geometry("+12+12")              # top-left corner
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", settings.air_hud_opacity)
        except Exception:
            pass
        if not CTK_AVAILABLE:
            win.configure(bg=BG)

        outer = (ctk.CTkFrame(win, fg_color=PANEL, corner_radius=14,
                              border_width=1, border_color=BORDER)
                 if CTK_AVAILABLE else
                 tk.Frame(win, bg=PANEL, highlightbackground=BORDER,
                          highlightthickness=1))
        outer.pack()

        top = (ctk.CTkFrame(outer, fg_color="transparent")
               if CTK_AVAILABLE else tk.Frame(top_bg := outer, bg=PANEL))
        top.pack(fill="x", padx=10, pady=(7, 2))

        # status dot ● + message
        self._dot = (ctk.CTkLabel(top, text="●", text_color=OK, width=14,
                                  font=("Segoe UI", 12))
                     if CTK_AVAILABLE else
                     tk.Label(top, text="●", fg=OK, bg=PANEL))
        self._dot.pack(side="left")
        self._msg_label = (ctk.CTkLabel(top, text=IDLE_TEXT,
                                        text_color=TEXT,
                                        font=("Segoe UI", 12),
                                        wraplength=300, justify="left")
                           if CTK_AVAILABLE else
                           tk.Label(top, text=IDLE_TEXT, fg=TEXT, bg=PANEL,
                                    font=("Segoe UI", 10),
                                    wraplength=300, justify="left"))
        self._msg_label.pack(side="left", padx=(6, 4))

        # minimize button —
        mini = (ctk.CTkButton(top, text="—", width=22, height=18,
                              fg_color="transparent", hover_color=BORDER,
                              text_color=DIM, command=self.hide)
                if CTK_AVAILABLE else
                tk.Button(top, text="—", command=self.hide, bg=PANEL,
                          fg=DIM, relief="flat", width=2))
        mini.pack(side="right")

        # row for choice buttons (hidden until a question is asked)
        self._btn_row = (ctk.CTkFrame(outer, fg_color="transparent")
                         if CTK_AVAILABLE else tk.Frame(outer, bg=PANEL))
        self._btn_row.pack(fill="x", padx=10, pady=(0, 7))

        # drag to reposition (frameless windows can't be moved otherwise)
        for w in (outer, self._msg_label):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        self.window = win

    def _drag_start(self, e):
        self._dx, self._dy = e.x, e.y

    def _drag_move(self, e):
        try:
            x = self.window.winfo_x() + e.x - self._dx
            y = self.window.winfo_y() + e.y - self._dy
            self.window.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Public API (all thread-safe)
    # ------------------------------------------------------------------ #
    def say(self, text, kind="info", hold_seconds=6):
        """Show a short message. kind: info | ok | warn | listen."""
        self._ui(self._say, text, kind, hold_seconds)

    def _say(self, text, kind, hold_seconds):
        if self.window is None:
            self._build()
        if not self.visible:
            # Important messages still update the label so they're
            # there when the HUD is restored — but we don't force-show.
            pass
        color = {"ok": OK, "warn": WARN, "listen": ACCENT}.get(kind, OK)
        try:
            if CTK_AVAILABLE:
                self._dot.configure(text_color=color)
                self._msg_label.configure(text=text)
            else:
                self._dot.configure(fg=color)
                self._msg_label.configure(text=text)
        except Exception:
            return
        # auto-return to the idle line after a while
        if self._clear_job:
            try:
                self.root.after_cancel(self._clear_job)
            except Exception:
                pass
        if hold_seconds:
            self._clear_job = self.root.after(
                int(hold_seconds * 1000), self._idle)

    def _idle(self):
        try:
            if CTK_AVAILABLE:
                self._dot.configure(text_color=OK)
                self._msg_label.configure(text=IDLE_TEXT)
            else:
                self._dot.configure(fg=OK)
                self._msg_label.configure(text=IDLE_TEXT)
        except Exception:
            pass

    def set_idle_text(self, text):
        """Change what the HUD shows when nothing is happening
        (e.g. 'AIR sleeping — say "wake up"')."""
        global IDLE_TEXT
        IDLE_TEXT = text
        self._ui(self._idle)

    # ---------------------- choice questions -------------------------- #
    def ask(self, question, options, callback):
        """
        Show a question with small buttons, e.g.
        ask("Which browser?", ["Chrome", "Edge", "Default"], fn).
        `callback(answer)` fires on click. answer_by_voice() lets the
        voice engine answer the same question. Passing None to the
        callback means the question was cancelled.
        """
        self._ui(self._ask, question, options, callback)

    def _ask(self, question, options, callback):
        if self.window is None:
            self._build()
        self._choice_cb = callback
        self._say(question, "listen", hold_seconds=0)
        self._clear_buttons()
        maker = (lambda t: ctk.CTkButton(
                    self._btn_row, text=t, height=22, corner_radius=8,
                    fg_color=ACCENT, hover_color="#6d28d9",
                    font=("Segoe UI", 11),
                    command=lambda a=t: self._answer(a))
                 ) if CTK_AVAILABLE else (
                 lambda t: tk.Button(
                    self._btn_row, text=t, bg=ACCENT, fg="white",
                    relief="flat", font=("Segoe UI", 9),
                    command=lambda a=t: self._answer(a)))
        for opt in options:
            maker(opt).pack(side="left", padx=3)

    def answer_by_voice(self, answer):
        """Voice engine resolved the current question."""
        self._ui(self._answer, answer)

    def has_question(self):
        return self._choice_cb is not None

    def _answer(self, answer):
        cb, self._choice_cb = self._choice_cb, None
        self._clear_buttons()
        self._idle()
        if cb:
            try:
                cb(answer)
            except Exception:
                pass

    def _clear_buttons(self):
        try:
            for child in self._btn_row.winfo_children():
                child.destroy()
        except Exception:
            pass

    # ---------------------- show / hide -------------------------------- #
    def hide(self):
        self._ui(self._hide)

    def _hide(self):
        if self.window is not None:
            try:
                self.window.withdraw()
            except Exception:
                pass
        self.visible = False

    def show(self):
        self._ui(self._show)

    def _show(self):
        if self.window is None:
            self._build()
        try:
            self.window.deiconify()
            self.window.attributes("-topmost", True)
        except Exception:
            pass
        self.visible = True

    def toggle(self):
        if self.visible:
            self.hide()
        else:
            self.show()
