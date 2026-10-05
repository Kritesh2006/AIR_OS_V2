"""AIR OS compact top-left camera/status Pod.

The Pod is intentionally small and persistent: a live 4:3 preview plus one
status line and AIR's existing short message / choice UI. It keeps the old
AirHUD public API so voice and monitor features do not need to be redesigned.

Tk owns this object. Under the Phase 1 architecture all calls arrive on Tk's
main thread via EventQueue; this module never schedules Tk work from workers.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any

try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
except ImportError:
    ctk = None
    CTK_AVAILABLE = False

try:
    from PIL import Image, ImageTk
    PIL_AVAILABLE = True
except ImportError:
    Image = ImageTk = None
    PIL_AVAILABLE = False

from settings import settings

try:
    from win_windows import make_window_noactivate
except ImportError:
    def make_window_noactivate(hwnd):
        return False

BG = "#0b0d13"
PANEL = "#111522"
BORDER = "#2b3350"
TEXT = "#e8eaf2"
DIM = "#8b93a7"
ACCENT = "#7c3aed"
OK = "#34d399"
WARN = "#fbbf24"
BAD = "#f87171"


class AirPod:
    """Small always-on-top AIR camera Pod. Tk-main-thread owned."""

    def __init__(self, root, scale: float = 1.0):
        self.root = root
        self.scale = max(0.75, min(float(scale or 1.0), 3.0))
        self.window = None
        self.visible = False

        self._preview_photo = None
        self._preview_label = None
        self._status_dot = None
        self._status_label = None
        self._msg_label = None
        self._btn_row = None
        self._choice_cb = None
        self._clear_job = None
        self._idle_text = "AIR ready"

        # Physical-pixel target used by SensorWorker when it publishes the
        # tiny immutable preview_rgb snapshot.
        self._preview_w = self._px(176)
        self._preview_h = self._px(132)

        if settings.air_hud_enabled:
            self._build()
            self.visible = True

    def _px(self, n: int) -> int:
        return max(1, int(round(n * self.scale)))

    def _font(self, size: int, bold: bool = False):
        return ("Segoe UI", max(8, int(round(size * self.scale))),
                "bold" if bold else "normal")

    @property
    def preview_visible(self) -> bool:
        """Whether SensorWorker should spend CPU producing preview_rgb."""
        return bool(self.visible and settings.show_preview)

    @property
    def preview_size(self) -> tuple[int, int]:
        """Requested worker preview size in physical pixels."""
        return self._preview_w, self._preview_h

    # ------------------------------------------------------------------ #
    def _build(self):
        if self.window is not None:
            return

        Toplevel = ctk.CTkToplevel if CTK_AVAILABLE else tk.Toplevel
        win = Toplevel(self.root)
        win.overrideredirect(True)
        margin = self._px(12)
        win.geometry(f"+{margin}+{margin}")
        win.attributes("-topmost", True)
        try:
            win.attributes("-alpha", settings.air_hud_opacity)
        except Exception:
            pass
        try:
            win.configure(takefocus=False)
        except Exception:
            pass
        if not CTK_AVAILABLE:
            win.configure(bg=BG)

        outer = (ctk.CTkFrame(
                    win, fg_color=PANEL, corner_radius=self._px(14),
                    border_width=1, border_color=BORDER)
                 if CTK_AVAILABLE else
                 tk.Frame(win, bg=PANEL, highlightbackground=BORDER,
                          highlightthickness=1))
        outer.pack()

        host = tk.Frame(outer, width=self._preview_w,
                        height=self._preview_h, bg="#05060a",
                        bd=0, highlightthickness=0)
        host.pack(padx=self._px(8), pady=(self._px(8), self._px(5)))
        host.pack_propagate(False)
        self._preview_label = tk.Label(
            host, text="Starting camera…", bg="#05060a", fg=DIM,
            bd=0, font=self._font(9))
        self._preview_label.pack(fill="both", expand=True)

        top = (ctk.CTkFrame(outer, fg_color="transparent")
               if CTK_AVAILABLE else tk.Frame(outer, bg=PANEL))
        top.pack(fill="x", padx=self._px(8), pady=(0, self._px(3)))

        self._status_dot = (ctk.CTkLabel(
                                top, text="●", text_color=OK,
                                width=self._px(13), font=self._font(10))
                            if CTK_AVAILABLE else
                            tk.Label(top, text="●", fg=OK, bg=PANEL,
                                     font=self._font(10)))
        self._status_dot.pack(side="left")

        self._status_label = (ctk.CTkLabel(
                                  top, text="AIR • READY", text_color=TEXT,
                                  font=self._font(10, True))
                              if CTK_AVAILABLE else
                              tk.Label(top, text="AIR • READY", fg=TEXT,
                                       bg=PANEL, font=self._font(9, True)))
        self._status_label.pack(side="left", padx=(self._px(4), self._px(4)))

        mini = (ctk.CTkButton(
                    top, text="—", width=self._px(22), height=self._px(18),
                    fg_color="transparent", hover_color=BORDER,
                    text_color=DIM, command=self.hide)
                if CTK_AVAILABLE else
                tk.Button(top, text="—", command=self.hide, bg=PANEL,
                          fg=DIM, relief="flat", width=2,
                          font=self._font(8)))
        mini.pack(side="right")

        self._msg_label = (ctk.CTkLabel(
                               outer, text=self._idle_text, text_color=DIM,
                               font=self._font(9), wraplength=self._px(190),
                               justify="left")
                           if CTK_AVAILABLE else
                           tk.Label(outer, text=self._idle_text, fg=DIM,
                                    bg=PANEL, font=self._font(8),
                                    wraplength=self._px(190), justify="left"))
        self._msg_label.pack(fill="x", padx=self._px(10),
                             pady=(0, self._px(4)))

        self._btn_row = (ctk.CTkFrame(outer, fg_color="transparent")
                         if CTK_AVAILABLE else tk.Frame(outer, bg=PANEL))
        self._btn_row.pack(fill="x", padx=self._px(8),
                           pady=(0, self._px(7)))

        for widget in (outer, self._status_label, self._msg_label):
            widget.bind("<Button-1>", self._drag_start)
            widget.bind("<B1-Motion>", self._drag_move)

        self.window = win
        try:
            win.update_idletasks()
            make_window_noactivate(int(win.winfo_id()))
        except Exception:
            pass

    def _drag_start(self, event):
        self._dx, self._dy = event.x, event.y

    def _drag_move(self, event):
        try:
            x = self.window.winfo_x() + event.x - self._dx
            y = self.window.winfo_y() + event.y - self._dy
            self.window.geometry(f"+{x}+{y}")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Phase 1 snapshot rendering
    # ------------------------------------------------------------------ #
    def render(self, snap: Any) -> None:
        """Render the newest UiSnapshot (Tk thread only)."""
        if snap is None:
            return
        if self.window is None:
            self._build()

        if self.preview_visible:
            frame = getattr(snap, "preview_rgb", None)
            if frame is not None:
                self._render_preview(frame)

        interaction = getattr(snap, "interaction", None)
        if interaction is not None:
            raw = getattr(interaction, "pod_status", None)
            status = getattr(raw, "value", raw)
            if status:
                self._render_status(str(status))

    def _render_preview(self, frame_rgb) -> None:
        if not PIL_AVAILABLE or self._preview_label is None:
            return
        try:
            img = Image.fromarray(frame_rgb)
            if img.mode != "RGB":
                img = img.convert("RGB")
            if img.size != self.preview_size:
                resampling = getattr(Image, "Resampling", Image)
                img = img.resize(self.preview_size, resampling.BILINEAR)
            self._preview_photo = ImageTk.PhotoImage(img)
            self._preview_label.configure(image=self._preview_photo, text="")
        except Exception:
            pass

    def _render_status(self, status: str) -> None:
        label = status.strip() or "READY"
        color = {
            "READY": OK,
            "PAUSED": WARN,
            "CLOSE?": WARN,
            "SELECT": ACCENT,
            "BLINK": ACCENT,
            "CLOSING…": WARN,
            "CLOSING...": WARN,
            "CLOSED": OK,
            "STILL OPEN": BAD,
            "CANCELLED": DIM,
        }.get(label.upper(), OK)
        try:
            if CTK_AVAILABLE:
                self._status_dot.configure(text_color=color)
                self._status_label.configure(text=f"AIR • {label}")
            else:
                self._status_dot.configure(fg=color)
                self._status_label.configure(text=f"AIR • {label}")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # AirHUD-compatible communication API
    # ------------------------------------------------------------------ #
    def say(self, text, kind="info", hold_seconds=6):
        if self.window is None:
            self._build()
        color = {"ok": OK, "warn": WARN, "listen": ACCENT}.get(kind, OK)
        try:
            if CTK_AVAILABLE:
                self._status_dot.configure(text_color=color)
                self._msg_label.configure(text=text, text_color=TEXT)
            else:
                self._status_dot.configure(fg=color)
                self._msg_label.configure(text=text, fg=TEXT)
        except Exception:
            return
        if self._clear_job:
            try:
                self.root.after_cancel(self._clear_job)
            except Exception:
                pass
        if hold_seconds:
            self._clear_job = self.root.after(
                int(float(hold_seconds) * 1000), self._idle)

    def _idle(self):
        self._clear_job = None
        try:
            if CTK_AVAILABLE:
                self._msg_label.configure(text=self._idle_text,
                                          text_color=DIM)
            else:
                self._msg_label.configure(text=self._idle_text, fg=DIM)
        except Exception:
            pass

    def set_idle_text(self, text):
        self._idle_text = str(text)
        self._idle()

    def ask(self, question, options, callback):
        if self.window is None:
            self._build()
        self._choice_cb = callback
        self.say(question, "listen", hold_seconds=0)
        self._clear_buttons()

        if CTK_AVAILABLE:
            def maker(label):
                return ctk.CTkButton(
                    self._btn_row, text=label, height=self._px(22),
                    corner_radius=self._px(8), fg_color=ACCENT,
                    hover_color="#6d28d9", font=self._font(9),
                    command=lambda a=label: self._answer(a))
        else:
            def maker(label):
                return tk.Button(
                    self._btn_row, text=label, bg=ACCENT, fg="white",
                    relief="flat", font=self._font(8),
                    command=lambda a=label: self._answer(a))

        for option in options:
            maker(option).pack(side="left", padx=self._px(2))

    def answer_by_voice(self, answer):
        self._answer(answer)

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
        if self._btn_row is None:
            return
        try:
            for child in self._btn_row.winfo_children():
                child.destroy()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def hide(self):
        if self.window is not None:
            try:
                self.window.withdraw()
            except Exception:
                pass
        self.visible = False

    def show(self):
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


# Compatibility name for code that still imports the old class name while
# Claude integrates main.py. New code should import AirPod explicitly.
AirHUD = AirPod
