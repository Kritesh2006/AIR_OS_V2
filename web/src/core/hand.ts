/** Hand data shared by vision, core logic and UI (no DOM, no MediaPipe types). */

/** Normalized landmark in the UNMIRRORED camera image: x, y in 0..1. */
export interface Landmark {
  readonly x: number;
  readonly y: number;
  readonly z?: number;
}

export interface HandObservation {
  /** 21 MediaPipe hand landmarks. */
  readonly landmarks: readonly Landmark[];
  /** "Left" | "Right" as reported by MediaPipe. */
  readonly handedness: string;
  /** Handedness confidence 0..1 (the best per-hand score MediaPipe exposes). */
  readonly score: number;
}

/** MediaPipe landmark indices. */
export const LM = {
  WRIST: 0,
  THUMB_IP: 3,
  THUMB_TIP: 4,
  INDEX_MCP: 5,
  INDEX_PIP: 6,
  INDEX_TIP: 8,
  MIDDLE_MCP: 9,
  MIDDLE_PIP: 10,
  MIDDLE_TIP: 12,
  RING_PIP: 14,
  RING_TIP: 16,
  PINKY_MCP: 17,
  PINKY_PIP: 18,
  PINKY_TIP: 20,
} as const;

/** Bone pairs for drawing a skeleton (debug view). */
export const HAND_CONNECTIONS: ReadonlyArray<readonly [number, number]> = [
  [0, 1], [1, 2], [2, 3], [3, 4],
  [0, 5], [5, 6], [6, 7], [7, 8],
  [5, 9], [9, 10], [10, 11], [11, 12],
  [9, 13], [13, 14], [14, 15], [15, 16],
  [13, 17], [17, 18], [18, 19], [19, 20],
  [0, 17],
];
