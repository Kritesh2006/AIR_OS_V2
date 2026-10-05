"""
contracts.py — Shared data contracts for AIR OS (frozen, see docs/ARCHITECTURE.md).

Every module that crosses a thread or ownership boundary talks in these
types. Changing anything here is a contract change: edit
docs/ARCHITECTURE.md in the same commit and get it reviewed.

Pure Python, no third-party imports, so it loads (and is testable) on
any platform.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Optional, Protocol

Point = tuple[float, float]
Rect = tuple[int, int, int, int]   # x, y, w, h in overlay-local PHYSICAL px


# ------------------------------------------------------------------ #
# Sensor data (SensorWorker only — never crosses into Tk)
# ------------------------------------------------------------------ #
@dataclass(frozen=True)
class HandObs:
    # 21 normalized points from the mirrored frame. The current tracker
    # yields (x, y); a z component may be appended later.
    landmarks: tuple[tuple[float, ...], ...]
    handedness: str                 # "Left" | "Right" | "Unknown"


@dataclass(frozen=True)
class FaceObs:
    present: bool
    blink_left: float = 0.0         # blendshape eyeBlinkLeft 0..1
    blink_right: float = 0.0
    ear: Optional[float] = None     # optional eye-aspect-ratio cross-check


@dataclass(frozen=True)
class FrameResult:
    seq: int                        # camera sequence number
    ts_ms: int                      # monotonic capture time; the ONLY timestamp for this frame
    frame_bgr: Any                  # np.ndarray, mirrored; SensorWorker-only
    hands: tuple[HandObs, ...]
    face: Optional[FaceObs]         # None = face model not run this frame


# ------------------------------------------------------------------ #
# Actions
# ------------------------------------------------------------------ #
@dataclass(frozen=True)
class Target:
    id: str                         # stable within one session, e.g. f"{hwnd}:{pid}"
    label: str                      # "Chrome"
    sublabel: str                   # window title
    icon_ref: Optional[str]         # exe path; the Tk side resolves + caches icons
    minimized: bool
    available: bool                 # V1: unavailable targets are omitted; flag kept for later
    payload: Mapping[str, Any]      # build with types.MappingProxyType(...); never mutate


class ActionStatus(Enum):
    SENT = "SENT"
    CLOSED = "CLOSED"
    STILL_OPEN = "STILL_OPEN"
    FAILED = "FAILED"
    GONE_BEFORE = "GONE_BEFORE"


@dataclass(frozen=True)
class ActionResult:
    status: ActionStatus
    detail: str                     # longer text for the Control Panel log


@dataclass(frozen=True)
class BlinkEvent:
    start_ts: int                   # ms, same clock as FrameResult.ts_ms
    duration_ms: int
    peak_confidence: float


class ActionProvider(Protocol):
    id: str
    risk: str                       # "high" for close

    def list_targets(self) -> list[Target]:
        """SensorWorker thread; budget about 100 ms."""
        ...

    def execute(self, target: Target) -> ActionResult:
        """Non-blocking (PostMessageW). Revalidates hwnd+pid+title first."""
        ...

    def still_exists(self, target: Target) -> bool:
        """Cheap check used while VERIFYING: hwnd + pid identity only."""
        ...


# ------------------------------------------------------------------ #
# State machine enums
# ------------------------------------------------------------------ #
class Mode(Enum):
    NORMAL = 1
    CLOSE_SELECTION = 2
    WAIT_FOR_RELEASE = 3


class SessionState(Enum):
    IDLE = 1
    ARMING = 2
    SELECTING = 3
    LOCKED = 4
    EXECUTING = 5
    VERIFYING = 6
    COOLDOWN = 7


class FaceState(Enum):
    UNKNOWN = 1
    OPEN = 2
    CLOSING = 3
    CLOSED = 4


class PodStatus(Enum):
    READY = "READY"
    PAUSED = "PAUSED"
    ARMING = "CLOSE?"
    SELECT = "SELECT"
    BLINK = "BLINK"
    CLOSING = "CLOSING…"
    CLOSED = "CLOSED"
    STILL_OPEN = "STILL OPEN"
    CANCELLED = "CANCELLED"


# ------------------------------------------------------------------ #
# Snapshots (SensorWorker → Tk through LatestState)
# ------------------------------------------------------------------ #
@dataclass(frozen=True)
class InteractionSnapshot:
    mode: Mode
    state: SessionState
    pod_status: PodStatus
    arm_progress: float             # 0..1
    cursor: Optional[Point]         # overlay-local px; None outside selection
    hovered_id: Optional[str]
    locked_id: Optional[str]
    dwell_progress: float           # 0..1
    face_state: FaceState
    blink_progress: float           # 0..1 toward blink_min_ms
    hand_present: bool

    @classmethod
    def idle(cls, pod_status: PodStatus = PodStatus.READY,
             hand_present: bool = False) -> "InteractionSnapshot":
        """Snapshot for NORMAL mode with no session running."""
        return cls(mode=Mode.NORMAL, state=SessionState.IDLE,
                   pod_status=pod_status, arm_progress=0.0, cursor=None,
                   hovered_id=None, locked_id=None, dwell_progress=0.0,
                   face_state=FaceState.UNKNOWN, blink_progress=0.0,
                   hand_present=hand_present)


@dataclass(frozen=True)
class UiSnapshot:
    seq: int                        # increases with every publish
    fps: float
    gesture_label: str
    # Small downscaled RGB np.ndarray, or None when the preview is off.
    # A fresh buffer per publish; immutable once published.
    preview_rgb: Optional[Any]
    interaction: InteractionSnapshot
