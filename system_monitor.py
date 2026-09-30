"""
system_monitor.py — AIR OS V2 system resource monitor + explain mode.

Watches CPU, RAM and battery in a background thread. When usage stays
high for several samples in a row, it calmly asks (through the mini
HUD) whether you want to close the heaviest app — it NEVER closes
anything on its own.

Safety ladder for closing a process:
  1. Ask first:      "Chrome is using high memory. Close it?"
  2. If the app is a known could-have-unsaved-work type (editors,
     Office, browsers…), ask ONE more explicit confirmation.
  3. Try a graceful terminate() first.
  4. Only force-kill if the graceful close didn't work AND the user
     explicitly confirms the force kill.

Also powers the "why is my laptop slow?" voice command via explain().
"""

import ctypes
import sys
import threading
import time

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    psutil = None
    PSUTIL_AVAILABLE = False

from settings import settings

IS_WINDOWS = sys.platform == "win32"

# Apps that commonly hold unsaved work — closing them gets an extra
# confirmation step. (Matched against the process name, lowercase.)
UNSAVED_RISK = (
    "winword", "excel", "powerpnt", "notepad", "notepad++", "code",
    "photoshop", "illustrator", "premiere", "blender", "chrome",
    "msedge", "firefox", "brave", "obs64", "audacity",
)

# Background/system processes we should never suggest closing.
NEVER_SUGGEST = (
    "system", "system idle process", "registry", "memcompression",
    "svchost.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
    "dwm.exe", "explorer.exe", "python.exe", "pythonw.exe",
)


class SystemMonitor:
    """Background CPU/RAM/battery watcher with calm HUD alerts."""

    def __init__(self, callbacks=None):
        """
        callbacks:
          on_alert(message, process_info)  high-usage alert for the HUD;
              process_info is {"pid": int, "name": str} or None
        """
        self.cb = callbacks or {}
        self.available = PSUTIL_AVAILABLE
        self.error = None if PSUTIL_AVAILABLE else \
            "psutil missing — system monitor disabled"
        self._thread = None
        self._stop = threading.Event()
        self._high_streak = 0
        self._last_alert = 0.0

    # ------------------------------------------------------------------ #
    def start(self):
        if not self.available or not settings.monitor_enabled:
            if not settings.monitor_enabled:
                self.error = "Monitor disabled in settings"
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop,
                                        name="MonitorThread", daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

    # ------------------------------------------------------------------ #
    def _loop(self):
        # First cpu_percent call primes the counters (returns 0.0).
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass
        while not self._stop.wait(settings.monitor_interval_seconds):
            try:
                self._sample()
            except Exception as exc:
                self.error = f"Monitor error: {exc}"

    def _sample(self):
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent

        if cpu >= settings.cpu_alert_percent or \
                ram >= settings.ram_alert_percent:
            self._high_streak += 1
        else:
            self._high_streak = 0
            return

        # Must be high for N samples in a row, and respect the cooldown
        # so AIR never nags.
        if self._high_streak < settings.monitor_sustained_samples:
            return
        if time.time() - self._last_alert < settings.monitor_alert_cooldown:
            return
        self._last_alert = time.time()
        self._high_streak = 0

        kind = "CPU" if cpu >= settings.cpu_alert_percent else "memory"
        top = (self.top_process("cpu") if kind == "CPU"
               else self.top_process("ram"))
        if top:
            msg = (f"{top['name']} is using high {kind} "
                   f"({top['value']:.0f}{'%' if kind == 'CPU' else ' MB'})."
                   f" Want me to close it?")
            info = {"pid": top["pid"], "name": top["name"]}
        else:
            msg = f"High {kind} usage detected ({cpu:.0f}% CPU / {ram:.0f}% RAM)."
            info = None
        fn = self.cb.get("on_alert")
        if fn:
            try:
                fn(msg, info)
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    def top_process(self, by="cpu"):
        """Heaviest user-facing process: {'pid','name','value'} or None.
        value is CPU %% or RAM MB depending on `by`."""
        if not self.available:
            return None
        best = None
        try:
            for p in psutil.process_iter(["pid", "name", "cpu_percent",
                                          "memory_info"]):
                try:
                    name = (p.info["name"] or "").lower()
                    if not name or name in NEVER_SUGGEST:
                        continue
                    if by == "cpu":
                        val = p.info["cpu_percent"] or 0.0
                    else:
                        mem = p.info["memory_info"]
                        val = (mem.rss / (1024 * 1024)) if mem else 0.0
                    if best is None or val > best["value"]:
                        best = {"pid": p.info["pid"],
                                "name": p.info["name"], "value": val}
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            return None
        return best

    def active_window_title(self):
        """Title of the focused window (Windows only), else None."""
        if not IS_WINDOWS:
            return None
        try:
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            return buf.value or None
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    def explain(self):
        """Short human answer to 'why is my laptop slow?' for the HUD."""
        if not self.available:
            return "Can't check — psutil is not installed."
        parts = []
        try:
            cpu = psutil.cpu_percent(interval=0.3)
            ram = psutil.virtual_memory().percent
            top_cpu = self.top_process("cpu")
            top_ram = self.top_process("ram")
            if top_cpu and top_cpu["value"] > 5:
                parts.append(f"{top_cpu['name']} is using CPU "
                             f"({top_cpu['value']:.0f}%)")
            if top_ram and (not top_cpu or
                            top_ram["name"] != top_cpu["name"]):
                parts.append(f"{top_ram['name']} is using "
                             f"{top_ram['value']:.0f} MB of memory")
            batt = None
            try:
                batt = psutil.sensors_battery()
            except Exception:
                pass
            if batt is not None and not batt.power_plugged and \
                    batt.percent < 25:
                parts.append(f"battery is low ({batt.percent:.0f}%), "
                             "Windows may be throttling")
            summary = (f"CPU {cpu:.0f}%, RAM {ram:.0f}%. " +
                       ("; ".join(parts) + ". " if parts else ""))
            if ram >= 85:
                summary += "Suggested: close unused apps or browser tabs."
            elif cpu >= 70:
                summary += "Suggested: close the heavy app or let it finish."
            else:
                summary += "Nothing looks stuck — a restart also helps."
            return summary
        except Exception as exc:
            return f"Couldn't inspect the system: {exc}"

    # ------------------------------------------------------------------ #
    # Closing a process — every step gated by the caller's confirmations.
    # ------------------------------------------------------------------ #
    def needs_unsaved_warning(self, name):
        n = (name or "").lower()
        return any(risk in n for risk in UNSAVED_RISK)

    def close_process(self, pid, force=False):
        """
        Close a process. Graceful terminate() unless force=True.
        Returns (ok, message). The CALLER is responsible for having
        asked the user (and the unsaved-work double-check) first.
        """
        if not self.available:
            return False, "psutil missing"
        try:
            p = psutil.Process(pid)
            name = p.name()
            if force:
                p.kill()
                return True, f"Force-closed {name}"
            p.terminate()
            try:
                p.wait(timeout=3)
                return True, f"Closed {name} ✓"
            except psutil.TimeoutExpired:
                return False, (f"{name} didn't close gracefully — "
                               "say 'force close' to force it")
        except psutil.NoSuchProcess:
            return True, "It already closed ✓"
        except psutil.AccessDenied:
            return False, "Windows denied access (try running AIR as admin)"
        except Exception as exc:
            return False, f"Couldn't close it: {exc}"
