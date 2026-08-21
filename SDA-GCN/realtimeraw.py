"""Raw fall-classifier entry point using the shared realtime source pipeline."""
from __future__ import annotations

import argparse
import threading
import numpy as np
import torch
import torch.nn.functional as F

from extractkpt.common.cleaning import clean_out_of_bounds_data
from fusion.interpolate import interpolate_missing
from fusion.kalman_filter import apply_kalman_filter
from fusion.normalize_pose import normalize_pose
from realtime import (BackendResolutionError, FallDetectionSystem as RealtimeFallDetectionSystem,
                      parse_source, resample_frames, run_flask)
from runtime.timing import source_span_s


class FallDetectionSystem(RealtimeFallDetectionSystem):
    """Preserve raw model semantics while reusing source/timing/identity code."""
    def detect_fall(self, current_source_time_s):
        if source_span_s(self.pose_samples, current_source_time_s) < 2.0:
            return
        raw_array = np.array([sample.keypoints for sample in self.pose_samples])
        kpt = clean_out_of_bounds_data(raw_array)
        kpt = interpolate_missing(kpt)
        kpt = kpt - kpt[:, 0:1, :]
        kpt = normalize_pose(kpt)
        kpt = apply_kalman_filter(kpt)
        kpt = resample_frames(kpt, target_frames=self.window_size)
        data_tensor = torch.from_numpy(kpt.transpose(2, 0, 1)[:, :, :, np.newaxis]).unsqueeze(0).float()
        with torch.inference_mode():
            output = self.action_model(data_tensor)
            self.current_sda_gcn_ms = self.action_model.last_inference_ms
            prob = F.softmax(output, dim=1).squeeze()
            pred_idx = torch.argmax(prob).item()
            conf = float(prob[pred_idx])
            if pred_idx == 1:
                self.current_action = f"Nga! ({conf:.2f})"
                self.action_color = (0, 0, 255)
                self.send_event_to_backend("FALL_CONFIRMED", conf)
            else:
                self.current_action = f"Khong nga ({conf:.2f})"
                self.action_color = (0, 255, 0)
        while self.pose_samples and current_source_time_s - self.pose_samples[0].source_time_s > 1.0:
            self.pose_samples.popleft()


def parse_args():
    parser = argparse.ArgumentParser(description="Realtime raw Vision-only fall detection")
    parser.add_argument("--device", choices=("auto", "cuda", "amd", "intel", "cpu"), default="auto")
    parser.add_argument("--preview", choices=("window", "web", "none"), default="window")
    parser.add_argument("--send-events", action="store_true")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000/api/v1/vision/events")
    parser.add_argument("--identity", choices=("on", "off"), default="on")
    parser.add_argument("--source", default="0", help="Camera index or local video path (default: 0)")
    parser.add_argument("--source-fps", type=float, help="Override video FPS when metadata is invalid")
    parser.add_argument("--vision-fps", type=float, default=15.0)
    parser.add_argument("--identity-interval", type=float, default=0.5)
    parser.add_argument("--face-det-size", type=int, default=416)
    parser.add_argument("--rebuild-face-cache", action="store_true")
    parser.add_argument("--log-level", choices=("debug", "info", "warning", "error"), default="info")
    parser.add_argument("--identity-debug", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    try:
        source_spec = parse_source(args.source)
    except ValueError as exc:
        raise SystemExit(f"[Source Error] {exc}")
    if args.source_fps is not None and args.source_fps <= 0:
        raise SystemExit("[Source Error] --source-fps must be positive")
    if args.preview == "web":
        threading.Thread(target=run_flask, daemon=True).start()
    system = FallDetectionSystem(
        args.device, args.preview, args.backend_url if args.send_events else None,
        args.identity, args.vision_fps, args.identity_interval, args.face_det_size,
        args.rebuild_face_cache, args.log_level, args.identity_debug, source_spec, args.source_fps)
    try:
        system.init_models()
        system.load_known_faces()
        system.run()
    finally:
        system.shutdown()
        system.event_sender.close()


if __name__ == "__main__":
    try:
        main()
    except BackendResolutionError as exc:
        raise SystemExit(f"[Vision Runtime Error] {exc}")
