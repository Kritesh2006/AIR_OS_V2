# AIR OS Web

AIR OS in the browser: open the link, press **Start AIR**, allow the camera.
Everything runs locally in the tab. No install, no account, no API key, and
no camera frames ever leave the device.

## Develop

```
cd web
npm install
npm run dev        # http://localhost:5173 (camera works on localhost)
```

## Check

```
npm run typecheck
npm test           # unit tests (Vitest)
npm run e2e        # browser tests with a fake camera (Playwright + Chromium)
npm run check      # all of the above + production build
```

## Layout

| Path | Owner | Contents |
|---|---|---|
| `src/contracts.ts` | Claude + Sol | Interfaces between app and UI layers |
| `src/core/` | Claude | Pure logic, no DOM (state machine, fps; gestures from W1) |
| `src/vision/` | Claude | Camera and frame loop (hand tracking from W1) |
| `src/ui/` | Sol | AIR Pod, cursor, Start and Privacy screens |
| `src/app/` | Claude (Sol reviews) | Wiring. `placeholderUi.ts` is replaced by `src/ui` |

## Deploy

`.github/workflows/web.yml` tests every push and deploys `main` to GitHub
Pages. One-time setup: repository **Settings → Pages → Source: GitHub Actions**.
