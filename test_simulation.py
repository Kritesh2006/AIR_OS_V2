"""
test_simulation.py — Automated checks for AIR OS V01 (no hardware needed).

Feeds synthetic hand landmarks into the GestureEngine and text into
the VoiceEngine parser, using mock controllers that record calls.
Run:  python test_simulation.py
"""

import math
import time

from gesture_engine import GestureEngine
from voice_engine import VoiceEngine
from utils import CircleDetector, SwipeDetector, FPSCounter, Smoother


# ------------------------- mock controllers --------------------------- #
class Recorder:
    def __init__(self):
        self.calls = []

    def _rec(self, name):
        def fn(*a, **k):
            self.calls.append((name, a, k))
        return fn


class MockMouse(Recorder):
    def __init__(self):
        super().__init__()
        for m in ("begin_move", "move", "end_move", "left_click",
                  "double_click", "right_click", "scroll"):
            setattr(self, m, self._rec(m))


class MockKeyboard(Recorder):
    def __init__(self):
        super().__init__()
        self.modifiers = {"shift": False, "ctrl": False, "alt": False}
        for m in ("press_key", "hotkey", "type_text", "toggle_modifier"):
            setattr(self, m, self._rec(m))


class MockSystem(Recorder):
    def __init__(self):
        super().__init__()
        for m in ("volume_step", "set_volume", "mute", "open_app",
                  "open_url", "search_youtube", "search_google",
                  "close_active_window", "show_desktop", "task_view",
                  "browser_back", "browser_forward", "play_pause_media",
                  "lock_pc", "shutdown", "restart"):
            setattr(self, m, self._rec(m))
        for m in ("open_in_browser", "open_terminal", "compose_gmail"):
            setattr(self, m, self._rec(m))
        self.screenshot = lambda: (self.calls.append(("screenshot", (), {}))
                                   or "/tmp/x.png")
        self.battery_status = lambda: "Battery is at 88% (charging)"
        self.browsers = ["chrome", "edge", "default"]
        self.available_browsers = lambda: self.browsers

    def called(self, name):
        return any(c[0] == name for c in self.calls)


# ---------------------- synthetic hand builders ----------------------- #
def make_hand(extended, base=(0.5, 0.6), pinch=False):
    """
    Build a fake 21-landmark hand. `extended` = set of finger names.
    Geometry: wrist at base; extended fingertips far from wrist,
    curled fingertips close to it. Distances chosen to satisfy the
    finger_extended / thumb_extended heuristics.
    """
    lm = [base] * 21
    lm = list(lm)
    bx, by = base
    lm[0] = (bx, by)                       # wrist
    lm[17] = (bx + 0.10, by - 0.02)        # pinky base (thumb reference)

    fingers = {
        "thumb":  (4, 3, (bx - 0.14, by - 0.06), (bx - 0.06, by - 0.03)),
        "index":  (8, 6, (bx - 0.05, by - 0.28), (bx - 0.05, by - 0.14)),
        "middle": (12, 10, (bx, by - 0.30), (bx, by - 0.15)),
        "ring":   (16, 14, (bx + 0.05, by - 0.28), (bx + 0.05, by - 0.14)),
        "pinky":  (20, 18, (bx + 0.10, by - 0.24), (bx + 0.10, by - 0.12)),
    }
    for name, (tip, pip, ext_tip, pip_pos) in fingers.items():
        lm[pip] = pip_pos
        if name in extended:
            lm[tip] = ext_tip
        else:
            # curled: tip pulled back near the wrist, inside the pip radius
            lm[tip] = (bx + (pip_pos[0] - bx) * 0.4,
                       by + (pip_pos[1] - by) * 0.4)
    if pinch:
        # Thumb tip and index tip touching, away from the palm.
        lm[4] = (bx - 0.02, by - 0.20)
        lm[8] = (bx - 0.015, by - 0.20)
    return lm


def move_hand(lm, dx, dy):
    return [(x + dx, y + dy) for (x, y) in lm]


# ------------------------------ tests --------------------------------- #
PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(("  PASS " if cond else "  FAIL ") + name)


def new_engine():
    mouse, kb, sysm = MockMouse(), MockKeyboard(), MockSystem()
    events = {"kb_toggles": 0, "overlay_closed": 0, "paused": []}
    eng = GestureEngine(mouse, kb, sysm, callbacks={
        "toggle_keyboard": lambda: events.__setitem__(
            "kb_toggles", events["kb_toggles"] + 1),
        "close_overlay": lambda: events.__setitem__(
            "overlay_closed", events["overlay_closed"] + 1),
        "set_paused": lambda p: events["paused"].append(p),
    })
    return eng, mouse, kb, sysm, events


print("== Gesture engine ==")

# 1. Pinch => mouse move mode
eng, mouse, kb, sysm, ev = new_engine()
hand = make_hand({"index"}, pinch=True)
for i in range(10):
    eng.process(move_hand(hand, i * 0.01, 0))
check("pinch enters mouse mode", any(c[0] == "begin_move" for c in mouse.calls))
check("pinch drives cursor movement", any(c[0] == "move" for c in mouse.calls))
eng.process(make_hand({"index", "middle", "ring", "pinky", "thumb"}))
# (palm frame) then no hand:
eng.process(None)
check("pinch release ends mouse mode", any(c[0] == "end_move" for c in mouse.calls))

# 2. Pinch + middle tap = left click; ring = double; pinky = right
for finger, call in (("middle", "left_click"), ("ring", "double_click"),
                     ("pinky", "right_click")):
    eng, mouse, kb, sysm, ev = new_engine()
    ext = {"index", "middle", "ring", "pinky"}
    eng.process(make_hand(ext, pinch=True))            # finger extended
    eng.process(make_hand(ext - {finger}, pinch=True)) # finger curls = tap
    check(f"pinch + {finger} tap => {call}", any(c[0] == call for c in mouse.calls))

# 3. Index circles => volume
eng, mouse, kb, sysm, ev = new_engine()
for step in range(80):  # clockwise circle of the index tip
    a = step * 0.25
    hand = make_hand({"index"})
    hand[8] = (0.5 + 0.08 * math.cos(a), 0.35 + 0.08 * math.sin(a))
    eng.process(hand)
check("clockwise circle => volume step",
      any(c[0] == "volume_step" and c[2].get("up") is True or
          (c[0] == "volume_step" and c[1] and c[1][0] is True)
          for c in sysm.calls) or
      any(c[0] == "volume_step" and c[2].get("up", True) for c in sysm.calls))

eng, mouse, kb, sysm, ev = new_engine()
for step in range(80):  # anti-clockwise
    a = -step * 0.25
    hand = make_hand({"index"})
    hand[8] = (0.5 + 0.08 * math.cos(a), 0.35 + 0.08 * math.sin(a))
    eng.process(hand)
down_calls = [c for c in sysm.calls if c[0] == "volume_step"]
check("anti-clockwise circle => volume down",
      any(c[2].get("up") is False for c in down_calls))

# 4. Fist held 1s => close window; quick fist => close overlay
eng, mouse, kb, sysm, ev = new_engine()
fist = make_hand(set())
eng.process(fist)
time.sleep(1.05)
eng.process(fist)
check("fist held 1s => close active window", sysm.called("close_active_window"))

eng, mouse, kb, sysm, ev = new_engine()
eng.process(make_hand(set()))                      # quick fist...
eng.process(make_hand({"index"}))                  # ...released fast
check("quick fist => close overlay", ev["overlay_closed"] == 1)

# 5. Open palm held still => pause, again => resume
eng, mouse, kb, sysm, ev = new_engine()
palm = make_hand({"thumb", "index", "middle", "ring", "pinky"})
eng.process(palm)
time.sleep(0.7)
eng.process(palm)
check("open palm => pause", ev["paused"] == [True] and eng.paused)
eng.process(palm)  # STILL holding palm — latch must block re-toggle
check("held palm toggles only once (latch)", ev["paused"] == [True])
time.sleep(1.6)  # wait out the palm cooldown
eng.process(make_hand({"index"}))  # palm leaves => latch releases
eng.process(palm)
time.sleep(0.7)
eng.process(palm)
check("palm shown again => resume", ev["paused"] == [True, False] and not eng.paused)

# 6. Paused = other gestures ignored
eng, mouse, kb, sysm, ev = new_engine()
eng.paused = True
eng.process(make_hand({"index", "middle"}))  # peace sign while paused
check("paused blocks other gestures", ev["kb_toggles"] == 0)

# 7. Peace sign => virtual keyboard (once per appearance)
eng, mouse, kb, sysm, ev = new_engine()
eng.process(make_hand({"index", "middle"}))
check("peace sign => toggle keyboard", ev["kb_toggles"] == 1)
time.sleep(1.1)  # cooldown expires, but pose is still held...
eng.process(make_hand({"index", "middle"}))
check("held peace sign fires only once (latch)", ev["kb_toggles"] == 1)
eng.process(make_hand({"index"}))      # pose changes => latch releases
time.sleep(1.1)
eng.process(make_hand({"index", "middle"}))
check("peace sign again => fires again", ev["kb_toggles"] == 2)

# 8. Four fingers => screenshot
eng, mouse, kb, sysm, ev = new_engine()
eng.process(make_hand({"index", "middle", "ring", "pinky"}))
check("four fingers => screenshot", sysm.called("screenshot"))

# 9. Thumbs up => play/pause
eng, mouse, kb, sysm, ev = new_engine()
eng.process(make_hand({"thumb"}))
check("thumbs up => play/pause media", sysm.called("play_pause_media"))

# 10. Swipes
for (dx, dy, expect) in ((0.5, 0, "browser_forward"), (-0.5, 0, "browser_back"),
                         (0, 0.5, "show_desktop"), (0, -0.5, "task_view")):
    eng, mouse, kb, sysm, ev = new_engine()
    hand = make_hand({"index"}, base=(0.5, 0.5))
    for i in range(8):
        eng.process(move_hand(hand, dx * i / 7, dy * i / 7))
    check(f"swipe ({dx},{dy}) => {expect}", sysm.called(expect))

# 11. No hand => everything released, gesture 'none'
eng, mouse, kb, sysm, ev = new_engine()
eng.process(make_hand({"index"}, pinch=True))
eng.process(None)
check("hand lost => releases + gesture none",
      eng.current_gesture == "none")


print("\n== Voice command parser ==")
sysm = MockSystem()
confirms = []
speaks = []
ve = VoiceEngine(sysm, callbacks={
    "request_confirmation": lambda label, fn: confirms.append((label, fn)),
    "on_speak": lambda t: speaks.append(t),
})

cases = [
    ("open youtube", "open_app"),
    ("open github", "open_app"),
    ("open chrome", "open_app"),
    ("open vs code", "open_app"),
    ("open downloads", "open_app"),
    ("search youtube for lofi beats", "search_youtube"),
    ("search google for python tutorials", "search_google"),
    ("volume 50", "set_volume"),
    ("mute", "mute"),
    ("unmute", "mute"),
    ("close current app", "close_active_window"),
    ("lock pc", "lock_pc"),
]
for phrase, expect in cases:
    sysm.calls.clear()
    ve.handle_command(phrase)
    check(f'voice "{phrase}" => {expect}', sysm.called(expect))

# volume 50 must pass the right number
sysm.calls.clear()
ve.handle_command("volume 50")
vol = [c for c in sysm.calls if c[0] == "set_volume"]
check("volume 50 passes value 50", vol and vol[0][1][0] == 50)

# unmute must call mute(False)
sysm.calls.clear()
ve.handle_command("unmute")
mm = [c for c in sysm.calls if c[0] == "mute"]
check("unmute passes False", mm and mm[0][1][0] is False)

# battery
speaks.clear()
ve.handle_command("what is my battery")
check('voice "what is my battery" => spoken answer',
      speaks and "88%" in speaks[0])

# dangerous commands: must NOT execute, must request confirmation
for phrase, direct in (("shutdown the computer", "shutdown"),
                       ("restart my pc", "restart")):
    sysm.calls.clear()
    confirms.clear()
    ve.handle_command(phrase)
    check(f'"{phrase}" requires confirmation',
          len(confirms) == 1 and not sysm.called(direct))
    # Confirming actually runs it:
    confirms[0][1]()
    check(f'"{phrase}" runs after confirm', sysm.called(direct))

sysm.calls.clear()
ve.handle_command("delete all my files")
check('"delete" is always refused',
      not sysm.calls and any("disabled" in s for s in speaks))

# unknown phrase does nothing
sysm.calls.clear()
check("unknown phrase ignored",
      ve.handle_command("tell me a joke") is None and not sysm.calls)


print("\n== Utility units ==")
cd = CircleDetector(min_radius=0.02)
res = 0
for step in range(60):
    a = step * 0.3
    r = cd.update((0.5 + 0.06 * math.cos(a), 0.5 + 0.06 * math.sin(a)))
    if r:
        res = r
        break
check("CircleDetector detects CW", res == 1)

sd = SwipeDetector(min_dist=0.2)
r = None
for i in range(8):
    r = sd.update((0.1 + i * 0.06, 0.5)) or r
check("SwipeDetector detects right", r == "right")

f = FPSCounter()
for _ in range(5):
    f.tick()
    time.sleep(0.01)
check("FPSCounter > 0", f.fps > 0)

s = Smoother(0.5)
s.update((0, 0))
check("Smoother smooths", s.update((1, 1))[0] == 0.5)



# ====================================================================== #
print("\n== AIR OS V2: wake word + passcode ==")
from settings import settings as _st
_st.set("wake_word_enabled", True)
_st.set("passcode", "2331")

def new_voice():
    sysm = MockSystem()
    huds, actions, answered = [], [], []
    ve = VoiceEngine(sysm, callbacks={
        "on_hud": lambda t, k="info", h=6: huds.append(t),
        "on_action": lambda a: actions.append(a),
        "on_question_answered": lambda k, p, a: answered.append((k, p, a)),
    })
    return ve, sysm, huds, answered

ve, sysm, huds, answered = new_voice()
check("starts sleeping when wake enabled", ve.state == "sleeping")
ve.handle_utterance("open youtube")
check("sleeping ignores commands", not sysm.called("open_app"))
ve.handle_utterance("hey wake up please")
check("wake word => asks passcode",
      ve.state == "awaiting_passcode" and "Passcode?" in huds[-1])
ve.handle_utterance("open youtube")
check("passcode state ignores commands", not sysm.called("open_app"))
ve.handle_utterance("1234")
check("wrong passcode stays locked", ve.state == "awaiting_passcode")
ve.handle_utterance("2331")
check("correct passcode activates", ve.state == "active")
ve.handle_utterance("open youtube")
check("commands work after activation", sysm.called("open_app"))
ve.handle_utterance("stop listening")
check("'stop listening' => sleeping", ve.state == "sleeping")
ve.handle_utterance("wake up"); ve.handle_utterance("two three three one")
check("spoken-word passcode works", ve.state == "active")
ve.handle_utterance("lock air")
check("'lock air' => sleeping", ve.state == "sleeping")
ve.handle_utterance("wake up"); ve.handle_utterance("cancel")
check("cancel during passcode => sleeping", ve.state == "sleeping")

_st.set("wake_word_enabled", False)
ve2, sysm2, _, _ = new_voice()
check("wake disabled => V1 always-active", ve2.state == "active")
ve2.handle_utterance("open youtube")
check("V1 behavior preserved with wake off", sysm2.called("open_app"))
_st.set("wake_word_enabled", True)

print("\n== AIR OS V2: command router ==")
ve, sysm, huds, answered = new_voice()
ve.state = "active"
ve.handle_utterance("open google")
check("open google", sysm.called("open_url"))
ve.handle_utterance("open terminal")
check("open terminal", sysm.called("open_terminal"))
ve.handle_utterance("show me what's new")
check("show me what's new", any(c[0] == "open_url" and "news" in c[1][0]
                                for c in sysm.calls))
hf = []
ve.cb["set_hands_free"] = lambda v: hf.append(v)
ve.handle_utterance("hands free mode")
check("hands free mode => callback ON", hf == [True])
ve.handle_utterance("hands free off")
check("hands free off => callback OFF", hf == [True, False])
ve.cb["explain_system"] = lambda: "Chrome is using high memory. Suggested: close tabs."
huds.clear()
ve.handle_utterance("why is my laptop slow")
check("why is my laptop slow => HUD explanation",
      any("Chrome" in h for h in huds))

print("\n== AIR OS V2: browser choice flow ==")
ve, sysm, huds, answered = new_voice()
ve.state = "active"
ve.handle_utterance("open gmail")
check("open gmail with 2 browsers => question pending",
      ve._pending is not None and ve._pending[0] == "browser_choice"
      and not sysm.called("open_in_browser"))
ve.handle_utterance("chrome please")
check("voice answer resolves question",
      answered and answered[-1][2] == "chrome" and ve._pending is None)
# only one browser => no question
sysm.browsers = ["default"]
ve.handle_utterance("open gmail")
check("single browser => opens directly",
      sysm.called("open_in_browser") and ve._pending is None)

print("\n== AIR OS V2: Gmail compose (no API) ==")
ve, sysm, huds, answered = new_voice()
ve.state = "active"
ve.handle_utterance("send mail to grishma saying i will call you later")
mails = [c for c in sysm.calls if c[0] == "compose_gmail"]
check("send mail finds contact + composes",
      mails and mails[0][1][0] == "grishmadhungel7@gmail.com"
      and "call you later" in mails[0][1][1])
check("compose never auto-sends (only opens draft)",
      not any(c[0] == "send" for c in sysm.calls))
huds.clear()
ve.handle_utterance("send email to nobody saying hello")
check("unknown contact => helpful HUD message",
      any("contacts.json" in h for h in huds)
      and not [c for c in sysm.calls if c[0] == "compose_gmail"
               and "nobody" in str(c[1])])

print("\n== AIR OS V2: monitor question flow ==")
ve, sysm, huds, answered = new_voice()
ve.state = "active"
ve.ask_question("close_process", {"pid": 123, "name": "chrome.exe"},
                "Chrome is using high memory. Close it?", ["Yes", "No"])
ve.handle_utterance("yes close it")
check("voice 'yes' answers close question",
      answered and answered[-1] == ("close_process",
                                    {"pid": 123, "name": "chrome.exe"},
                                    "yes"))
ve.ask_question("close_process", {"pid": 5, "name": "x"}, "Close?",
                ["Yes", "No"])
ve.handle_utterance("no leave it")
check("voice 'no' answers close question", answered[-1][2] == "no")

print("\n== AIR OS V2: new gestures ==")
# pinky up => toggle AIR HUD
eng, mouse, kb, sysm, ev = new_engine()
hud_toggles = []
eng.cb["toggle_air_hud"] = lambda: hud_toggles.append(1)
eng.process(make_hand({"pinky"}))
check("pinky up => toggle AIR HUD", len(hud_toggles) == 1)
eng.process(make_hand({"pinky"}))
check("held pinky fires once (latch)", len(hud_toggles) == 1)

# three-finger pinch click (opt-in)
_st.set("three_finger_pinch_click", True)
eng, mouse, kb, sysm, ev = new_engine()
h = make_hand({"index"}, pinch=True)
h[12] = (h[4][0] + 0.01, h[4][1])   # middle tip joins the pinch
eng.process(h)
check("3-finger pinch click (enabled)", any(c[0] == "left_click"
                                            for c in mouse.calls))
_st.set("three_finger_pinch_click", False)
eng, mouse, kb, sysm, ev = new_engine()
eng.process(h)
check("3-finger pinch OFF by default", not any(c[0] == "left_click"
                                               for c in mouse.calls))

# two-hand gestures (opt-in)
_st.set("two_hand_gestures", True)
eng, mouse, kb, sysm, ev = new_engine()
lfist = make_hand(set(), base=(0.3, 0.6))
rindex = make_hand({"index"}, base=(0.7, 0.6))
eng.process_multi([(lfist, "Left"), (rindex, "Right")])   # anchor
r2 = make_hand({"index"}, base=(0.7, 0.6))
r2[8] = (r2[8][0], r2[8][1] - 0.10)                        # index rises
eng.process_multi([(lfist, "Left"), (r2, "Right")])
check("left fist + right index => scroll", any(c[0] == "scroll"
                                               for c in mouse.calls))
eng, mouse, kb, sysm, ev = new_engine()
rpalm = make_hand({"thumb","index","middle","ring","pinky"}, base=(0.5,0.5))
for i in range(8):
    eng.process_multi([(lfist, "Left"),
                       (move_hand(rpalm, i*0.07, 0), "Right")])
check("left fist + right palm wave => alt+tab",
      any(c[0] == "hotkey" and c[1] == ("alt","tab") for c in kb.calls))
_st.set("two_hand_gestures", False)
eng, mouse, kb, sysm, ev = new_engine()
eng.process_multi([(lfist, "Left"), (rindex, "Right")])
check("two-hand OFF by default => single-hand path",
      not any(c[0] == "scroll" for c in mouse.calls))

print("\n== AIR OS V2: system monitor ==")
from system_monitor import SystemMonitor
mon = SystemMonitor()
if mon.available:
    txt = mon.explain()
    check("explain() returns readable summary",
          isinstance(txt, str) and "CPU" in txt and "Suggested" in txt
          or "restart" in txt)
    top = mon.top_process("ram")
    check("top_process finds a process", top is None or
          ("pid" in top and "name" in top))
    check("unsaved-work heuristic", mon.needs_unsaved_warning("chrome.exe")
          and not mon.needs_unsaved_warning("calc.exe"))
else:
    check("monitor degrades readably", mon.error is not None)

print(f"\n===== RESULT: {len(PASS)} passed, {len(FAIL)} failed =====")
if FAIL:
    print("Failed:", *FAIL, sep="\n  - ")
    raise SystemExit(1)
