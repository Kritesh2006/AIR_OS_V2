"""
main.py — AIR OS V01 entry point.

Boot order (all automatic, no Start button):
  1. Windows process setup (DPI), then build the HUD window.
  2. Start the camera thread          → limited mode if it fails
  3. Detect + start the microphone    → limited mode if it fails
  4. Start the SensorWorker thread    → hand tracking + gestures
  5. Start the always-on voice loop
  6. Enter the UI loop; every ~16 ms the Tk thread drains UI events
     and renders the newest worker snapshot.

Threading (see docs/ARCHITECTURE.md): only the Tk main thread touches
widgets. Other threads talk to it through EventQueue / LatestState and
to the SensorWorker through CommandQueue.

Everything hardware-related is wrapped so a missing camera or mic
shows a readable error in the HUD instead of crashing.

Run with:  python main.py
"""

import sys
import threading
import time
import traceback

from settings import settings
from channels import (CommandKind, CommandQueue, EventKind, EventQueue,
                      LatestState)
from sensor_worker import PassthroughRouter, SensorWorker

from camera import CameraManager
from microphone import MicrophoneManager
from hand_tracker import HandTracker
from gesture_engine import GestureEngine
from voice_engine import VoiceEngine
from mouse_controller import MouseController
from keyboard_controller import KeyboardController
from system_controller import SystemController
from virtual_keyboard import VirtualKeyboard
from hud import HUD
from air_hud import AirHUD
from system_monitor import SystemMonitor

try:
    import cv2
except ImportError:
    cv2 = None

try:
    from win_windows import configure_windows_process
except ImportError:
    def configure_windows_process():
        return 1.0

POLL_MS = 16            # Tk-side poll of events + newest snapshot
SHUTDOWN_DEADLINE_S = 3.0


class AirOS:
    """Wires every subsystem together and runs the main loop."""

    def __init__(self):
        # ---- Thread channels (see channels.py) -------------------------
        self.state = LatestState()
        self.events = EventQueue()
        self.commands = CommandQueue()

        # ---- Windows process setup BEFORE any Tk object exists ---------
        try:
            self.ui_scale = configure_windows_process()
        except Exception:
            traceback.print_exc()
            self.ui_scale = 1.0

        # ---- UI first, so every error has somewhere to be shown -------
        self.hud = HUD()
        self.hud.on_close = self._request_shutdown
        # X on the Control Panel = quit, but without blocking Tk while
        # the worker stops (see _request_shutdown).
        panel = getattr(self.hud, "panel", self.hud.root)
        panel.protocol("WM_DELETE_WINDOW", self._request_shutdown)
        # V2: the small always-on-top communication HUD (top-left).
        self.air_hud = AirHUD(self.hud.root)
        self.hud.on_show_air_hud = self.air_hud.show

        # ---- Controllers ----------------------------------------------
        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        self.system = SystemController(self.keyboard)
        self.vkeyboard = VirtualKeyboard(self.hud.root, self.keyboard)

        # ---- Sensors ----------------------------------------------------
        self.camera = CameraManager()
        self.mic = MicrophoneManager()
        self.tracker = HandTracker()

        # ---- Engines ----------------------------------------------------
        # The gesture engine runs on the SensorWorker thread, so every
        # UI-facing callback goes through _ui(). The current gesture
        # label travels in the worker snapshot instead of a callback.
        self.gestures = GestureEngine(
            self.mouse, self.keyboard, self.system,
            callbacks={
                "on_action": lambda a: self._ui(
                    lambda: self.hud.set_status("action", a)),
                "toggle_keyboard": lambda: self._ui(self.vkeyboard.toggle),
                "close_overlay": lambda: self._ui(self.hud.close_overlay),
                "set_paused": lambda p: self._ui(
                    lambda: self.hud.set_status(
                        "gesture", "PAUSED" if p else "ON", good=not p)),
                # V2: pinky-up gesture hides/restores the mini HUD.
                "toggle_air_hud": lambda: self._ui(self.air_hud.toggle),
            })

        self.voice = VoiceEngine(
            self.system,
            callbacks={
                "on_heard": lambda t: self._ui(
                    lambda: self.hud.set_status("heard", f'"{t}"')),
                "on_action": lambda a: self._ui(
                    lambda: self.hud.set_status("action", a)),
                "on_speak": lambda t: self._ui(
                    lambda: self.hud.set_error(t)),
                "request_confirmation": lambda label, fn: self._ui(
                    lambda: self.hud.show_confirmation(label, fn)),
                # ---------------- V2 wiring -----------------------------
                "on_hud": lambda t, k="info", h=6: self._say(t, k, h),
                "ask_choice": lambda q, opts, cb: self._ui(
                    lambda: self.air_hud.ask(q, opts, cb)),
                "on_question_answered": self._on_question_answered,
                "set_hands_free": self._set_hands_free,
                "explain_system": lambda: self.monitor.explain(),
            })

        # V2: background CPU/RAM/battery monitor -> calm HUD questions.
        self.monitor = SystemMonitor(callbacks={
            "on_alert": self._on_monitor_alert,
        })

        self.router = PassthroughRouter(self.gestures, self.events)
        self.worker = None
        self._running = True
        self._last_snap_seq = None
        self._shown = {}            # last text for fps / cur_gesture
        self._voice_off_shown = False
        self._preview_on = None     # last value sent to the worker
        self._popup_open = None     # last value sent to the worker
        self._worker_stopped = False
        self._stopper = None        # thread stopping voice + monitor
        self._shutdown_deadline = None

    # ------------------------------------------------------------------ #
    def _ui(self, fn):
        """Run a callable on the Tk main thread. Safe from any thread.
        Legacy bridge only (EventKind.UI_CALL) — new features should
        use explicit UiEvents."""
        self.events.emit(EventKind.UI_CALL, fn=fn)

    def _say(self, text, kind="info", hold_seconds=6):
        """Thread-safe AIR HUD message."""
        self._ui(lambda: self.air_hud.say(text, kind, hold_seconds))

    # ------------------------------------------------------------------ #
    def start(self):
        """Auto-start every subsystem, then run the UI loop."""
        errors = []

        # Camera — auto-on
        if self.camera.start():
            self.hud.set_status("camera", "ON", good=True)
        else:
            self.hud.set_status("camera", "OFF", good=False)
            errors.append(self.camera.error or "Camera unavailable")

        # Gestures — auto-on (needs camera + tracker)
        if self.camera.available and self.tracker.available:
            self.hud.set_status("gesture", "ON", good=True)
        else:
            self.hud.set_status("gesture", "OFF (limited mode)", good=False)
            if self.tracker.error:
                errors.append(self.tracker.error)

        # Microphone — auto-on
        if self.mic.detect():
            self.hud.set_status("mic", "ON", good=True)
        else:
            self.hud.set_status("mic", "OFF", good=False)
            errors.append(self.mic.error or "Microphone unavailable")

        # Voice — auto-on (needs mic)
        if self.mic.available and self.voice.start():
            self.hud.set_status("voice", "LISTENING", good=True)
        else:
            self.hud.set_status("voice", "OFF (limited mode)", good=False)
            if self.voice.error:
                errors.append(self.voice.error)

        if errors:
            self.hud.limited_mode = True
            for e in errors:
                self.hud.set_error(e)

        # V2: start the resource monitor and set the mini HUD's state.
        self.monitor.start()
        if self.voice.available and settings.wake_word_enabled:
            self.air_hud.set_idle_text("AIR sleeping — say 'wake up'")
        elif self.voice.available:
            self.air_hud.set_idle_text("AIR ready — listening")
        else:
            self.air_hud.set_idle_text("AIR ready (voice off)")

        # Start the SensorWorker (camera → tracking → gestures) and the
        # Tk-side poll, then hand control to Tk.
        self.worker = SensorWorker(
            self.camera, self.tracker, self.router,
            self.state, self.events, self.commands,
            error_sources=(self.tracker, self.mouse, self.keyboard,
                           self.system, self.voice),
            # Interim size for the V2 panel preview; the AIR Pod sets
            # its own size at integration.
            preview_size=(320, 240),
            preview_enabled=self._preview_wanted())
        self.worker.start()
        self.hud.root.after(POLL_MS, self._poll)
        self.hud.run()

    # ------------------------------------------------------------------ #
    def _poll(self):
        """Tk-thread loop: dispatch UI events, render the newest worker
        snapshot, and tell the worker about UI state it depends on."""
        if not self._running:
            return
        try:
            for ev in self.events.drain(max_n=50):
                try:
                    self._dispatch(ev)
                except Exception:
                    # One bad event must not drop the rest of the batch.
                    traceback.print_exc()

            snap = self.state.read()
            if snap is not None and snap.seq != self._last_snap_seq:
                self._last_snap_seq = snap.seq
                self._render(snap)

            self._sync_worker_flags()

            # Voice status can change if the mic dies mid-session.
            if self.voice.available and not self.voice.listening:
                if not self._voice_off_shown:
                    self._voice_off_shown = True
                    self.hud.set_status("voice", "OFF", good=False)
        except Exception:
            # The loop must never die — log and keep going.
            traceback.print_exc()
        finally:
            if self._running:
                try:
                    self.hud.root.after(POLL_MS, self._poll)
                except Exception:
                    pass

    def _dispatch(self, ev):
        kind, data = ev.kind, ev.data
        if kind == EventKind.UI_CALL:
            data["fn"]()
        elif kind == EventKind.STATUS:
            self.hud.set_status(data["key"], data["text"],
                                good=data.get("good"))
        elif kind == EventKind.ERROR:
            self.hud.set_error(data["text"])
        elif kind == EventKind.LOG:
            print("[AIR]", data.get("text", ""))
        elif kind == EventKind.POD_SAY:
            self.air_hud.say(data["text"], data.get("kind", "info"),
                             data.get("hold_s", 6))
        elif kind == EventKind.WORKER_STOPPED:
            self._worker_stopped = True
        # OVERLAY_* / ACTION_RESULT / MODE_CHANGED arrive in Phase 2.

    def _render(self, snap):
        if snap.preview_rgb is not None and cv2 is not None:
            # The V2 panel preview expects BGR. cvtColor makes a new
            # array, so the published snapshot is never modified.
            self.hud.update_preview(
                cv2.cvtColor(snap.preview_rgb, cv2.COLOR_RGB2BGR))
        if self.camera.available:
            self._set_frequent("fps", f"{snap.fps:.0f}")
        self._set_frequent("cur_gesture", snap.gesture_label)

    def _set_frequent(self, key, text):
        """hud.set_status for per-frame values, skipped when unchanged.
        Only for keys nothing else writes (fps, cur_gesture)."""
        if self._shown.get(key) == text:
            return
        self._shown[key] = text
        self.hud.set_status(key, text)

    def _preview_wanted(self):
        # Interim: the V2 panel's preview toggle. At integration this
        # becomes "AIR Pod preview visible".
        return bool(getattr(self.hud, "_preview_visible", True))

    def _sync_worker_flags(self):
        want = self._preview_wanted()
        if want != self._preview_on:
            self._preview_on = want
            self.commands.send(CommandKind.SET_PREVIEW_ENABLED, on=want)
        popup = bool(self.hud.overlay_open)
        if popup != self._popup_open:
            self._popup_open = popup
            self.commands.send(CommandKind.SET_LEGACY_POPUP_OPEN, open=popup)

    # ------------------------------------------------------------------ #
    # V2: hands-free toggle (voice command "hands free mode")
    # ------------------------------------------------------------------ #
    def _set_hands_free(self, on):
        # Called from the voice thread: the worker owns the engine.
        self.commands.send(CommandKind.SET_GESTURES_PAUSED, paused=not on)

    # ------------------------------------------------------------------ #
    # V2: monitor alert -> HUD question -> safe close ladder
    # ------------------------------------------------------------------ #
    def _on_monitor_alert(self, message, proc_info):
        if proc_info is None:
            self._say(message, "warn", hold_seconds=10)
            return
        # Ask via HUD buttons AND voice (same pending-question path).
        self.voice.ask_question("close_process", proc_info,
                                message, ["Yes", "No"])

    def _on_question_answered(self, kind, payload, answer):
        answer = (answer or "").lower()
        if kind == "browser_choice":
            if answer in ("chrome", "edge", "default"):
                self._say(
                    f"Opening {payload.get('label','it')}...", "listen")
                self.system.open_in_browser(payload["url"], answer)
                self._say("Done ✓", "ok")
            else:
                self._say("Cancelled", "info")
            return

        if kind == "close_process":
            if answer != "yes":
                self._say("Okay, leaving it alone", "info")
                return
            name = payload.get("name", "it")
            # Extra confirmation for apps that may hold unsaved work.
            if self.monitor.needs_unsaved_warning(name):
                self.voice.ask_question(
                    "confirm_unsaved", payload,
                    f"{name} may have unsaved work. Really close it?",
                    ["Yes", "No"])
                return
            self._do_close(payload, force=False)
            return

        if kind == "confirm_unsaved":
            if answer == "yes":
                self._do_close(payload, force=False)
            else:
                self._say("Okay, leaving it alone", "info")
            return

        if kind == "force_close":
            if answer == "yes":
                self._do_close(payload, force=True)
            else:
                self._say("Okay, not forcing it", "info")

    def _do_close(self, payload, force):
        ok, msg = self.monitor.close_process(payload["pid"], force=force)
        self._say(msg, "ok" if ok else "warn", hold_seconds=8)
        if not ok and not force and "force" in msg:
            # Graceful close failed: offer (but never assume) a force kill.
            self.voice.ask_question(
                "force_close", payload,
                f"Force close {payload.get('name','it')}?", ["Yes", "No"])

    # ------------------------------------------------------------------ #
    def _request_shutdown(self):
        """Control Panel X: stop every thread without blocking Tk.
        The worker releases the camera and models itself; voice and the
        monitor are stopped on a helper thread because their stop()
        joins. Tk keeps polling and destroys the windows once everything
        has stopped, or after SHUTDOWN_DEADLINE_S at the latest."""
        if self._shutdown_deadline is not None:
            return  # already shutting down
        self._shutdown_deadline = time.monotonic() + SHUTDOWN_DEADLINE_S
        try:
            self.hud.set_status("action", "Shutting down…")
        except Exception:
            pass

        def stop_background():
            for fn in (self.voice.stop, self.monitor.stop):
                try:
                    fn()
                except Exception:
                    pass
        self._stopper = threading.Thread(target=stop_background,
                                         name="Stopper", daemon=True)
        self._stopper.start()

        if self.worker is not None and self.worker.is_alive():
            self.worker.stop()
        else:
            self._worker_stopped = True
            try:
                self.camera.stop()
                self.tracker.close()
            except Exception:
                pass
        self._await_shutdown()

    def _await_shutdown(self):
        done = self._worker_stopped and not self._stopper.is_alive()
        if done or time.monotonic() >= self._shutdown_deadline:
            self._finalize()
            return
        self.hud.root.after(50, self._await_shutdown)

    def _finalize(self):
        self._running = False
        settings.save()
        try:
            self.hud.root.destroy()
        except Exception:
            pass

def main():
    try:
        app = AirOS()
        app.start()
    except Exception as exc:
        # Absolute last resort: print a readable error instead of a
        # silent crash (e.g. Tk missing on a stripped-down Python).
        print("AIR OS failed to start:", exc)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
