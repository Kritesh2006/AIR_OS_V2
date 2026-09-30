"""
microphone.py — Microphone detection and status for AIR OS V01.

Checks whether a working microphone exists BEFORE the voice engine
tries to use it, so the app can start in limited mode with a clear
message instead of crashing.
"""

try:
    import speech_recognition as sr
    SR_AVAILABLE = True
except ImportError:
    sr = None
    SR_AVAILABLE = False


class MicrophoneManager:
    """Detects available microphones and reports readable status."""

    def __init__(self):
        self.available = False
        self.error = None
        self.device_name = None

    def detect(self):
        """
        Probe for a microphone. Returns True if one is usable.
        Never raises — all failures become a readable `self.error`.
        """
        if not SR_AVAILABLE:
            self.error = "SpeechRecognition not installed — mic disabled"
            return False
        # Try PyAudio first (classic backend)…
        try:
            names = sr.Microphone.list_microphone_names()
            if names:
                mic = sr.Microphone()
                with mic as _source:
                    pass
                self.device_name = names[0]
                self.available = True
                self.error = None
                return True
            self.error = "No microphone detected on this system"
        except Exception as exc:
            self.error = f"PyAudio unavailable: {exc}"
        # …then sounddevice (works when PyAudio has no wheel, e.g. Py 3.13).
        try:
            import sounddevice as sd
            sd.check_input_settings(samplerate=16000, channels=1,
                                    dtype="int16")
            dev = sd.query_devices(kind="input")
            self.device_name = dev.get("name", "Default microphone")
            self.available = True
            self.error = None
            return True
        except Exception as exc:
            if "PyAudio" in (self.error or ""):
                self.error = f"No working microphone backend: {exc}"
        self.available = False
        return False

    def status_text(self):
        """Short status string for the HUD."""
        if self.available:
            return "ON"
        return "OFF"
