"""
system_controller.py — OS-level actions for AIR OS V01.

Handles: volume (pycaw with key-press fallback), opening apps and
websites, screenshots, media play/pause, browser navigation, show
desktop / task view, closing windows, locking the PC, and battery
status. Dangerous actions (shutdown/restart) are exposed as separate
methods and are ONLY called after the UI confirms with the user.
"""

import ctypes
import datetime
import os
import subprocess
import sys
import threading
import webbrowser

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

# pycaw is Windows-only; anything else falls back to media keys.
PYCAW_AVAILABLE = False
if sys.platform == "win32":
    try:
        from ctypes import POINTER, cast
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        PYCAW_AVAILABLE = True
    except Exception:
        PYCAW_AVAILABLE = False

from keyboard_controller import KeyboardController
from utils import clamp

IS_WINDOWS = sys.platform == "win32"


class SystemController:
    """All 'do something to the OS' actions live here."""

    def __init__(self, keyboard: KeyboardController | None = None):
        self.keyboard = keyboard or KeyboardController()
        self.error = None
        self._volume = None
        self._com_ready = threading.local()  # per-thread COM init tracking
        self._acquire_volume()

    def _com_init(self):
        """pycaw/comtypes need COM initialized in EVERY thread that
        touches audio (the voice thread included) — the classic cause of
        'AudioDevice' errors when volume is changed by voice command."""
        if not PYCAW_AVAILABLE:
            return
        if getattr(self._com_ready, "done", False):
            return
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass  # already initialized in this thread — fine
        self._com_ready.done = True

    def _acquire_volume(self):
        """(Re)acquire the master volume endpoint. Safe to call again
        after a device change (headphones plugged in, etc.)."""
        if not PYCAW_AVAILABLE:
            return
        try:
            self._com_init()
            devices = AudioUtilities.GetSpeakers()
            interface = devices.Activate(IAudioEndpointVolume._iid_,
                                         CLSCTX_ALL, None)
            self._volume = cast(interface, POINTER(IAudioEndpointVolume))
            return
        except Exception as exc:
            self._volume = None
            self.error = f"Volume control fallback (pycaw: {exc})"

    # ---------------------- volume ----------------------------------- #
    def get_volume(self):
        """Current master volume 0-100, or None if unknown."""
        if self._volume is not None:
            try:
                self._com_init()
                return round(self._volume.GetMasterVolumeLevelScalar() * 100)
            except Exception:
                self._acquire_volume()  # device may have changed — retry once
                try:
                    return round(
                        self._volume.GetMasterVolumeLevelScalar() * 100)
                except Exception:
                    return None
        return None

    def set_volume(self, percent):
        percent = clamp(int(percent), 0, 100)
        if self._volume is not None:
            try:
                self._com_init()
                self._volume.SetMasterVolumeLevelScalar(percent / 100.0, None)
                return True
            except Exception:
                self._acquire_volume()  # retry once after re-acquiring
                try:
                    self._volume.SetMasterVolumeLevelScalar(
                        percent / 100.0, None)
                    return True
                except Exception as exc:
                    self.error = f"Volume error: {exc}"
        # Fallback: nudge with media keys toward the target.
        current = self.get_volume() or 50
        key = "volume up" if percent > current else "volume down"
        for _ in range(abs(percent - current) // 2):
            self.keyboard.press_key(key)
        return False

    def volume_step(self, up=True, step=4):
        if self._volume is not None:
            self._com_init()
            cur = self.get_volume()
            if cur is not None:
                self.set_volume(cur + (step if up else -step))
                return
        self.keyboard.press_key("volume up" if up else "volume down")

    def mute(self, state=True):
        if self._volume is not None:
            try:
                self._com_init()
                self._volume.SetMute(1 if state else 0, None)
                return
            except Exception:
                pass
        self.keyboard.press_key("volume mute")

    # ---------------------- apps & web -------------------------------- #
    def open_url(self, url):
        try:
            webbrowser.open(url)
        except Exception as exc:
            self.error = f"Could not open browser: {exc}"

    def open_app(self, name):
        """
        Open a known app by friendly name. Uses `start` on Windows so
        the shell resolves the path; returns True if launch was attempted.
        """
        name = name.lower().strip()
        try:
            if name in ("chrome", "google chrome"):
                if IS_WINDOWS:
                    os.system('start "" chrome')
                else:
                    self.open_url("https://www.google.com")
            elif name in ("vs code", "vscode", "code", "visual studio code"):
                # `code` is on PATH after a normal VS Code install.
                subprocess.Popen("code", shell=True)
            elif name in ("downloads", "downloads folder"):
                path = os.path.join(os.path.expanduser("~"), "Downloads")
                if IS_WINDOWS:
                    os.startfile(path)  # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["xdg-open", path])
            elif name in ("youtube",):
                self.open_url("https://www.youtube.com")
            elif name in ("github",):
                self.open_url("https://www.github.com")
            elif name in ("gmail",):
                self.open_url("https://mail.google.com")
            else:
                if IS_WINDOWS:
                    os.system(f'start "" "{name}"')
                else:
                    subprocess.Popen(name, shell=True)
            return True
        except Exception as exc:
            self.error = f"Could not open {name}: {exc}"
            return False

    # ================== AIR OS V2 additions ========================== #
    def available_browsers(self):
        """Which known browsers exist on this machine?
        Returns a list like ['chrome', 'edge'] (+ 'default' is always
        implied). Non-Windows returns ['default']."""
        found = []
        if IS_WINDOWS:
            pf = os.environ.get("ProgramFiles", r"C:\Program Files")
            pf86 = os.environ.get("ProgramFiles(x86)",
                                  r"C:\Program Files (x86)")
            local = os.environ.get("LocalAppData", "")
            chrome_paths = [
                os.path.join(pf, "Google", "Chrome", "Application",
                             "chrome.exe"),
                os.path.join(pf86, "Google", "Chrome", "Application",
                             "chrome.exe"),
                os.path.join(local, "Google", "Chrome", "Application",
                             "chrome.exe"),
            ]
            edge_paths = [
                os.path.join(pf86, "Microsoft", "Edge", "Application",
                             "msedge.exe"),
                os.path.join(pf, "Microsoft", "Edge", "Application",
                             "msedge.exe"),
            ]
            if any(os.path.exists(p) for p in chrome_paths):
                found.append("chrome")
            if any(os.path.exists(p) for p in edge_paths):
                found.append("edge")
        if found:
            found.append("default")
        else:
            found = ["default"]
        return found

    def open_in_browser(self, url, browser="default"):
        """Open a URL in a specific browser ('chrome'/'edge') or the
        system default. Falls back to the default browser on failure."""
        browser = (browser or "default").lower()
        try:
            if IS_WINDOWS and browser == "chrome":
                os.system(f'start chrome "{url}"')
            elif IS_WINDOWS and browser == "edge":
                os.system(f'start msedge "{url}"')
            else:
                webbrowser.open(url)
        except Exception:
            self.open_url(url)

    def open_terminal(self):
        """Open a command prompt / terminal window."""
        try:
            if IS_WINDOWS:
                os.system("start cmd")
            else:
                subprocess.Popen(["x-terminal-emulator"])
        except Exception as exc:
            self.error = f"Could not open terminal: {exc}"

    def compose_gmail(self, to_email, body, subject=""):
        """Open a pre-filled Gmail compose window in the browser.
        NO Gmail API, NO OAuth, NOTHING is sent automatically — the
        user reviews the draft and clicks Send themselves. Falls back
        to a mailto: link if the browser can't open Gmail."""
        from urllib.parse import quote
        url = ("https://mail.google.com/mail/?view=cm&fs=1"
               f"&to={quote(to_email)}"
               f"&su={quote(subject)}"
               f"&body={quote(body)}")
        try:
            webbrowser.open(url)
        except Exception:
            self.open_url(f"mailto:{to_email}?subject={quote(subject)}"
                          f"&body={quote(body)}")

    # ================================================================== #
    def search_youtube(self, query):
        from urllib.parse import quote_plus
        self.open_url(f"https://www.youtube.com/results?search_query={quote_plus(query)}")

    def search_google(self, query):
        from urllib.parse import quote_plus
        self.open_url(f"https://www.google.com/search?q={quote_plus(query)}")

    # ---------------------- window / desktop -------------------------- #
    def close_active_window(self):
        self.keyboard.hotkey("alt", "f4")

    def show_desktop(self):
        self.keyboard.hotkey("win", "d")

    def task_view(self):
        self.keyboard.hotkey("win", "tab")

    def browser_back(self):
        self.keyboard.hotkey("alt", "left")

    def browser_forward(self):
        self.keyboard.hotkey("alt", "right")

    def play_pause_media(self):
        self.keyboard.press_key("play/pause media")

    # ---------------------- misc -------------------------------------- #
    def screenshot(self):
        """Save a screenshot to the user's Pictures folder."""
        try:
            import pyautogui
            folder = os.path.join(os.path.expanduser("~"), "Pictures")
            os.makedirs(folder, exist_ok=True)
            stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(folder, f"airos_screenshot_{stamp}.png")
            pyautogui.screenshot(path)
            return path
        except Exception as exc:
            self.error = f"Screenshot failed: {exc}"
            return None

    def lock_pc(self):
        try:
            if IS_WINDOWS:
                ctypes.windll.user32.LockWorkStation()
            else:
                subprocess.Popen(["loginctl", "lock-session"])
        except Exception as exc:
            self.error = f"Lock failed: {exc}"

    def battery_status(self):
        """Readable battery string, e.g. '87% (charging)'."""
        if not PSUTIL_AVAILABLE:
            return "Battery info unavailable (psutil missing)"
        try:
            batt = psutil.sensors_battery()
            if batt is None:
                return "No battery detected (desktop PC?)"
            state = "charging" if batt.power_plugged else "on battery"
            return f"Battery is at {batt.percent}% ({state})"
        except Exception:
            return "Battery info unavailable"

    # ------------- DANGEROUS: only after user confirmation ------------ #
    def shutdown(self):
        """Shut down the PC. MUST be gated behind a confirmation dialog."""
        try:
            if IS_WINDOWS:
                os.system("shutdown /s /t 5")
            else:
                subprocess.Popen(["shutdown", "-h", "now"])
        except Exception as exc:
            self.error = f"Shutdown failed: {exc}"

    def restart(self):
        """Restart the PC. MUST be gated behind a confirmation dialog."""
        try:
            if IS_WINDOWS:
                os.system("shutdown /r /t 5")
            else:
                subprocess.Popen(["shutdown", "-r", "now"])
        except Exception as exc:
            self.error = f"Restart failed: {exc}"
