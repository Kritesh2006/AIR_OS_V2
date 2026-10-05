# AIR OS — Interaction Architecture (frozen)

This is the frozen design agreed between Claude and Sol and approved by
Kritesh. Code in `contracts.py` and `channels.py` is the source of truth
for types. **Any change to this document or those two files is a
contract change and needs review from both implementers.**

## 1. Goals

- Improve AIR OS V2, don't rebuild it. NORMAL mode behaves exactly like V2.
- Small top-left camera Pod. The Control Panel is a normal window that
  can be minimized while AIR keeps working.
- No gesture ever performs a destructive action directly:

  ```
  FIST (hold)  → intent: "I want to close something"
  INDEX FINGER → move an AIR virtual cursor over window cards
  BLINK        → confirm (deliberate blink)
  ```

- Everything runs locally. No cloud dependency in the interaction path.

## 2. Phases

| Phase | Scope |
|---|---|
| 1 Foundation | DPI setup, SensorWorker thread, LatestState/EventQueue/CommandQueue, AIR Pod with small preview, minimizable Control Panel. **No gesture behavior change.** |
| 2 Intent + selection | ModeRouter, InteractionSession, CloseWindowProvider, DimLayer + CardLayer, AIR virtual cursor. Fist hold enters close selection instead of Alt+F4. Enter = temporary developer confirm, Esc = cancel. |
| 3 Blink | FaceTracker, blink state machine, target captured at blink onset, blink settings. Enter confirm removed. Esc stays cancel. |
| 4 Polish | Filter tuning, animations, card visuals, calibration if needed, performance, edge cases. |

No extra action providers until V1 survives real use.

## 3. Threads and ownership

| Thread | Owns / may mutate | Talks to others only via |
|---|---|---|
| Camera thread (`camera.py`) | `VideoCapture` | `camera.read_latest()` → frame, capture `ts_ms`, `seq` |
| SensorWorker (`sensor_worker.py`) | HandTracker, FaceTracker, BlinkDetector, GestureEngine, ModeRouter, InteractionSession, PointerController, providers, global key hook | publishes `LatestState`, puts `UiEvent`s, drains `Command`s |
| Tk main (`main.py`) | every widget: Control Panel, AirPod, SelectionOverlay, legacy popup | reads `LatestState`, drains `UiEvent`s, puts `Command`s |
| Voice / keyboard hook / monitor | their own internals | put `UiEvent`s and/or `Command`s only |

Rules:

- Only the Tk main thread touches Tk widgets. No `root.after()` from other threads.
- Only the SensorWorker creates or mutates the session, router and providers.
  Tk never calls their methods.
- `frame_bgr` never leaves the SensorWorker. Tk only gets `preview_rgb`,
  a small, fresh buffer per publish that is never mutated after
  `LatestState.publish()`.
- `LatestState` holds high-frequency data (newest wins). `EventQueue`
  holds things that must never be dropped. `CommandQueue` carries input
  back to the worker (keys, pause, popup state, shutdown).
- `EventKind.UI_CALL` exists only to migrate legacy `_ui(fn)` callers.
  No new feature may use it.
- One camera capture. One timestamp per captured frame, assigned at
  acquisition with `time.monotonic()`, passed to every model for that frame.
- New code uses `time.monotonic()`.

Tk main loop (every ~16 ms): drain `EventQueue` and dispatch, then read
`LatestState` and render the Pod (and the overlay when visible) if
`seq` changed.

### Startup order

```
configure_windows_process()        # DPI awareness, before any Tk object
→ create Tk root / Control Panel / AirPod
→ create SelectionOverlay, read primary-monitor size (physical px)
→ build PointerController / InteractionSession with that fixed geometry
→ start camera, start SensorWorker
```

V1 supports the primary monitor only.

### Shutdown

Control Panel X → `SHUTDOWN` command → UI marked as shutting down → Tk
polls with `after()` for `WORKER_STOPPED` → destroy windows. A hard
deadline (3 s) destroys anyway. Tk never blocks on `join()`.
Minimize keeps AIR running. No tray in V1.

## 4. Modes and the interaction session

```
Modes: NORMAL | CLOSE_SELECTION | WAIT_FOR_RELEASE

NORMAL           existing GestureEngine, unchanged
CLOSE_SELECTION  InteractionSession owns input; GestureEngine not called
WAIT_FOR_RELEASE GestureEngine not called until the pose differs from the
                 one that ended the session for ≥ release_pose_ms (150),
                 or no hand is seen for ≥ release_absent_ms (300).
                 No time-based unlock.
```

Session: `IDLE → ARMING → SELECTING → LOCKED → EXECUTING → VERIFYING → COOLDOWN → IDLE`

- GestureEngine only reports the fist lifecycle: `on_fist_hold(progress)`
  and `on_fist_release()`. The router stamps them with the frame `ts_ms`.
- The router owns `legacy_popup_open` (from `SET_LEGACY_POPUP_OPEN`):
  - NORMAL + popup open: a quick fist dismisses the popup; holding never
    enters close selection.
  - NORMAL + no popup: hold progress drives ARMING; reaching
    `fist_hold_seconds` begins CLOSE_SELECTION.
  - In CLOSE_SELECTION the fist has no meaning.
- Cancel: open palm, Esc, timeout (`select_timeout_s`), hand lost longer
  than `hand_lost_grace_s`. Every exit path goes through one
  `InteractionSession._end()`.
- After any session end the router enters WAIT_FOR_RELEASE.

### Global key hook

- Installed by the worker when CLOSE_SELECTION begins, removed in `_end()`;
  also released in the worker loop's `finally` and via `atexit`. Release
  is idempotent.
- While active: Esc → `KEY_CANCEL`, Enter → `KEY_CONFIRM` (Phase 2 only,
  behind `debug_keyboard_confirm`), both suppressed from the foreground
  app. Outside CLOSE_SELECTION nothing is suppressed.
- If registration fails: emit an `ERROR` event ("keyboard controls
  unavailable") and continue without key confirm/cancel.
- Uses the existing `keyboard` dependency.

### Closing a window

- `CloseWindowProvider` enumerates Alt-Tab-eligible windows; excludes
  AIR's own pid, shell/taskbar/desktop and cloaked windows; includes
  minimized windows (labelled); omits windows AIR cannot control
  (elevated / access denied) and logs how many were hidden.
- `execute()`: revalidate hwnd + pid + title, then `PostMessageW(WM_CLOSE)`.
  Returns `SENT` immediately. Never `TerminateProcess`, never Alt+F4.
- VERIFYING: each worker tick calls `still_exists()` (hwnd + pid only;
  title may change). Gone → `CLOSED`. Deadline (`close_verify_s`) →
  `STILL_OPEN`. A save dialog is the app's business; AIR never bypasses it.

### Pointer

```
index tip (normalized) → One Euro filter → control box anchored at the
hand position when selection began (pointer_box_fraction) → overlay px
→ AIR virtual cursor → tile hysteresis + dwell lock (select_dwell_ms)
```

- The Windows cursor is never moved during CLOSE_SELECTION.
- Targets are snapshotted when selection begins.
- The worker owns geometry: `pointer.layout_grid()` computes card rects,
  sent once in `OVERLAY_SHOW`. The overlay only draws.
- `PointerController.locked_at(ts_ms)` keeps ~1 s of lock history so the
  blink confirms the target that was locked at blink onset.

### Blink (Phase 3)

- MediaPipe FaceLandmarker with blendshapes (`eyeBlinkLeft/Right`),
  optional EAR cross-check. Runs on the same captured frame and `ts_ms`
  as the hand tracker, only in SELECTING / LOCKED.
- `BlinkDetector` states `UNKNOWN / OPEN / CLOSING / CLOSED`, hysteresis
  (`blink_close_threshold`, `blink_open_threshold`), timestamps not frame
  counts, an in-progress blink is discarded on face loss. Emits
  `BlinkEvent(start_ts, duration_ms, peak_confidence)`.
- FaceTracker detects the physical blink. InteractionSession decides
  whether it confirms (`blink_min_ms`..`blink_max_ms`, target locked at
  `start_ts`).

## 5. UI

- **AirPod** (top-left, always on top, no focus steal): small live preview
  plus status line `AIR • <PodStatus>`. Keeps the AirHUD public API
  (`say`, `ask`, `answer_by_voice`, `has_question`, `set_idle_text`,
  `show`, `hide`, `toggle`) so voice and monitor code keep working.
- **Control Panel**: the V2 HUD as a normal, minimizable window (not
  always on top). Minimize = AIR keeps running. X = quit.
- **SelectionOverlay** (Phase 2): two full-screen, click-through,
  non-activating windows. DimLayer is black at low alpha. CardLayer has a
  transparent background and draws a centered grid of cards plus the AIR
  virtual cursor.

Pod statuses: `READY → CLOSE? → SELECT → BLINK → CLOSING… → CLOSED / STILL OPEN`,
plus `PAUSED` and `CANCELLED`.

## 6. Settings added by this work (defaults; tuned with Kritesh)

| Key | Default | Phase |
|---|---|---|
| `select_dwell_ms` | 250 | 2 |
| `select_timeout_s` | 8 | 2 |
| `hand_lost_grace_s` | 1.0 | 2 |
| `release_pose_ms` | 150 | 2 |
| `release_absent_ms` | 300 | 2 |
| `close_verify_s` | 2.0 | 2 |
| `pointer_box_fraction` | 0.35 | 2 |
| `one_euro_min_cutoff`, `one_euro_beta` | tbd | 2 |
| `debug_keyboard_confirm` | true in Phase 2, removed in Phase 3 | 2 |
| `blink_close_threshold` | 0.55 | 3 |
| `blink_open_threshold` | 0.35 | 3 |
| `blink_min_ms` | 300 | 3 |
| `blink_max_ms` | 1200 | 3 |

ARMING reuses the existing `fist_hold_seconds`.

## 7. File ownership

| Owner | Files |
|---|---|
| Claude | `contracts.py`, `channels.py`, `sensor_worker.py`, `interaction.py`, `face_tracker.py`, `pointer.py`, minimal hooks in `gesture_engine.py`, `camera.py`, `hand_tracker.py`, tests |
| Sol | `win_windows.py` (incl. `configure_windows_process()`, CloseWindowProvider), `air_pod.py`, `selection_overlay.py`, minimal `hud.py` changes, UI/Windows tests |
| Integration (Claude, reviewed by Sol) | `main.py`, `settings.py` |
| Last, after Kritesh verifies | `README.md`, `requirements.txt` |

Windows-specific code must be a harmless no-op on other platforms so
tests run anywhere.

## 8. Branch rules

- Claude: `claude/github-repo-modifications-6c43nh`. Sol: `sol/air-os-phase1-ui`.
- Nobody merges a feature branch into `main` on their own. Claude
  integrates, Sol reviews the integration diff, Kritesh tests on Windows
  with a real webcam, and only Kritesh approves landing a phase on `main`.

## 9. Known debt (out of scope here)

- Voice recognition uses Google's online recognizer; the spoken passcode
  leaves the machine and the default passcode is public in the README.
  Plan: local recognizer (e.g. Vosk) in a separate branch.
- The hand model fallback URL is a third-party mirror with no checksum.
  Plan: SHA-256 verification in a separate small commit.
