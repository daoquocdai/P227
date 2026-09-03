import type { CameraVisionResult } from "../../api/cameras";

export const VISION_OVERLAY_GRACE_MS = 450;

export function formatActionDisplay(metadata: CameraVisionResult["metadata"]): string | null {
  if (typeof metadata.action_label !== "string" || !metadata.action_label) return null;
  const confidence = typeof metadata.action_confidence === "number" && Number.isFinite(metadata.action_confidence)
    ? ` (${Math.round(metadata.action_confidence * 100)}%)` : "";
  return `Trạng thái: ${metadata.action_label}${confidence}`;
}

export interface VisionOverlayState {
  resetKey: string;
  sourceEpoch: number | null;
  retained: CameraVisionResult | null;
  expiresAt: number;
}

export function emptyVisionOverlayState(resetKey: string): VisionOverlayState {
  return { resetKey, sourceEpoch: null, retained: null, expiresAt: 0 };
}

export function hasVisualBBox(result: CameraVisionResult | null): result is CameraVisionResult {
  return Boolean(result?.detections.some((detection) => detection.bbox_xyxy));
}

export function updateVisionOverlayState(
  previous: VisionOverlayState,
  incoming: CameraVisionResult | null,
  now: number,
  active: boolean,
  resetKey: string,
): { state: VisionOverlayState; display: CameraVisionResult | null } {
  let state = previous.resetKey === resetKey ? previous : emptyVisionOverlayState(resetKey);
  if (!active) return { state: emptyVisionOverlayState(resetKey), display: null };

  const epoch = typeof incoming?.metadata.source_epoch === "number" ? incoming.metadata.source_epoch : null;
  if (epoch !== null && state.sourceEpoch !== null && epoch !== state.sourceEpoch) {
    state = emptyVisionOverlayState(resetKey);
  }
  if (epoch !== null) state = { ...state, sourceEpoch: epoch };
  if (hasVisualBBox(incoming)) {
    state = { ...state, retained: incoming, expiresAt: now + VISION_OVERLAY_GRACE_MS };
  }
  if (state.retained && state.expiresAt > now) return { state, display: state.retained };
  state = { ...state, retained: null, expiresAt: 0 };
  return { state, display: null };
}
