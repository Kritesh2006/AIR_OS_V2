"""
channels.py — The only ways AIR OS threads talk to each other.

  LatestState   SensorWorker → Tk   newest UiSnapshot only (older ones dropped)
  EventQueue    any thread  → Tk    FIFO UiEvents, never dropped
  CommandQueue  any thread  → SensorWorker   FIFO Commands, never dropped

Rules (frozen, see docs/ARCHITECTURE.md):
  * Only the Tk main thread touches Tk widgets.
  * Only the SensorWorker mutates interaction state.
  * Event/command kinds are the constants below — never ad-hoc strings.
  * EventKind.UI_CALL is a migration bridge for legacy callbacks only.
    New features must use explicit events.
"""

from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Optional

from contracts import UiSnapshot


class EventKind:
    """UiEvent kinds (worker / voice / monitor → Tk)."""
    OVERLAY_SHOW = "OVERLAY_SHOW"      # {targets: list[Target], rects: dict[id, Rect]}
    OVERLAY_HIDE = "OVERLAY_HIDE"      # {reason: "done"|"cancel"|"timeout"|"hand_lost"}
    ACTION_RESULT = "ACTION_RESULT"    # {result: ActionResult, target: Target}
    STATUS = "STATUS"                  # {key, text, good}
    ERROR = "ERROR"                    # {text}
    LOG = "LOG"                        # {text}
    POD_SAY = "POD_SAY"                # {text, kind, hold_s}
    MODE_CHANGED = "MODE_CHANGED"      # {mode: Mode}
    UI_CALL = "UI_CALL"                # {fn} — legacy bridge only
    WORKER_STOPPED = "WORKER_STOPPED"  # {}


class CommandKind:
    """Command kinds (Tk / keyboard hook / voice → SensorWorker)."""
    KEY_CANCEL = "KEY_CANCEL"                        # {}
    KEY_CONFIRM = "KEY_CONFIRM"                      # {} (Phase 2 debug only)
    SET_PREVIEW_ENABLED = "SET_PREVIEW_ENABLED"      # {on: bool}
    SET_LEGACY_POPUP_OPEN = "SET_LEGACY_POPUP_OPEN"  # {open: bool}
    SET_GESTURES_PAUSED = "SET_GESTURES_PAUSED"      # {paused: bool}
    SHUTDOWN = "SHUTDOWN"                            # {}


@dataclass(frozen=True)
class UiEvent:
    kind: str
    data: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Command:
    kind: str
    data: dict = field(default_factory=dict)


class LatestState:
    """Single-slot mailbox. The writer replaces, the reader takes the
    newest. The lock only guards the reference swap."""

    def __init__(self):
        self._lock = threading.Lock()
        self._value: Optional[UiSnapshot] = None

    def publish(self, snap: UiSnapshot) -> None:
        with self._lock:
            self._value = snap

    def read(self) -> Optional[UiSnapshot]:
        with self._lock:
            return self._value


class _FifoQueue:
    def __init__(self):
        self._q = queue.SimpleQueue()

    def put(self, item) -> None:
        self._q.put(item)

    def drain(self, max_n: Optional[int] = None) -> list:
        """Return queued items in order without blocking."""
        out = []
        while max_n is None or len(out) < max_n:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                break
        return out


class EventQueue(_FifoQueue):
    """UiEvents for the Tk main thread."""

    def put(self, ev: UiEvent) -> None:
        super().put(ev)

    def emit(self, kind: str, **data) -> None:
        self.put(UiEvent(kind, data))


class CommandQueue(_FifoQueue):
    """Commands for the SensorWorker."""

    def put(self, cmd: Command) -> None:
        super().put(cmd)

    def send(self, kind: str, **data) -> None:
        self.put(Command(kind, data))
