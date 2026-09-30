"""
voice_engine.py — Always-on voice command listener for AIR OS V01.

Listens on a background thread from the moment the app launches.
Uses the SpeechRecognition library with Google's free web recognizer
(needs internet). If the mic is missing or recognition fails, the
app keeps running in limited mode with a readable error in the HUD.

Dangerous commands (shutdown / restart / delete) are NEVER executed
directly — they are handed to the UI, which shows a confirmation
overlay first.
"""

import json
import os
import re
import threading

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    sr = None
    SR_AVAILABLE = False

# sr.Microphone needs PyAudio, which has no prebuilt wheels on newer
# Python versions (e.g. 3.13) and often fails to install on Windows.
# sounddevice ships wheels everywhere, so we use it as a fallback
# capture backend and hand raw audio to SpeechRecognition ourselves.
try:
    import pyaudio  # noqa: F401
    PYAUDIO_AVAILABLE = True
except Exception:
    PYAUDIO_AVAILABLE = False

try:
    import sounddevice as sd
    import numpy as _np
    SD_AVAILABLE = True
except Exception:
    sd = None
    SD_AVAILABLE = False

from settings import settings


class VoiceEngine:
    """Background microphone listener + command dispatcher."""

    def __init__(self, system, callbacks=None):
        """
        callbacks: optional UI hooks —
          on_heard(text)                    raw transcript for the HUD
          on_action(description)            what we did
          request_confirmation(label, fn)   dangerous command gate
          on_speak(text)                    answer to show/say (battery etc.)
        """
        self.system = system
        self.cb = callbacks or {}
        self.available = False
        self.listening = False
        self.error = None
        self._thread = None
        self._stop = threading.Event()
        self._recognizer = None
        self._mic = None
        self.backend = None  # "pyaudio" or "sounddevice"

        # ---------------- AIR OS V2: wake state machine ----------------
        # States: "active"            -> executes commands (V1 behavior)
        #         "sleeping"          -> ignores everything except the
        #                                wake word ("wake up")
        #         "awaiting_passcode" -> next phrase is checked against
        #                                the passcode
        # With wake_word_enabled=False AIR starts (and stays) active,
        # which is exactly the V1 behavior.
        self.state = "sleeping" if settings.wake_word_enabled else "active"
        # Pending HUD question ("browser_choice", "close_process", ...):
        # while set, the next phrase answers the question instead of
        # being treated as a command.
        self._pending = None      # (kind, payload)
        self.hands_free = True    # gesture tracking on/off via voice

    # ------------------------------------------------------------------ #
    def start(self):
        """Start the mic. Never raises — failure = limited mode."""
        if not settings.voice_enabled:
            self.error = "Voice disabled in settings"
            return False
        if not SR_AVAILABLE:
            self.error = "SpeechRecognition not installed — voice disabled"
            return False
        self._recognizer = sr.Recognizer()
        self._recognizer.energy_threshold = settings.voice_energy_threshold
        self._recognizer.dynamic_energy_threshold = True
        self._recognizer.pause_threshold = settings.voice_pause_threshold

        # Backend 1: PyAudio (classic SpeechRecognition microphone)
        if PYAUDIO_AVAILABLE:
            try:
                self._mic = sr.Microphone()
                with self._mic as source:
                    self._recognizer.adjust_for_ambient_noise(
                        source, duration=0.6)
                self.backend = "pyaudio"
            except Exception as exc:
                self.error = f"PyAudio mic failed: {exc}"
                self._mic = None

        # Backend 2: sounddevice fallback (works when PyAudio is missing,
        # e.g. on Python 3.13 where PyAudio has no prebuilt wheel).
        if self._mic is None and SD_AVAILABLE:
            try:
                sd.check_input_settings(samplerate=16000, channels=1,
                                        dtype="int16")
                self.backend = "sounddevice"
                self.error = None
            except Exception as exc:
                self.error = f"Microphone unavailable: {exc}"

        if self.backend is None:
            if not self.error:
                self.error = ("No mic backend — install PyAudio or "
                              "sounddevice")
            self.available = False
            return False

        self.available = True
        self.listening = True
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop,
                                        name="VoiceThread", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        self.listening = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    # ------------------------------------------------------------------ #
    def _capture_sounddevice(self):
        """Record a phrase with sounddevice and wrap it as sr.AudioData.
        Simple energy gate: skip chunks that are silence."""
        rate, secs = 16000, 4
        rec = sd.rec(int(rate * secs), samplerate=rate, channels=1,
                     dtype="int16")
        sd.wait()
        mono = rec.reshape(-1)
        # Silence gate — don't waste API calls on quiet rooms.
        if _np.abs(mono).mean() < 60:
            return None
        return sr.AudioData(mono.tobytes(), rate, 2)

    def _loop(self):
        while not self._stop.is_set():
            try:
                if self.backend == "pyaudio":
                    with self._mic as source:
                        audio = self._recognizer.listen(
                            source, timeout=4, phrase_time_limit=6)
                else:
                    audio = self._capture_sounddevice()
                    if audio is None:
                        continue  # silence — keep listening
            except sr.WaitTimeoutError:
                continue  # nothing said — keep listening
            except Exception as exc:
                self.error = f"Mic error: {exc}"
                self.available = False
                self.listening = False
                return

            try:
                text = self._recognizer.recognize_google(audio)
            except sr.UnknownValueError:
                continue  # speech was unintelligible — normal, ignore
            except sr.RequestError as exc:
                self.error = f"Speech service unreachable: {exc}"
                continue
            except Exception as exc:
                self.error = f"Recognition error: {exc}"
                continue

            text = text.lower().strip()
            self._emit("on_heard", text)
            try:
                self.handle_utterance(text)
            except Exception as exc:
                self.error = f"Command error: {exc}"

    def _emit(self, name, *args):
        fn = self.cb.get(name)
        if fn:
            try:
                fn(*args)
            except Exception:
                pass

    def _action(self, text):
        self._emit("on_action", text)

    # ================================================================== #
    # AIR OS V2 — wake word, passcode, pending questions. Pure functions
    # of the transcript (fully unit-testable without a microphone).
    # ================================================================== #
    def _hud(self, text, kind="info", hold=6):
        fn = self.cb.get("on_hud")
        if fn:
            try:
                fn(text, kind, hold)
            except Exception:
                pass

    @staticmethod
    def _normalize_digits(text):
        """'two three three one' / '23 31' / '2331' -> '2331'."""
        words = {"zero": "0", "oh": "0", "one": "1", "two": "2", "to": "2",
                 "three": "3", "four": "4", "for": "4", "five": "5",
                 "six": "6", "seven": "7", "eight": "8", "nine": "9"}
        out = []
        for tok in re.split(r"[\s,.-]+", text.lower()):
            if tok.isdigit():
                out.append(tok)
            elif tok in words:
                out.append(words[tok])
        return "".join(out)

    def handle_utterance(self, text):
        """Entry point for every recognized phrase (state-aware)."""
        # ---- asleep: only the wake word matters -----------------------
        if self.state == "sleeping":
            if settings.wake_word in text:
                self.state = "awaiting_passcode"
                self._hud("Passcode?", "listen", hold=0)
                return "awaiting passcode"
            return None  # everything else is ignored while sleeping

        # ---- waiting for the passcode ---------------------------------
        if self.state == "awaiting_passcode":
            if re.search(r"\b(sleep|cancel|never ?mind)\b", text):
                self.state = "sleeping"
                self._hud("AIR sleeping — say 'wake up'", "info")
                return "back to sleep"
            if self._normalize_digits(text) == str(settings.passcode):
                self.state = "active"
                self._hud("AIR activated ✓ Listening...", "ok")
                self._emit("on_action", "AIR activated")
                return "activated"
            self._hud("Wrong passcode — try again, or say 'cancel'",
                      "warn", hold=0)
            return "wrong passcode"

        # ---- active: pending HUD question? ----------------------------
        if self._pending is not None:
            if self._answer_pending(text):
                return "answered question"
            # fall through: an unrelated command cancels nothing; the
            # question stays open on the HUD.

        # ---- active: sleep / lock commands ----------------------------
        if re.search(r"\b(go to sleep|sleep|stop listening|lock air)\b",
                     text):
            if settings.wake_word_enabled:
                self.state = "sleeping"
                self._hud("AIR locked — say 'wake up' to resume", "info")
                self._emit("on_action", "AIR sleeping")
                return "sleeping"
            self._hud("Wake lock is disabled in settings", "warn")
            return "wake disabled"

        return self.handle_command(text)

    # ------------------- pending-question answers ---------------------- #
    def ask_question(self, kind, payload, question, options):
        """Register a question that voice OR HUD buttons can answer."""
        self._pending = (kind, payload)
        ask = self.cb.get("ask_choice")
        if ask:
            try:
                # HUD button click resolves through the same path:
                ask(question, options,
                    lambda ans: self.resolve_pending(ans))
                return
            except Exception:
                pass
        self._hud(question + "  (" + " / ".join(options) + ")",
                  "listen", hold=0)

    def _answer_pending(self, text):
        kind, payload = self._pending
        if kind == "browser_choice":
            for name in ("chrome", "edge", "default"):
                if name in text:
                    self.resolve_pending(name)
                    return True
            if re.search(r"\b(cancel|never ?mind|no)\b", text):
                self.resolve_pending(None)
                return True
            return False
        if kind in ("close_process", "confirm_unsaved", "force_close"):
            if re.search(r"\b(yes|yeah|sure|close it|do it|force close)\b",
                         text):
                self.resolve_pending("yes")
                return True
            if re.search(r"\b(no|nope|cancel|leave it|keep it)\b", text):
                self.resolve_pending("no")
                return True
            return False
        return False

    def resolve_pending(self, answer):
        """Resolve the open question (from voice or a HUD button)."""
        if self._pending is None:
            return
        kind, payload = self._pending
        self._pending = None
        fn = self.cb.get("on_question_answered")
        if fn:
            try:
                fn(kind, payload, answer)
            except Exception as exc:
                self.error = f"Question handler error: {exc}"

    # ------------------------- contacts -------------------------------- #
    @staticmethod
    def load_contacts():
        """Read contacts.json fresh each time, so new contacts work
        without restarting AIR (and without code changes)."""
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "contacts.json")
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def find_contact(self, name):
        name = name.lower().strip()
        for c in self.load_contacts():
            cname = str(c.get("name", "")).lower()
            if cname == name or cname.startswith(name):
                return c
        return None

    # ------------------------------------------------------------------ #
    # Command parsing — a pure function of the transcript, so it can be
    # unit-tested without any microphone. Returns a short description of
    # what was done (or None if the phrase wasn't a known command).
    # ------------------------------------------------------------------ #
    def handle_command(self, text):
        sysc = self.system

        # ---------- dangerous commands: confirmation required ----------
        if re.search(r"\b(shut ?down|power off)\b", text):
            self._confirm("Shut down this PC?", sysc.shutdown)
            return "confirm shutdown"
        if re.search(r"\brestart\b|\breboot\b", text):
            self._confirm("Restart this PC?", sysc.restart)
            return "confirm restart"
        if re.search(r"\bdelete\b", text):
            # We never delete files by voice, even with confirmation.
            self._emit("on_speak",
                       "Deleting files by voice is disabled for safety.")
            return "delete refused"

        # ---------- searches (checked before plain "open") -------------
        m = re.search(r"search youtube for (.+)", text)
        if m:
            sysc.search_youtube(m.group(1))
            self._action(f"YouTube search: {m.group(1)}")
            return "youtube search"
        m = re.search(r"search google for (.+)", text)
        if m:
            sysc.search_google(m.group(1))
            self._action(f"Google search: {m.group(1)}")
            return "google search"

        # ================== AIR OS V2 commands ==========================
        # ---- send mail (no API: opens Gmail compose pre-filled) --------
        m = re.search(r"send (?:an? )?e?mail to (\w+)"
                      r"(?: saying| that says| saying that)? (.+)", text)
        if m:
            name, body = m.group(1), m.group(2).strip()
            contact = self.find_contact(name)
            if contact is None:
                self._hud(f"No contact called '{name}'. Add them to "
                          f"contacts.json and try again.", "warn")
                return "contact not found"
            self._hud(f"Preparing mail to {contact['name']}...", "listen")
            sysc.compose_gmail(contact["email"], body)
            self._hud("Compose opened — review it and press Send ✓", "ok")
            self._action(f"Drafted mail to {contact['name']}")
            return "compose mail"

        # ---- open Gmail: ask which browser ------------------------------
        if re.search(r"\bopen gmail\b", text):
            browsers = sysc.available_browsers()
            if len(browsers) <= 1:
                choice = browsers[0] if browsers else "default"
                self._hud(f"Opening Gmail ({choice})...", "listen")
                sysc.open_in_browser("https://mail.google.com", choice)
                self._hud("Done ✓", "ok")
                self._action("Opened Gmail")
                return "open gmail"
            self.ask_question(
                "browser_choice", {"url": "https://mail.google.com",
                                   "label": "Gmail"},
                "Which browser?", [b.capitalize() for b in browsers])
            return "browser question"

        # ---- open browser (same choice flow) ----------------------------
        if re.search(r"\bopen (?:the |a |my )?browser\b", text):
            browsers = sysc.available_browsers()
            if len(browsers) <= 1:
                choice = browsers[0] if browsers else "default"
                sysc.open_in_browser("https://www.google.com", choice)
                self._hud("Done ✓", "ok")
                return "open browser"
            self.ask_question(
                "browser_choice", {"url": "https://www.google.com",
                                   "label": "browser"},
                "Which browser?", [b.capitalize() for b in browsers])
            return "browser question"

        # ---- simple V2 opens --------------------------------------------
        if re.search(r"\bopen google\b", text):
            self._hud("Opening Google...", "listen")
            sysc.open_url("https://www.google.com")
            self._hud("Done ✓", "ok")
            self._action("Opened Google")
            return "open google"
        if re.search(r"\bopen (?:the )?(terminal|command prompt|cmd)\b",
                     text):
            self._hud("Opening terminal...", "listen")
            sysc.open_terminal()
            self._hud("Done ✓", "ok")
            self._action("Opened terminal")
            return "open terminal"
        if re.search(r"(what'?s new|show me what'?s new)", text):
            self._hud("Opening what's new...", "listen")
            sysc.open_url("https://news.google.com")
            self._hud("Done ✓", "ok")
            self._action("Opened Google News")
            return "whats new"

        # ---- hands free mode --------------------------------------------
        if re.search(r"\bhands[- ]?free( mode)?( on| off)?\b", text):
            turn_off = bool(re.search(r"off", text))
            self.hands_free = not turn_off
            fn = self.cb.get("set_hands_free")
            if fn:
                try:
                    fn(self.hands_free)
                except Exception:
                    pass
            self._hud("Hands-free mode ON — gestures active" if
                      self.hands_free else "Hands-free mode OFF", "ok")
            self._action("Hands-free " +
                         ("ON" if self.hands_free else "OFF"))
            return "hands free"

        # ---- why is my laptop slow --------------------------------------
        if re.search(r"why is my (laptop|computer|pc) (so )?slow", text) or \
                "laptop slow" in text:
            fn = self.cb.get("explain_system")
            answer = fn() if fn else "System monitor is not running."
            self._hud(answer, "info", hold=14)
            self._action("Explained system load")
            return "explain slow"

        # ================== end V2 commands =============================

        # ---------- open <thing> ----------------------------------------
        m = re.search(r"\bopen (youtube|github|gmail|chrome|vs ?code|"
                      r"visual studio code|downloads?)( folder)?\b", text)
        if m:
            target = m.group(1)
            sysc.open_app(target)
            self._action(f"Opened {target}")
            return f"open {target}"

        # ---------- volume ----------------------------------------------
        m = re.search(r"\bvolume (?:to )?(\d{1,3})\b", text)
        if m:
            level = int(m.group(1))
            sysc.set_volume(level)
            self._action(f"Volume set to {level}%")
            return "volume set"
        if re.search(r"\bunmute\b", text):
            sysc.mute(False)
            self._action("Unmuted")
            return "unmute"
        if re.search(r"\bmute\b", text):
            sysc.mute(True)
            self._action("Muted")
            return "mute"

        # ---------- window / system -------------------------------------
        if re.search(r"\bclose (the )?current (app|window)\b", text) or \
                text.strip() == "close current app":
            sysc.close_active_window()
            self._action("Closed current app")
            return "close app"
        if re.search(r"\block (my |the )?(pc|computer|screen)\b", text):
            sysc.lock_pc()
            self._action("Locking PC")
            return "lock"
        if re.search(r"\b(what is|what's|check) (my )?battery\b", text) or \
                "battery" in text and ("what" in text or "how" in text):
            status = sysc.battery_status()
            self._emit("on_speak", status)
            self._action(status)
            return "battery"

        return None  # not a recognized command

    def _confirm(self, label, fn):
        """Route a dangerous action through the UI confirmation overlay."""
        gate = self.cb.get("request_confirmation")
        if gate:
            gate(label, fn)
        else:
            # No UI available => refuse rather than execute.
            self._emit("on_speak", f"Cannot confirm '{label}' — action cancelled.")
