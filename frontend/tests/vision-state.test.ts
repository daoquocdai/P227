import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import type { CameraVisionResult } from "../src/api/cameras.ts";
import {
  emptyVisionOverlayState,
  formatActionDisplay,
  isFallAction,
  updateVisionOverlayState,
  visionActionPresentation,
  VISION_ACTION_ANALYZING,
  VISION_ACTION_GRACE_MS,
  VISION_OVERLAY_GRACE_MS,
} from "../src/features/vision/visionOverlayState.ts";
import {
  nextVisionPollDelay,
  VISION_POLL_INTERVAL_MS,
  VisionLatestPollGuard,
} from "../src/features/vision/visionPollingState.ts";

function result(frameId: number, epoch: number, withBox = true): CameraVisionResult {
  return {
    camera_id: "camera-1",
    frame_id: frameId,
    processed_at: 1,
    detections: withBox ? [{ label: "person", confidence: 0.9, bbox_xyxy: [1, 2, 3, 4], metadata: {} }] : [],
    metadata: { source_epoch: epoch },
  };
}

const canvasSource = readFileSync(
  new URL("../src/features/vision/VisionOverlayCanvas.tsx", import.meta.url),
  "utf8",
);

test("transient empty detections retain bbox only within the visual grace", () => {
  const initial = updateVisionOverlayState(emptyVisionOverlayState("camera:on"), result(1, 1), 100, true, "camera:on");
  const transient = updateVisionOverlayState(initial.state, result(2, 1, false), 100 + VISION_OVERLAY_GRACE_MS - 1, true, "camera:on");
  assert.equal(transient.display?.frame_id, 1);
  const expired = updateVisionOverlayState(transient.state, null, 100 + VISION_OVERLAY_GRACE_MS, true, "camera:on");
  assert.equal(expired.display, null);
  assert.match(canvasSource, /window\.setTimeout/);
  assert.match(canvasSource, /drawRef\.current\(\)/);
});

test("duplicate frame does not renew bbox grace", () => {
  const initial = updateVisionOverlayState(emptyVisionOverlayState("camera:on"), result(1, 1), 100, true, "camera:on");
  const duplicate = updateVisionOverlayState(initial.state, result(1, 1), 400, true, "camera:on");
  assert.equal(duplicate.state.expiresAt, 100 + VISION_OVERLAY_GRACE_MS);
  assert.equal(updateVisionOverlayState(duplicate.state, null, 551, true, "camera:on").display, null);
});

test("source epoch and camera or Vision lifecycle changes clear retained bbox", () => {
  const initial = updateVisionOverlayState(emptyVisionOverlayState("camera:on"), result(1, 1), 100, true, "camera:on");
  assert.equal(updateVisionOverlayState(initial.state, result(2, 2, false), 101, true, "camera:on").display, null);
  assert.equal(updateVisionOverlayState(initial.state, null, 101, true, "other-camera:on").display, null);
  assert.equal(updateVisionOverlayState(initial.state, null, 101, false, "camera:off").display, null);
});

test("UI formats every authoritative Vietnamese action label", () => {
  const labels = ["Ngã", "Đứng", "Cúi", "Ngồi", "Nằm"] as const;
  assert.deepEqual(
    labels.map((action_label) => formatActionDisplay({ action_label, action_confidence: 0.92 })),
    labels.map((label) => `Trạng thái: ${label} (92%)`),
  );
});

test("action status is available without a bbox and later falls back to analyzing", () => {
  const withoutBox = result(1, 1, false);
  withoutBox.metadata.action_label = "Đứng";
  withoutBox.metadata.action_confidence = 0.91;
  const selected = updateVisionOverlayState(
    emptyVisionOverlayState("camera:on"), withoutBox, 100, true, "camera:on",
  );
  assert.equal(selected.display, null);
  assert.equal(selected.actionDisplay, "Trạng thái: Đứng (91%)");
  assert.equal(visionActionPresentation(selected.display, selected.state).placement, "global");
  const expired = updateVisionOverlayState(
    selected.state, null, 100 + VISION_ACTION_GRACE_MS, true, "camera:on",
  );
  assert.equal(expired.actionDisplay, VISION_ACTION_ANALYZING);
  assert.equal(visionActionPresentation(expired.display, expired.state).placement, null);
});

test("action with a valid bbox is placed inside the bbox, not globally", () => {
  const withBox = result(1, 1);
  withBox.metadata.action_label = "Đứng";
  withBox.metadata.action_confidence = 0.88;
  withBox.metadata.action_class_id = 1;
  withBox.metadata.action_class_name = "standing";
  const selected = updateVisionOverlayState(
    emptyVisionOverlayState("camera:on"), withBox, 100, true, "camera:on",
  );
  assert.deepEqual(visionActionPresentation(selected.display, selected.state), {
    placement: "bbox",
    tone: "normal",
  });
  assert.match(
    canvasSource,
    /drawLabel\(identityLabel\(detection\)[\s\S]*actionY[\s\S]*drawLabel\(refreshed\.actionDisplay/,
  );
});

test("global fallback disappears when a bbox returns", () => {
  const withoutBox = result(1, 1, false);
  withoutBox.metadata.action_label = "Cúi";
  withoutBox.metadata.action_confidence = 0.8;
  const fallback = updateVisionOverlayState(
    emptyVisionOverlayState("camera:on"), withoutBox, 100, true, "camera:on",
  );
  assert.equal(visionActionPresentation(fallback.display, fallback.state).placement, "global");

  const withBox = result(2, 1, true);
  withBox.metadata.action_label = "Cúi";
  withBox.metadata.action_confidence = 0.82;
  const restored = updateVisionOverlayState(fallback.state, withBox, 200, true, "camera:on");
  assert.equal(visionActionPresentation(restored.display, restored.state).placement, "bbox");
});

test("fall class selects red presentation", () => {
  const fall = result(1, 1);
  fall.metadata.action_label = "Ngã";
  fall.metadata.action_confidence = 0.94;
  fall.metadata.action_class_id = 0;
  fall.metadata.action_class_name = "fall";
  const selected = updateVisionOverlayState(
    emptyVisionOverlayState("camera:on"), fall, 100, true, "camera:on",
  );
  assert.equal(visionActionPresentation(selected.display, selected.state).tone, "fall");
  assert.equal(isFallAction({ action_class_id: 0, action_class_name: "standing" }), true);
  assert.equal(isFallAction({ action_class_id: 4, action_class_name: "fall" }), true);
  assert.match(canvasSource, /"#ef4444" : "#00ff00"/);
  assert.match(canvasSource, /"#f87171" : "#86efac"/);
});

test("standing and other non-fall classes select green presentation", () => {
  const standing = result(1, 1);
  standing.metadata.action_label = "Đứng";
  standing.metadata.action_confidence = 0.92;
  standing.metadata.action_class_id = 1;
  standing.metadata.action_class_name = "standing";
  const selected = updateVisionOverlayState(
    emptyVisionOverlayState("camera:on"), standing, 100, true, "camera:on",
  );
  assert.equal(visionActionPresentation(selected.display, selected.state).tone, "normal");
});

test("poll guard prevents overlap and rejects stale frames", () => {
  const guard = new VisionLatestPollGuard();
  const token = guard.begin();
  assert.equal(typeof token, "number");
  assert.equal(guard.begin(), null);
  assert.equal(guard.accept(token!, { epoch: 2, frameId: 10 }), true);
  assert.equal(guard.accept(token!, { epoch: 2, frameId: 10 }), false);
  assert.equal(guard.accept(token!, { epoch: 2, frameId: 9 }), false);
  guard.finish(token!);
  assert.equal(typeof guard.begin(), "number");
});

test("poll guard accepts a higher epoch even when frame id resets", () => {
  const guard = new VisionLatestPollGuard();
  const token = guard.begin()!;
  assert.equal(guard.accept(token, { epoch: 2, frameId: 100 }), true);
  assert.equal(guard.accept(token, { epoch: 3, frameId: 1 }), true);
  assert.equal(guard.accept(token, { epoch: 2, frameId: 101 }), false);
});

test("poll cadence subtracts request latency from the 200ms start interval", () => {
  assert.equal(VISION_POLL_INTERVAL_MS, 200);
  assert.equal(nextVisionPollDelay(75), 125);
  assert.equal(nextVisionPollDelay(250), 0);
});

test("poll guard rejects responses from a prior lifecycle", () => {
  const guard = new VisionLatestPollGuard();
  const oldToken = guard.begin()!;
  guard.reset();
  assert.equal(guard.accept(oldToken, { epoch: 1, frameId: 20 }), false);
});
