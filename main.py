"""
main.py — AIR OS V01 entry point.

Boot order (all automatic, no Start button):
  1. Build the HUD window.
  2. Start the camera thread          → limited mode if it fails
  3. Detect + start the microphone    → limited mode if it fails
  4. Start hand tracking + gestures   → runs off the camera frames
  5. Start the always-on voice loop
  6. Enter the UI loop; a ~30 FPS tick pulls frames, runs tracking,
     feeds the gesture engine, and refreshes the HUD.

Everything hardware-related is wrapped so a missing camera or mic
shows a readable error in the HUD instead of crashing.

Run with:  python main.py
"""

import sys
import traceback

from settings import settings
from utils import FPSCounter

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

TICK_MS = 15  # UI loop interval (~capped by camera FPS anyway)


class AirOS:
    """Wires every subsystem together and runs the main loop."""

    def __init__(self):
        # ---- UI first, so every error has somewhere to be shown -------
        self.hud = HUD()
        self.hud.on_close = self.shutdown
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
        self.gestures = GestureEngine(
            self.mouse, self.keyboard, self.system,
            callbacks={
                "on_gesture": lambda g: self._ui(
                    lambda: self.hud.set_status("cur_gesture", g)),
                "on_action": lambda a: self._ui(
                    lambda: self.hud.set_status("action", a)),
                "toggle_keyboard": lambda: self._ui(self.vkeyboard.toggle),
                "close_overlay": lambda: self._ui(self.hud.close_overlay),
                "set_paused": lambda p: self._ui(
                    lambda: self.hud.set_status(
                        "gesture", "PAUSED" if p else "ON", good=not p)),
                # V2: pinky-up gesture hides/restores the mini HUD.
                "toggle_air_hud": self.air_hud.toggle,
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
                "on_hud": lambda t, k="info", h=6:
                    self.air_hud.say(t, k, h),
                "ask_choice": lambda q, opts, cb:
                    self.air_hud.ask(q, opts, cb),
                "on_question_answered": self._on_question_answered,
                "set_hands_free": self._set_hands_free,
                "explain_system": lambda: self.monitor.explain(),
            })

        # V2: background CPU/RAM/battery monitor -> calm HUD questions.
        self.monitor = SystemMonitor(callbacks={
            "on_alert": self._on_monitor_alert,
        })

        self.fps = FPSCounter()
        self._running = True

    # ------------------------------------------------------------------ #
    def _ui(self, fn):
        """Marshal a callable onto the Tk main thread (thread-safe UI)."""
        try:
            self.hud.root.after(0, fn)
        except Exception:
            pass

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

        # Kick off the frame loop and hand control to Tk.
        self.hud.root.after(TICK_MS, self._tick)
        self.hud.run()

    # ------------------------------------------------------------------ #
    def _tick(self):
        """One frame of the main loop (runs on the Tk thread)."""
        if not self._running:
            return
        try:
            if self.camera.available:
                ok, frame = self.camera.read()
                if ok:
                    self.fps.tick()
                    landmarks, frame = self.tracker.process(frame, draw=True)
                    if settings.get("two_hand_gestures"):
                        self.gestures.process_multi(self.tracker.last_hands)
                    else:
                        self.gestures.process(landmarks)
                    self.hud.update_preview(frame)
                    self.hud.set_status("fps", f"{self.fps.fps:.0f}")
            else:
                # Camera died mid-session? Reflect it once.
                if self.camera.error:
                    self.hud.set_status("camera", "OFF", good=False)
                    self.hud.set_status("gesture", "OFF", good=False)
                    self.hud.set_error(self.camera.error)
                    self.camera.error = None  # show once, don't spam

            # Surface any new subsystem errors in the HUD.
            for src in (self.tracker, self.mouse, self.keyboard,
                        self.system, self.voice):
                if getattr(src, "error", None):
                    self.hud.set_error(src.error)
                    src.error = None

            # Voice status can change if the mic dies mid-session.
            if self.voice.available and not self.voice.listening:
                self.hud.set_status("voice", "OFF", good=False)
        except Exception:
            # The loop must never die — log and keep going.
            traceback.print_exc()
        finally:
            if self._running:
                try:
                    self.hud.root.after(TICK_MS, self._tick)
                except Exception:
                    pass

    # ------------------------------------------------------------------ #
    # V2: hands-free toggle (voice command "hands free mode")
    # ------------------------------------------------------------------ #
    def _set_hands_free(self, on):
        self.gestures.paused = not on
        self._ui(lambda: self.hud.set_status(
            "gesture", "ON" if on else "PAUSED", good=on))

    # ------------------------------------------------------------------ #
    # V2: monitor alert -> HUD question -> safe close ladder
    # ------------------------------------------------------------------ #
    def _on_monitor_alert(self, message, proc_info):
        if proc_info is None:
            self.air_hud.say(message, "warn", hold_seconds=10)
            return
        # Ask via HUD buttons AND voice (same pending-question path).
        self.voice.ask_question("close_process", proc_info,
                                message, ["Yes", "No"])

    def _on_question_answered(self, kind, payload, answer):
        answer = (answer or "").lower()
        if kind == "browser_choice":
            if answer in ("chrome", "edge", "default"):
                self.air_hud.say(
                    f"Opening {payload.get('label','it')}...", "listen")
                self.system.open_in_browser(payload["url"], answer)
                self.air_hud.say("Done ✓", "ok")
            else:
                self.air_hud.say("Cancelled", "info")
            return

        if kind == "close_process":
            if answer != "yes":
                self.air_hud.say("Okay, leaving it alone", "info")
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
                self.air_hud.say("Okay, leaving it alone", "info")
            return

        if kind == "force_close":
            if answer == "yes":
                self._do_close(payload, force=True)
            else:
                self.air_hud.say("Okay, not forcing it", "info")

    def _do_close(self, payload, force):
        ok, msg = self.monitor.close_process(payload["pid"], force=force)
        self.air_hud.say(msg, "ok" if ok else "warn", hold_seconds=8)
        if not ok and not force and "force" in msg:
            # Graceful close failed: offer (but never assume) a force kill.
            self.voice.ask_question(
                "force_close", payload,
                f"Force close {payload.get('name','it')}?", ["Yes", "No"])

    # ------------------------------------------------------------------ #
    def shutdown(self):
        """Clean shutdown of every thread and device."""
        self._running = False
        try:
            self.voice.stop()
        except Exception:
            pass
        try:
            self.monitor.stop()
        except Exception:
            pass
        try:
            self.camera.stop()
        except Exception:
            pass
        try:
            self.tracker.close()
        except Exception:
            pass
        settings.save()


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
