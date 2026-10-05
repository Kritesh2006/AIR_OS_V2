// Copies the MediaPipe wasm runtime and the hand model into public/ so the
// site self-hosts everything (no CDN at runtime). Runs before dev/build.
import { createHash } from 'node:crypto';
import { copyFileSync, existsSync, mkdirSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const web = join(dirname(fileURLToPath(import.meta.url)), '..');
const wasmSrc = join(web, 'node_modules/@mediapipe/tasks-vision/wasm');
const wasmDst = join(web, 'public/mediapipe/wasm');
const modelSrc = join(web, '../hand_landmarker.task'); // the same file desktop AIR bundles
const modelDst = join(web, 'public/models/hand_landmarker.task');
// Pinned so a swapped or corrupted model fails the build instead of shipping.
const MODEL_SHA256 = 'fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1';

mkdirSync(wasmDst, { recursive: true });
// SIMD build for modern browsers, no-SIMD build as MediaPipe's own fallback.
for (const f of ['vision_wasm_internal.js', 'vision_wasm_internal.wasm',
  'vision_wasm_nosimd_internal.js', 'vision_wasm_nosimd_internal.wasm']) {
  copyFileSync(join(wasmSrc, f), join(wasmDst, f));
}

if (!existsSync(modelSrc)) throw new Error(`Hand model missing: ${modelSrc}`);
const hash = createHash('sha256').update(readFileSync(modelSrc)).digest('hex');
if (hash !== MODEL_SHA256) throw new Error(`Hand model checksum mismatch: ${hash}`);
mkdirSync(dirname(modelDst), { recursive: true });
copyFileSync(modelSrc, modelDst);
console.log('[prepare-assets] MediaPipe wasm + hand model ready in public/');
