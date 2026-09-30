# AIR OS V2

**An intelligent hands-free overlay for Windows — gestures, voice, and a calm mini HUD.**

**New in V2:** a small always-on-top AIR HUD in the top-left corner (AIR's
main way of talking to you), wake word + passcode security, more voice
commands, Gmail compose by voice with **no API and no OAuth**, a system
resource monitor that politely offers to close heavy apps (never
automatically), an "explain mode" for "why is my laptop slow?", and a
single gesture-sensitivity knob. Everything from V1 still works exactly
as before.
AIR OS turns your webcam into a gesture controller and your microphone
into an always-on voice command layer. No Start button — everything
turns on automatically when the app launches. If the camera or mic is
missing, the app keeps running in *limited mode* and tells you why.

---

## 1. Requirements

- Windows 10 or 11
- Python **3.12+** — download from https://python.org
  (during install, tick **"Add Python to PATH"**)
- A webcam and a microphone (the app still opens without them)
- Internet connection (voice recognition uses Google's free service)

## 2. Install

Open **Command Prompt** in the AIR OS folder and run:

```
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

> If `PyAudio` fails to install, run: `pip install pipwin` then
> `pipwin install pyaudio`, or grab a wheel from
> https://pypi.org/project/PyAudio/#files and `pip install <file>.whl`.

## 3. Run

```
venv\Scripts\activate
python main.py
```

That's it. The window opens, the camera preview appears **top-left**
with your hand skeleton drawn on it, and the HUD on the right shows:
Camera / Mic / Gesture / Voice status, FPS, current gesture, last
action, and any errors along the bottom.

> **Tip:** run the terminal **as Administrator** if keyboard shortcuts
> (Alt+F4, Win+D…) don't fire — the `keyboard` library sometimes needs it.

To verify the logic without any hardware:

```
python test_simulation.py
```

## 4. Gesture guide

| Gesture | Action |
|---|---|
| ☝ Index finger, draw **clockwise circle** | Volume up |
| ☝ Index finger, draw **anti-clockwise circle** | Volume down |
| 🤏 Pinch (thumb + index) and move hand | Move the mouse cursor |
| 🤏 Pinch + **tap middle finger** | Left click |
| 🤏 Pinch + **tap ring finger** | Double click |
| 🤏 Pinch + **tap pinky** | Right click |
| ✊ Quick fist | Close the confirmation popup |
| ✊ Hold fist **1 second** | Close the active window (Alt+F4) |
| 🖐 Open palm, hold still ~0.6 s | Pause / resume gesture tracking |
| ✌ Peace sign | Open / close the virtual keyboard |
| 🖖 Four fingers (thumb tucked) | Screenshot → saved to Pictures |
| 👍 Thumbs up | Play / pause media |
| 👋 Fast swipe **left / right** | Browser back / forward |
| 👋 Fast swipe **down / up** | Show desktop / Task view |

**How clicking works:** pinch to grab the cursor, move your hand to
move it, then tap the extra finger (middle/ring/pinky) *while still
pinching* to click. Typing on the virtual keyboard = hover a key with
the cursor, then pinch + middle-finger tap.

## 5. Waking AIR up (V2)

By default AIR launches **asleep** and ignores everything until:

1. You say **"wake up"** — the mini HUD asks **"Passcode?"**
2. You say **"2331"** (or "two three three one") — **AIR activated**

To put it back to sleep say **"sleep"**, **"stop listening"**, or
**"lock air"**. Change the passcode in `airos_settings.json`
(`"passcode"`), and set `"wake_word_enabled": false` to restore the V1
always-listening behavior.

Privacy note: while asleep AIR still has to *hear* you to catch the
wake word, so audio is still transcribed — it just isn't acted on.

## 6. Voice commands

Once AIR is awake:

- "open YouTube" · "open GitHub" · "open Google" · "open Chrome"
- "open VS Code" · "open Downloads" · "open terminal" · "open browser"
- "open Gmail" — the HUD asks **"Which browser? Chrome / Edge / Default"**;
  answer by voice or tap a button (skipped if only one browser exists)
- "send mail to Grishma saying I will call you later" — opens a
  **pre-filled Gmail compose window**. AIR never sends it; you review
  and click Send yourself. Recipients come from `contacts.json`; add
  more entries any time, no code changes or restart needed.
- "search YouTube for lofi beats" · "search Google for python tutorials"
- "show me what's new" (opens Google News)
- "hands free mode" / "hands free off" (gesture tracking on/off)
- "why is my laptop slow?" — short HUD explanation with a suggestion
- "volume 50" · "mute" · "unmute"
- "close current app" · "lock PC" · "what is my battery"

## 6b. The AIR HUD (V2)

The small strip in the top-left corner is AIR's voice: Listening...,
Opening Gmail..., Done, Wrong passcode, resource warnings, and choice
questions with tappable buttons. Drag it anywhere. Hide it with the
minus button or the **pinky-up gesture** (only the pinky extended);
bring it back with the same gesture or the **AIR HUD** button in the
main window. It never blocks and never steals focus.

## 6c. Resource monitor (V2)

AIR quietly watches CPU, RAM and battery. If usage stays high for about
15 seconds, the HUD calmly asks, e.g. "chrome.exe is using high memory.
Want me to close it?" Safety ladder: nothing closes without your yes;
apps that may hold unsaved work (Office, editors, browsers) get a
**second** confirmation; AIR always tries a graceful close first; a
force-kill happens only if the graceful close fails **and** you
explicitly confirm again. Tune or disable it in settings
(`monitor_enabled`, `cpu_alert_percent`, `ram_alert_percent`,
`monitor_alert_cooldown`).

**Dangerous commands are protected.** Saying "shutdown" or "restart"
opens a confirmation popup — nothing happens until you click
**Confirm** (a quick ✊ fist cancels it). "Delete" commands are always
refused, even with confirmation.

## 7. Settings

Tweak behaviour in `airos_settings.json` (created next to the app after
first run). Highlights: `gesture_sensitivity` (one knob — above 1.0 all
gestures trigger more easily, below 1.0 stricter), `mouse_smoothing`,
`mouse_speed`, `scroll_speed`, `volume_step`, `wake_word_enabled`,
`passcode`, plus all monitor thresholds. Defaults live in `settings.py`
with a comment on every value.

### Experimental gestures (OFF by default)

Two V2 gestures ship **disabled** because they can be unstable — enable
them in `airos_settings.json` if you want to try them:

- `"three_finger_pinch_click": true` — thumb+index+middle pinched
  together = left click. Off by default because it can collide with the
  V1 middle-finger tap click while pinching.
- `"two_hand_gestures": true` — tracks both hands (costs FPS on slower
  laptops). Left fist + right index up/down = **scroll**; left fist +
  right open palm waved sideways = **switch window (Alt+Tab)**. With one
  hand in frame, everything behaves exactly like V1.

## 8. Troubleshooting

| Problem | Fix |
|---|---|
| "No camera found" | Close other apps using the webcam (Zoom, Teams). Try `"camera_index": 1` in `airos_settings.json`. Check Windows Settings → Privacy → Camera. |
| "Microphone unavailable" | Check Windows Settings → Privacy → Microphone, and that a default input device is set in Sound settings. Reinstall PyAudio (see Install). |
| Voice never responds | It needs internet (Google recognizer). Speak clearly ~30 cm from the mic. Lower `voice_energy_threshold` in settings for quiet mics. |
| Gestures feel jumpy | Improve lighting; face the camera palm-forward; lower `mouse_smoothing` (e.g. 0.25) for smoother cursor. |
| Clicks fire accidentally | Raise `pinch_threshold` slightly (e.g. 0.065) or raise `gesture_cooldown`. |
| Alt+F4 / Win+D don't work | Run the terminal as Administrator. |
| Gestures OFF though camera is ON | The hand model file is missing. AIR OS ships with `hand_landmarker.task` next to `main.py` — keep it there. If deleted, the app re-downloads it automatically on launch (needs internet once). |
| `PyAudio` won't install (Python 3.13) | You don't need it — AIR OS automatically uses `sounddevice` for the mic instead. Just make sure `pip install sounddevice` succeeded. |
| Voice shows "AudioDevice" / volume errors | Fixed in this build: audio COM is now initialized per-thread and the device is re-acquired automatically when it changes (e.g. plugging in headphones). |
| App opens but everything says OFF | That's limited mode — read the yellow error bar at the bottom, it tells you exactly what's missing. |

## 9. Known limitations

- **Voice needs internet** — recognition uses Google's free web API;
  offline = voice shows a readable error and gestures keep working.
- **One hand at a time** — tracking is single-hand for speed/accuracy.
- **Swipes vs. palm** — a swipe uses the whole hand; the open-palm
  pause requires holding the palm *still*, so they don't conflict, but
  very slow swipes may be ignored on purpose.
- **Circle direction** — is judged from the camera's mirrored view;
  if up/down feel inverted, set `"mirror_camera": false` in settings.
- **Held poses fire once** — holding a peace sign / four fingers /
  thumbs-up / palm triggers its action a single time; lower your hand
  (or change pose) and show it again to repeat. This is deliberate, so
  a held pose can't spam actions.
- **Hand model** — the tracker uses `hand_landmarker.task` (bundled).
  MediaPipe's modern versions (required for Python 3.13) removed the
  old hands API, so AIR OS supports both automatically.
- **Virtual keyboard focus** — on rare setups clicking a key can steal
  focus from the target app; the `keyboard` library workaround handles
  most cases, running as Administrator handles the rest.
- **Lighting matters** — hand tracking accuracy drops in dim rooms or
  with cluttered backgrounds.
- Tested logic runs cross-platform, but window shortcuts (Win+D,
  Alt+F4), pycaw volume, and lock-screen are **Windows-specific**.

## 10. Project layout

```
main.py               entry point + main loop + V2 wiring (start here)
air_hud.py            V2: the small top-left AIR HUD overlay
system_monitor.py     V2: CPU/RAM/battery watcher + explain mode
contacts.json         V2: local contacts for send-mail-by-voice
camera.py             threaded webcam capture, limited-mode fallback
microphone.py         mic detection + status
hand_tracker.py       MediaPipe wrapper + finger-pose helpers
gesture_engine.py     gesture state machine → actions
voice_engine.py       always-on listener + command parser
mouse_controller.py   smoothed relative cursor control
keyboard_controller.py keystrokes / hotkeys / modifier latching
virtual_keyboard.py   floating resizable on-screen keyboard
system_controller.py  volume, apps, screenshots, lock, battery, power
hud.py                main window, preview, status HUD, confirm popup
settings.py           all tunables + JSON persistence
utils.py              FPS, smoothing, circle & swipe detectors
test_simulation.py    47 automated checks, no hardware needed
```

Built as AIR OS V2 · gesture + voice control layer
