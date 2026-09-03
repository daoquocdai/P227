import type { CameraVisionResult } from "../../api/cameras";

export const VISION_OVERLAY_GRACE_MS = 450;
export const VISION_ACTION_GRACE_MS = 750;
export const VISION_ACTION_ANALYZING = "Đang phân tích";

export type VisionActionPlacement = "bbox" | null;
export type VisionActionTone = "fall" | "normal";

export interface VisionBBoxLabelLayout {
  identityX: number;
  identityY: number;
  actionX: number;
  actionY: number;
}

export function visionBBoxLabelLayout(
  bboxLeft: number,
  bboxTop: number,
  labelHeight: number,
  canvasTop: number,
  padding: number,
): VisionBBoxLabelLayout {
  return {
    identityX: bboxLeft,
    identityY: Math.max(canvasTop, bboxTop - labelHeight),
    actionX: bboxLeft + padding,
    actionY: bboxTop + padding,
  };
}

export function formatActionDisplay(metadata: CameraVisionResult["metadata"]): string | null {
  if (typeof metadata.action_label !== "string" || !metadata.action_label) return null;
  const confidence = typeof metadata.action_confidence === "number" && Number.isFinite(metadata.action_confidence)
    ? ` (${Math.round(metadata.action_confidence * 100)}%)` : "";
  return `Trạng thái: ${metadata.action_label}${confidence}`;
}

export interface VisionOverlayState {
  resetKey: string;
  sourceEpoch: number | null;
  latestFrameId: number | null;
  retained: CameraVisionResult | null;
  expiresAt: number;
  retainedAction: string | null;
  actionExpiresAt: number;
  retainedActionIsFall: boolean;
}

export function emptyVisionOverlayState(resetKey: string): VisionOverlayState {
  return {
    resetKey,
    sourceEpoch: null,
    latestFrameId: null,
    retained: null,
    expiresAt: 0,
    retainedAction: null,
    actionExpiresAt: 0,
    retainedActionIsFall: false,
  };
}

export function hasVisualBBox(result: CameraVisionResult | null): result is CameraVisionResult {
  return Boolean(result?.detections.some((detection) => {
    const bbox = detection.bbox_xyxy;
    return bbox?.length === 4
      && bbox.every((value) => typeof value === "number" && Number.isFinite(value))
      && bbox[2] > bbox[0]
      && bbox[3] > bbox[1];
  }));
}

export function isFallAction(metadata: CameraVisionResult["metadata"]): boolean {
  return metadata.action_class_id === 0 || metadata.action_class_name === "fall";
}

export function visionActionPresentation(
  display: CameraVisionResult | null,
  state: VisionOverlayState,
  actionDisplay: string | null,
): { placement: VisionActionPlacement; tone: VisionActionTone } {
  const hasActionState = Boolean(state.retainedAction && state.actionExpiresAt > 0);
  return {
    placement: display && actionDisplay ? "bbox" : null,
    tone: hasActionState
      ? (state.retainedActionIsFall ? "fall" : "normal")
      : (display && isFallAction(display.metadata) ? "fall" : "normal"),
  };
}

export function updateVisionOverlayState(
  previous: VisionOverlayState,
  incoming: CameraVisionResult | null,
  now: number,
  active: boolean,
  resetKey: string,
): { state: VisionOverlayState; display: CameraVisionResult | null; actionDisplay: string | null } {
  let state = previous.resetKey === resetKey ? previous : emptyVisionOverlayState(resetKey);
  if (!active) {
    return { state: emptyVisionOverlayState(resetKey), display: null, actionDisplay: null };
  }

  const epoch = incoming
    ? (typeof incoming.metadata.source_epoch === "number" ? incoming.metadata.source_epoch : 0)
    : null;
  if (epoch !== null && state.sourceEpoch !== null && epoch !== state.sourceEpoch) {
    if (epoch < state.sourceEpoch) incoming = null;
    else state = emptyVisionOverlayState(resetKey);
  }
  const duplicateOrStale = Boolean(
    incoming
    && epoch !== null
    && state.sourceEpoch === epoch
    && state.latestFrameId !== null
    && incoming.frame_id <= state.latestFrameId,
  );
  if (incoming && !duplicateOrStale) {
    const action = formatActionDisplay(incoming.metadata);
    state = {
      ...state,
      sourceEpoch: epoch ?? state.sourceEpoch,
      latestFrameId: incoming.frame_id,
      ...(hasVisualBBox(incoming)
        ? { retained: incoming, expiresAt: now + VISION_OVERLAY_GRACE_MS }
        : {}),
      ...(action
        ? {
          retainedAction: action,
          actionExpiresAt: now + VISION_ACTION_GRACE_MS,
          retainedActionIsFall: isFallAction(incoming.metadata),
        }
        : {}),
    };
  }
  const display = state.retained && state.expiresAt > now ? state.retained : null;
  const actionDisplay = state.retainedAction && state.actionExpiresAt > now
    ? state.retainedAction
    : VISION_ACTION_ANALYZING;
  if (!display || actionDisplay === VISION_ACTION_ANALYZING) {
    state = {
      ...state,
      ...(!display ? { retained: null, expiresAt: 0 } : {}),
      ...(actionDisplay === VISION_ACTION_ANALYZING
        ? { retainedAction: null, actionExpiresAt: 0, retainedActionIsFall: false }
        : {}),
    };
  }
  return { state, display, actionDisplay };
}
