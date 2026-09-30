"""
hud.py — Main window and floating HUD for AIR OS V01.

Layout:
  ┌──────────────────────────────────────────────┐
  │ [Live camera preview, top-left]  │  STATUS   │
  │  (hand landmarks drawn on it)    │  Camera   │
  │                                  │  Mic      │
  │  [Hide/Show Preview]             │  Gesture  │
  │                                  │  Voice    │
  │                                  │  FPS      │
  │                                  │  Gesture  │
  │                                  │  Action   │
  │  Errors bar (readable, wraps)               │
  └──────────────────────────────────────────────┘

Also owns the dangerous-action confirmation overlay
(voice "shutdown" etc. → Confirm / Cancel; a quick FIST also cancels).
"""

import tkinter as tk

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

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    CV2_AVAILABLE = False

from settings import settings

# Palette — near-black glass with violet accent.
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
    """Main application window + status HUD + confirmation overlay."""

    def __init__(self):
        if CTK_AVAILABLE:
            ctk.set_appearance_mode("dark")
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()
            self.root.configure(bg=BG)
        self.root.title("AIR OS V01")
        self.root.geometry("880x560+60+60")
        self.root.minsize(720, 480)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-alpha", settings.hud_opacity)
        except Exception:
            pass

        self._preview_visible = settings.show_preview
        self._preview_photo = None  # keep reference or Tk garbage-collects it
        self._status_labels = {}
        self._overlay = None
        self._overlay_action = None
        self.on_close = None  # set by main.py

        self._build_layout()
        self.root.protocol("WM_DELETE_WINDOW", self._handle_close)

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

    # ------------------------------------------------------------------ #
    def _build_layout(self):
        root = self.root
        root.grid_columnconfigure(0, weight=3)
        root.grid_columnconfigure(1, weight=2)
        root.grid_rowconfigure(0, weight=1)

        # ---- Left: camera preview (top-left of the window) ------------
        left = self._frame(root)
        left.grid(row=0, column=0, sticky="nsew", padx=(14, 7), pady=(14, 7))
        left.grid_rowconfigure(1, weight=1)
        left.grid_columnconfigure(0, weight=1)

        self._label(left, "  LIVE PREVIEW", size=12, color=DIM,
                    bold=True).grid(row=0, column=0, sticky="w",
                                    padx=10, pady=(10, 4))
        # Plain tk.Label is the fastest way to blit video frames.
        self.preview_label = tk.Label(left, bg="#05060a",
                                      text="Starting camera…", fg=DIM,
                                      font=("Segoe UI", 12))
        self.preview_label.grid(row=1, column=0, sticky="nsew",
                                padx=10, pady=4)
        self.preview_btn = self._button(left, "Hide preview",
                                        self.toggle_preview)
        self.preview_btn.grid(row=2, column=0, sticky="w",
                              padx=10, pady=(4, 10))
        # V2: restore the mini HUD if it was hidden (gesture also works).
        self.on_show_air_hud = None
        air_btn = self._button(left, "AIR HUD",
                               lambda: self.on_show_air_hud and
                               self.on_show_air_hud())
        air_btn.grid(row=2, column=0, sticky="e", padx=10, pady=(4, 10))

        # ---- Right: floating status HUD --------------------------------
        right = self._frame(root)
        right.grid(row=0, column=1, sticky="nsew", padx=(7, 14), pady=(14, 7))
        right.grid_columnconfigure(1, weight=1)

        self._label(right, "  AIR OS V01", size=16, color=TEXT, bold=True)\
            .grid(row=0, column=0, columnspan=2, sticky="w",
                  padx=10, pady=(12, 2))
        self._label(right, "  gesture + voice control layer", size=11,
                    color=DIM).grid(row=1, column=0, columnspan=2,
                                    sticky="w", padx=10, pady=(0, 10))

        rows = [("camera", "Camera"), ("mic", "Microphone"),
                ("gesture", "Gestures"), ("voice", "Voice"),
                ("fps", "FPS"), ("cur_gesture", "Current gesture"),
                ("action", "Last action"), ("heard", "Heard")]
        for i, (key, title) in enumerate(rows, start=2):
            self._label(right, f"{title}", size=12, color=DIM)\
                .grid(row=i, column=0, sticky="w", padx=(14, 6), pady=3)
            val = self._label(right, "—", size=12, color=TEXT, bold=True)
            val.grid(row=i, column=1, sticky="w", padx=6, pady=3)
            self._status_labels[key] = val

        # ---- Bottom: error bar ------------------------------------------
        errbar = self._frame(root)
        errbar.grid(row=1, column=0, columnspan=2, sticky="ew",
                    padx=14, pady=(7, 14))
        errbar.grid_columnconfigure(0, weight=1)
        self.error_label = self._label(errbar, "No errors.", size=11,
                                       color=DIM)
        self.error_label.grid(row=0, column=0, sticky="w", padx=12, pady=8)

    # ------------------------------------------------------------------ #
    # Status updates — all safe to call from the main (Tk) thread only.
    # main.py marshals background-thread updates via root.after().
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
        """Show an error in the bottom bar. Errors accumulate (last 3
        are shown) so a new minor error never hides an older one."""
        try:
            if text:
                if not hasattr(self, "_errors"):
                    self._errors = []
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

    def update_preview(self, frame_bgr):
        """Blit a BGR frame into the preview label (main thread only)."""
        if not self._preview_visible or frame_bgr is None:
            return
        if not (PIL_AVAILABLE and CV2_AVAILABLE):
            return
        try:
            w = max(self.preview_label.winfo_width(), 160)
            h = max(self.preview_label.winfo_height(), 120)
            fh, fw = frame_bgr.shape[:2]
            scale = min(w / fw, h / fh)
            frame = cv2.resize(frame_bgr, (int(fw * scale), int(fh * scale)))
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            img = Image.fromarray(rgb)
            self._preview_photo = ImageTk.PhotoImage(img)
            self.preview_label.configure(image=self._preview_photo, text="")
        except Exception:
            pass  # a bad frame must never crash the UI

    def toggle_preview(self):
        self._preview_visible = not self._preview_visible
        settings.set("show_preview", self._preview_visible)
        settings.save()
        if self._preview_visible:
            self.preview_btn.configure(text="Hide preview")
        else:
            self.preview_btn.configure(text="Show preview")
            self.preview_label.configure(image="", text="Preview hidden")
            self._preview_photo = None

    # ------------------------------------------------------------------ #
    # Confirmation overlay for dangerous actions.
    # ------------------------------------------------------------------ #
    def show_confirmation(self, label, action_fn):
        """Ask the user to confirm a dangerous action (shutdown etc.)."""
        self.close_overlay()  # only one at a time
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
        self._button(row, "Confirm", self._confirm_overlay)\
            .grid(row=0, column=0, padx=8)
        cancel = self._button(row, "Cancel", self.close_overlay)
        try:
            cancel.configure(fg_color="#374151", hover_color="#4b5563") \
                if CTK_AVAILABLE else cancel.configure(bg="#374151")
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
        """Dismiss the confirmation dialog (also triggered by FIST)."""
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
        if self.on_close:
            self.on_close()
        try:
            self.root.destroy()
        except Exception:
            pass

    def run(self):
        self.root.mainloop()
