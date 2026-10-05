"""
test_foundation.py — Phase 1 checks (no hardware, no Tk, no OpenCV).

Covers the shared contracts, the thread channels, the camera's frame
sequence/timestamp, and the SensorWorker driving the real GestureEngine
through fake camera/tracker objects.
Run:  python test_foundation.py
"""

import dataclasses
import threading
import time
import types

import channels as ch
import contracts as c
from camera import CameraManager
from gesture_engine import GestureEngine
from sensor_worker import PassthroughRouter, SensorWorker

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name)


def wait_until(cond, timeout=2.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return cond()


# ------------------------------ fakes --------------------------------- #
class Rec:
    """Records every method call; any attribute is a callable."""

    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: self.calls.append(name)


class FakeFrame:
    def __init__(self, n):
        self.n = n

    def copy(self):
        return FakeFrame(self.n)


class FakeCamera:
    def __init__(self):
        self.available = True
        self.error = None
        self.stopped = False
        self._lock = threading.Lock()
        self._frame = None
        self._seq = 0
        self._ts = 0

    def push(self, ts_ms):
        with self._lock:
            self._seq += 1
            self._ts = ts_ms
            self._frame = FakeFrame(self._seq)

    def read_latest(self):
        with self._lock:
            if self._frame is None:
                return False, None, 0, self._seq
            return True, self._frame.copy(), self._ts, self._seq

    def stop(self):
        self.stopped = True


FIST = [(0.5, 0.6)] * 21   # every fingertip at the wrist => fist


class FakeTracker:
    def __init__(self):
        self.calls = []          # (frame.n, draw, ts_ms)
        self.last_hands = []
        self.hand = None
        self.error = None
        self.closed = False

    def process(self, frame, draw=True, ts_ms=None):
        self.calls.append((frame.n, draw, ts_ms))
        self.last_hands = [(self.hand, "Right")] if self.hand else []
        return (self.hand, frame)

    def close(self):
        self.closed = True


def new_worker():
    events, commands, state = ch.EventQueue(), ch.CommandQueue(), \
        ch.LatestState()
    engine = GestureEngine(Rec(), Rec(), Rec())
    router = PassthroughRouter(engine, events)
    cam, trk = FakeCamera(), FakeTracker()
    w = SensorWorker(cam, trk, router, state, events, commands,
                     error_sources=(trk,))
    return w, cam, trk, engine, state, events, commands


# ------------------------------ tests --------------------------------- #
print("== contracts ==")
snap = c.InteractionSnapshot.idle()
try:
    snap.mode = c.Mode.CLOSE_SELECTION
    check("snapshots are frozen", False)
except dataclasses.FrozenInstanceError:
    check("snapshots are frozen", True)
check("idle snapshot is NORMAL/IDLE/READY",
      snap.mode is c.Mode.NORMAL and snap.state is c.SessionState.IDLE
      and snap.pod_status is c.PodStatus.READY)
t = c.Target("1:2", "Chrome", "Tab", None, False, True,
             types.MappingProxyType({"hwnd": 1, "pid": 2}))
try:
    t.payload["hwnd"] = 9
    check("Target payload is read-only", False)
except TypeError:
    check("Target payload is read-only", True)
check("ActionStatus is typed", c.ActionResult(
    c.ActionStatus.STILL_OPEN, "x").status.value == "STILL_OPEN")
check("Pod labels match the UX contract",
      [p.value for p in (c.PodStatus.ARMING, c.PodStatus.CLOSING,
                         c.PodStatus.STILL_OPEN)]
      == ["CLOSE?", "CLOSING…", "STILL OPEN"])

print("\n== channels ==")
ls = ch.LatestState()
check("LatestState starts empty", ls.read() is None)
s1 = c.UiSnapshot(1, 0.0, "none", None, snap)
s2 = c.UiSnapshot(2, 0.0, "none", None, snap)
ls.publish(s1)
ls.publish(s2)
check("LatestState keeps only the newest", ls.read() is s2)
eq = ch.EventQueue()
for i in range(5):
    eq.emit(ch.EventKind.LOG, text=str(i))
first = eq.drain(max_n=3)
check("EventQueue is FIFO and honours max_n",
      [e.data["text"] for e in first] == ["0", "1", "2"])
check("EventQueue keeps the rest", len(eq.drain()) == 2 and eq.drain() == [])
cq = ch.CommandQueue()
cq.send(ch.CommandKind.SET_GESTURES_PAUSED, paused=True)
cmds = cq.drain()
check("CommandQueue carries typed commands",
      cmds[0].kind == "SET_GESTURES_PAUSED" and cmds[0].data["paused"])

print("\n== camera ==")
cam = CameraManager()
ok, frame, ts, seq = cam.read_latest()
check("read_latest without frames => not ok", not ok and frame is None)
cam._frame, cam._ts_ms, cam._seq = FakeFrame(7), 1234, 7
ok, frame, ts, seq = cam.read_latest()
check("read_latest returns copy + ts + seq",
      ok and frame is not cam._frame and ts == 1234 and seq == 7)
check("legacy read() still works", cam.read()[0] is True)

print("\n== sensor worker ==")
w, cam, trk, engine, state, events, commands = new_worker()
w.start()
check("publishes a snapshot with no frames yet",
      wait_until(lambda: state.read() is not None))

cam.push(1000)
check("processes a new frame", wait_until(lambda: len(trk.calls) == 1))
time.sleep(0.05)
check("never re-processes the same frame", len(trk.calls) == 1)
check("tracker gets the capture timestamp", trk.calls[0][2] == 1000)

trk.hand = FIST
cam.push(1033)
check("gesture engine runs on the worker",
      wait_until(lambda: state.read().gesture_label == "fist"))
check("snapshot says a hand is present",
      state.read().interaction.hand_present)

commands.send(ch.CommandKind.SET_GESTURES_PAUSED, paused=True)
check("pause command reaches the engine",
      wait_until(lambda: engine.paused))
ev = events.drain()
check("pause emits a STATUS event",
      any(e.kind == ch.EventKind.STATUS and e.data["text"] == "PAUSED"
          for e in ev))
check("snapshot shows PAUSED", wait_until(
    lambda: state.read().interaction.pod_status is c.PodStatus.PAUSED))

commands.send(ch.CommandKind.SET_PREVIEW_ENABLED, on=False)
time.sleep(0.03)
cam.push(1066)
check("preview off => no skeleton drawing",
      wait_until(lambda: len(trk.calls) == 3) and trk.calls[-1][1] is False)

trk.error = "Hand tracking error: boom"
check("subsystem errors become ERROR events", wait_until(
    lambda: any(e.kind == ch.EventKind.ERROR for e in events.drain())))
check("error is cleared after reporting", trk.error is None)

cam.available, cam.error = False, "Camera stopped responding"
time.sleep(0.15)
evs = events.drain()
check("camera loss reported once",
      sum(e.kind == ch.EventKind.ERROR for e in evs) == 1
      and cam.error is None)

w.stop()
check("SHUTDOWN stops the thread", wait_until(lambda: not w.is_alive()))
check("WORKER_STOPPED is emitted",
      any(e.kind == ch.EventKind.WORKER_STOPPED for e in events.drain()))
check("worker releases camera and tracker", cam.stopped and trk.closed)

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("Failed:", *FAIL, sep="\n  - ")
    raise SystemExit(1)
