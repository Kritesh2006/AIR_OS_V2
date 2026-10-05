"""AIR OS Control Panel.

Phase 1 separates the Tk application root from the visible Control Panel so
minimizing the panel never hides the always-on-top AirPod.  The panel remains
a normal taskbar window; X requests application shutdown through ``on_close``
and this class never destroys Tk by itself.
"""

from __future__ import annotations

import tkinter as tk

try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
except ImportError:
    ctk = None
    CTK_AVAILABLE = False

from settings import settings

BG = "#0b0d13"
PANEL = "#12151f"
BORDER = "#262c3d"
TEXT = "#e8eaf2"
DIM = "#8b93a7"
ACCENT = "#7c3aed"
OK = "#34d399"
BAD = "#f87171"
WARN = "#fbbf24"


class HUD:
    """Visible Control Panel plus legacy dangerous-action confirmation."""

    def __init__(self):
        if CTK_AVAILABLE:
            ctk.set_appearance_mode("dark")
            self.root = ctk.CTk()
            self.root.withdraw()
            self.panel = ctk.CTkToplevel(self.root)
        else:
            self.root = tk.Tk()
            self.root.withdraw()
            self.panel = tk.Toplevel(self.root)
            self.panel.configure(bg=BG)

        self.panel.title("AIR OS V2")
        self.panel.geometry("760x500+60+60")
        self.panel.minsize(660, 430)
        # Deliberately NOT topmost: this is a normal minimizable panel.
        try:
            self.panel.attributes("-alpha", settings.hud_opacity)
        except Exception:
            pass

        self._preview_visible = bool(settings.show_preview)
        self._status_labels = {}
        self._errors = []
        self._overlay = None
        self._overlay_action = None
        self.on_close = None
        self.on_show_air_hud = None

        self._build_layout()
        self.panel.protocol("WM_DELETE_WINDOW", self._handle_close)
        try:
            self.panel.deiconify()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    def _frame(self, parent, **kw):
        if CTK_AVAILABLE:
            return ctk.CTkFrame(parent, fg_color=PANEL, corner_radius=14,
                                border_width=1, border_color=BORDER, **kw)
        return tk.Frame(parent, bg=PANEL, highlightbackground=BORDER,
                        highlightthickness=1, **kw)

    def _label(self, parent, text, size=13, color=TEXT, bold=False):
        font = ("Segoe UI", size, "bold" if bold else "normal")
        if CTK_AVAILABLE:
            return ctk.CTkLabel(parent, text=text, font=font,
                                text_color=color)
        return tk.Label(parent, text=text, font=font, fg=color, bg=PANEL)

    def _button(self, parent, text, command):
        if CTK_AVAILABLE:
            return ctk.CTkButton(parent, text=text, command=command,
                                 fg_color=ACCENT, hover_color="#6d28d9",
                                 corner_radius=10, font=("Segoe UI", 13))
        return tk.Button(parent, text=text, command=command, bg=ACCENT,
                         fg="white", relief="flat", font=("Segoe UI", 11))

    def _build_layout(self):
        panel = self.panel
        panel.grid_columnconfigure(0, weight=2)
        panel.grid_columnconfigure(1, weight=3)
        panel.grid_rowconfigure(0, weight=1)

        # Left: Pod controls. The large V1 camera view moved to AirPod.
        left = self._frame(panel)
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=(14, 7))
        left.grid_columnconfigure(0, weight=1)

        self._label(left, "AIR POD", size=15, color=TEXT, bold=True).grid(
            row=0, column=0, sticky="w", padx=14, pady=(16, 6))
        self._label(
            left,
            "Live camera + AIR status now stay in the small top-left Pod.\n"
            "You can minimize this Control Panel and AIR keeps running.",
            size=11, color=DIM).grid(row=1, column=0, sticky="nw",
                                     padx=14, pady=(0, 14))

        self.preview_btn = self._button(
            left, "Hide Pod preview" if self._preview_visible
            else "Show Pod preview", self.toggle_preview)
        self.preview_btn.grid(row=2, column=0, sticky="ew", padx=14, pady=5)

        pod_btn = self._button(
            left, "Show AIR Pod",
            lambda: self.on_show_air_hud and self.on_show_air_hud())
        pod_btn.grid(row=3, column=0, sticky="ew", padx=14, pady=5)

        self._label(left, "Tip: minimizing this window does not pause gestures.",
                    size=10, color=DIM).grid(row=4, column=0, sticky="sw",
                                             padx=14, pady=(18, 12))

        # Right: existing status dashboard.
        right = self._frame(panel)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=(14, 7))
        right.grid_columnconfigure(1, weight=1)

        self._label(right, "AIR OS V2", size=16, color=TEXT, bold=True).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12,
            pady=(14, 2))
        self._label(right, "gesture + voice control layer", size=11,
                    color=DIM).grid(row=1, column=0, columnspan=2,
                                    sticky="w", padx=12, pady=(0, 10))

        rows = [("camera", "Camera"), ("mic", "Microphone"),
                ("gesture", "Gestures"), ("voice", "Voice"),
                ("fps", "FPS"), ("cur_gesture", "Current gesture"),
                ("action", "Last action"), ("heard", "Heard")]
        for i, (key, title) in enumerate(rows, start=2):
            self._label(right, title, size=12, color=DIM).grid(
                row=i, column=0, sticky="w", padx=(14, 6), pady=3)
            val = self._label(right, "—", size=12, color=TEXT, bold=True)
            val.grid(row=i, column=1, sticky="w", padx=6, pady=3)
            self._status_labels[key] = val

        errbar = self._frame(panel)
        errbar.grid(row=1, column=0, columnspan=2, sticky="ew",
                    padx=14, pady=(7, 14))
        errbar.grid_columnconfigure(0, weight=1)
        self.error_label = self._label(errbar, "No errors.", size=11, color=DIM)
        self.error_label.grid(row=0, column=0, sticky="w", padx=12, pady=8)

    # ------------------------------------------------------------------ #
    def set_status(self, key, text, good=None):
        lbl = self._status_labels.get(key)
        if lbl is None:
            return
        color = TEXT if good is None else (OK if good else BAD)
        try:
            if CTK_AVAILABLE:
                lbl.configure(text=text, text_color=color)
            else:
                lbl.configure(text=text, fg=color)
        except Exception:
            pass

    def set_error(self, text):
        try:
            if text:
                if text not in self._errors:
                    self._errors.append(text)
                    self._errors = self._errors[-3:]
                msg = "  |  ".join(self._errors)
                if getattr(self, "limited_mode", False):
                    msg = "LIMITED MODE — " + msg
                color = WARN
            else:
                self._errors = []
                msg, color = "No errors.", DIM
            if CTK_AVAILABLE:
                self.error_label.configure(text=msg, text_color=color)
            else:
                self.error_label.configure(text=msg, fg=color)
        except Exception:
            pass

    # Kept as a compatibility no-op while main.py moves preview rendering to
    # AirPod. New Phase 1 integration must call AirPod.render(snapshot).
    def update_preview(self, frame_bgr):
        return None

    def toggle_preview(self):
        self._preview_visible = not self._preview_visible
        settings.set("show_preview", self._preview_visible)
        settings.save()
        try:
            self.preview_btn.configure(
                text="Hide Pod preview" if self._preview_visible
                else "Show Pod preview")
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Legacy confirmation popup for voice/system actions.
    # ------------------------------------------------------------------ #
    def show_confirmation(self, label, action_fn):
        self.close_overlay()
        self._overlay_action = action_fn

        Toplevel = ctk.CTkToplevel if CTK_AVAILABLE else tk.Toplevel
        ov = Toplevel(self.root)
        ov.title("Confirm")
        ov.attributes("-topmost", True)
        ov.geometry("380x170+300+300")
        ov.resizable(False, False)
        if not CTK_AVAILABLE:
            ov.configure(bg=PANEL)

        self._label(ov, "⚠ Confirmation required", size=14, color=WARN,
                    bold=True).pack(pady=(18, 4))
        self._label(ov, label, size=13, color=TEXT).pack(pady=(0, 6))
        self._label(ov, "(make a quick FIST to cancel)", size=10,
                    color=DIM).pack()

        row = self._frame(ov)
        row.pack(pady=12)
        self._button(row, "Confirm", self._confirm_overlay).grid(
            row=0, column=0, padx=8)
        cancel = self._button(row, "Cancel", self.close_overlay)
        try:
            if CTK_AVAILABLE:
                cancel.configure(fg_color="#374151", hover_color="#4b5563")
            else:
                cancel.configure(bg="#374151")
        except Exception:
            pass
        cancel.grid(row=0, column=1, padx=8)

        ov.protocol("WM_DELETE_WINDOW", self.close_overlay)
        self._overlay = ov

    def _confirm_overlay(self):
        fn = self._overlay_action
        self.close_overlay()
        if fn:
            try:
                fn()
            except Exception as exc:
                self.set_error(f"Action failed: {exc}")

    def close_overlay(self):
        if self._overlay is not None:
            try:
                self._overlay.destroy()
            except Exception:
                pass
        self._overlay = None
        self._overlay_action = None

    @property
    def overlay_open(self):
        return self._overlay is not None

    # ------------------------------------------------------------------ #
    def _handle_close(self):
        """Request shutdown. AirOS owns final destruction of root/windows."""
        if self.on_close:
            self.on_close()

    def run(self):
        self.root.mainloop()
