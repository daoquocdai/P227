import assert from "node:assert/strict";
import test from "node:test";

import type { CameraVisionResult } from "../src/api/cameras.ts";
import {
  emptyVisionOverlayState,
  formatActionDisplay,
  updateVisionOverlayState,
  VISION_OVERLAY_GRACE_MS,
} from "../src/features/vision/visionOverlayState.ts";
import { VisionLatestPollGuard } from "../src/features/vision/visionPollingState.ts";

function result(frameId: number, epoch: number, withBox = true): CameraVisionResult {
  return {
    camera_id: "camera-1",
    frame_id: frameId,
    processed_at: 1,
    detections: withBox ? [{ label: "person", confidence: 0.9, bbox_xyxy: [1, 2, 3, 4], metadata: {} }] : [],
    metadata: { source_epoch: epoch },
  };
}

test("transient empty detections retain bbox only within the visual grace", () => {
  const initial = updateVisionOverlayState(emptyVisionOverlayState("camera:on"), result(1, 1), 100, true, "camera:on");
  const transient = updateVisionOverlayState(initial.state, result(2, 1, false), 100 + VISION_OVERLAY_GRACE_MS - 1, true, "camera:on");
  assert.equal(transient.display?.frame_id, 1);
  const expired = updateVisionOverlayState(transient.state, null, 100 + VISION_OVERLAY_GRACE_MS, true, "camera:on");
  assert.equal(expired.display, null);
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

test("poll guard prevents overlap and rejects stale frames", () => {
  const guard = new VisionLatestPollGuard();
  const token = guard.begin();
  assert.equal(typeof token, "number");
  assert.equal(guard.begin(), null);
  assert.equal(guard.accept(token!, { epoch: 2, frameId: 10 }), true);
  assert.equal(guard.accept(token!, { epoch: 2, frameId: 9 }), false);
  guard.finish(token!);
  assert.equal(typeof guard.begin(), "number");
});

test("poll guard rejects responses from a prior lifecycle", () => {
  const guard = new VisionLatestPollGuard();
  const oldToken = guard.begin()!;
  guard.reset();
  assert.equal(guard.accept(oldToken, { epoch: 1, frameId: 20 }), false);
});
