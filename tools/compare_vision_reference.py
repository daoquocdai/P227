"""CPU device-shim parity harness for the oracle and hardware-only runtimev2."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.util
import json
import sys
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
import yaml
from ultralytics import YOLO

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORACLE_ROOT = PROJECT_ROOT / "visionv2" / "P-227-thi"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(ORACLE_ROOT) not in sys.path:
    sys.path.insert(0, str(ORACLE_ROOT))

from visionv2.runtimev2 import realtime as portable  # noqa: E402
from visionv2.runtimev2.hardware import (  # noqa: E402
    RuntimeSelection,
    apply_device_safety_shim,
    load_action_model,
)


@dataclass
class Trace:
    sampled_ids: list[int] = field(default_factory=list)
    observation_times: list[float] = field(default_factory=list)
    boxes: list[np.ndarray] = field(default_factory=list)
    poses: list[np.ndarray] = field(default_factory=list)
    window_ids: list[list[int]] = field(default_factory=list)
    model_inputs: list[np.ndarray] = field(default_factory=list)
    logits: list[np.ndarray] = field(default_factory=list)
    classes: list[int] = field(default_factory=list)
    transitions: list[dict[str, Any]] = field(default_factory=list)


def load_oracle_module():
    source = ORACLE_ROOT / "realtime.py"
    spec = importlib.util.spec_from_file_location("visionv2_oracle_realtime", source)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load oracle: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_oracle_cpu_model(config: dict[str, Any], weights_path: Path):
    module_name, separator, class_name = str(config["model"]).rpartition(".")
    if not separator:
        raise ImportError(f"Invalid oracle model path: {config['model']}")
    module = importlib.import_module(module_name)
    apply_device_safety_shim(module)
    model_class = getattr(module, class_name)
    model = model_class(**config.get("model_args", {})).to(torch.device("cpu"))
    weights = torch.load(weights_path, map_location="cpu", weights_only=False)
    weights = OrderedDict((key.split("module.")[-1], value) for key, value in weights.items())
    model.load_state_dict(weights, strict=False)
    return model.eval()


def _letterbox(frame: np.ndarray) -> np.ndarray:
    height, width = frame.shape[:2]
    scale = 1024 / max(height, width)
    new_w, new_h = int(width * scale), int(height * scale)
    frame = cv2.resize(frame, (new_w, new_h))
    pad_w, pad_h = 1024 - new_w, 1024 - new_h
    return cv2.copyMakeBorder(
        frame,
        pad_h // 2,
        pad_h - pad_h // 2,
        pad_w // 2,
        pad_w - pad_w // 2,
        cv2.BORDER_CONSTANT,
        value=(0, 0, 0),
    )


def trace_video(
    video: Path,
    frame_limit: int,
    api: Any,
    action_model: Any,
    replay_times: list[float] | None = None,
) -> Trace:
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise RuntimeError(f"Cannot open video: {video}")
    detector = YOLO(str(ORACLE_ROOT / "yolov8n.pt"), verbose=False).to(torch.device("cpu"))
    pose = api.mp.solutions.pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)
    trace = Trace()
    kpts_buffer: list[np.ndarray] = []
    timestamp_buffer: list[float] = []
    frame_ids: list[int] = []
    current_action = "Waiting for frames..."
    pending_events: list[dict[str, Any]] = []
    last_global_kpts = None
    started = time.perf_counter()

    try:
        for frame_id in range(frame_limit):
            success, frame = capture.read()
            if not success:
                break
            frame_count = frame_id + 1
            prepared = _letterbox(frame)
            if frame_count % 2 == 0:
                continue
            observation_index = len(trace.sampled_ids)
            now = (
                replay_times[observation_index]
                if replay_times is not None
                else time.perf_counter() - started
            )
            trace.sampled_ids.append(frame_id)
            trace.observation_times.append(now)

            result = detector.track(prepared, persist=True, classes=0, verbose=False)[0]
            boxes_obj = result.boxes
            keypoints = np.zeros((25, 3), dtype=np.float32)
            person_found = False
            recorded_box = np.empty((0, 4), dtype=np.float32)
            if boxes_obj is not None and len(boxes_obj) > 0:
                boxes = boxes_obj.xyxy.cpu().numpy()
                best = int(np.argmax((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])))
                x1, y1, x2, y2 = map(int, boxes[best])
                x1, y1 = max(0, x1 - 30), max(0, y1 - 30)
                x2, y2 = min(1024, x2 + 30), min(1024, y2 + 30)
                recorded_box = np.asarray([[x1, y1, x2, y2]], dtype=np.float32)
                crop_w, crop_h = x2 - x1, y2 - y1
                if crop_w >= 20 and crop_h >= 20:
                    person_found = True
                    crop = cv2.cvtColor(prepared[y1:y2, x1:x2], cv2.COLOR_BGR2RGB)
                    keypoints = api.extract_from_crop(
                        crop, pose, x1, y1, crop_w, crop_h, 1024, 1024
                    )

                    if current_action == "Nga!":
                        if last_global_kpts is not None:
                            movement = np.mean(np.linalg.norm(keypoints - last_global_kpts, axis=1))
                            if movement > 0.1:
                                current_action = "Khong nga"
                                for event in pending_events:
                                    event["cancelled"] = True
                        last_global_kpts = keypoints
                    else:
                        last_global_kpts = keypoints

                    for event in pending_events:
                        if event["cancelled"]:
                            continue
                        elapsed = now - event["time"]
                        if elapsed < 2.0:
                            event["last_raw_kpts"] = keypoints
                        elif elapsed < 3.0:
                            if event["pred"] == "Nga!" and event["last_raw_kpts"] is not None:
                                movement = np.mean(
                                    np.linalg.norm(keypoints - event["last_raw_kpts"], axis=1)
                                )
                                if movement > 0.1:
                                    event["cancelled"] = True
                            event["last_raw_kpts"] = keypoints

            trace.boxes.append(recorded_box)
            trace.poses.append(keypoints.copy())
            kpts_buffer.append(keypoints)
            timestamp_buffer.append(now)
            frame_ids.append(frame_id)

            if not person_found:
                for event in pending_events:
                    event["cancelled"] = True
                if current_action == "Nga!":
                    current_action = "Khong nga"

            if timestamp_buffer and now - timestamp_buffer[0] >= 2.0:
                raw = api.resample_frames(np.asarray(kpts_buffer), target_frames=64)
                value = api.clean_out_of_bounds_data(raw)
                value = api.normalize_skeleton_dynamic(value)
                value = value - value[:, 0:1, :]
                value = api.normalize_pose(value)
                value = api.interpolate_missing(value)
                value = api.apply_kalman_filter(value)
                model_input = value.transpose(2, 0, 1)[:, :, :, np.newaxis]
                tensor = torch.FloatTensor(model_input).unsqueeze(0)
                with torch.no_grad():
                    output = action_model(tensor)
                    predicted = int(torch.argmax(torch.softmax(output, dim=1).squeeze()).item())
                trace.window_ids.append(list(frame_ids))
                trace.model_inputs.append(model_input.copy())
                trace.logits.append(output.detach().cpu().numpy().copy())
                trace.classes.append(predicted)
                pending_events.append(
                    {
                        "time": now,
                        "pred": "Nga!" if predicted == 1 else "Khong nga",
                        "cancelled": False,
                        "last_raw_kpts": raw[-1] if predicted == 1 else None,
                    }
                )
                while timestamp_buffer and now - timestamp_buffer[0] > 1.0:
                    timestamp_buffer.pop(0)
                    kpts_buffer.pop(0)
                    frame_ids.pop(0)

            active = []
            for event in pending_events:
                if event["cancelled"]:
                    continue
                if now - event["time"] >= 3.0:
                    previous = current_action
                    current_action = event["pred"]
                    if current_action != previous:
                        trace.transitions.append({"frame_id": frame_id, "action": current_action})
                else:
                    active.append(event)
            pending_events = active
    finally:
        capture.release()
        pose.close()
    return trace


def _arrays(left: list[np.ndarray], right: list[np.ndarray]) -> dict[str, Any]:
    if len(left) != len(right):
        return {"equal": False, "left_count": len(left), "right_count": len(right)}
    for index, (first, second) in enumerate(zip(left, right, strict=True)):
        if first.shape != second.shape:
            return {"equal": False, "first_divergence": index, "reason": "shape"}
        if not np.array_equal(first, second):
            return {
                "equal": False,
                "first_divergence": index,
                "reason": "value",
                "max_abs": float(np.max(np.abs(first - second))),
            }
    return {"equal": True, "max_abs": 0.0}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", type=Path, default=Path("frontend/public/videos/kich_ban3.mp4"))
    parser.add_argument("--frames", type=int, default=300)
    parser.add_argument("--output", type=Path, default=Path("data/runtimev2-oracle-parity.json"))
    args = parser.parse_args()
    video = args.video if args.video.is_absolute() else PROJECT_ROOT / args.video
    oracle = load_oracle_module()
    config_path = ORACLE_ROOT / "work_dir" / "fall_detection" / "joint" / "config.yaml"
    weights_path = ORACLE_ROOT / "work_dir" / "fall_detection" / "joint" / "runs-best_val.pt"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    oracle_model = load_oracle_cpu_model(config, weights_path)
    portable_model = load_action_model(
        config,
        weights_path,
        RuntimeSelection(
            requested="cpu",
            profile="cpu",
            torch_device=torch.device("cpu"),
            detector_runtime="pytorch:cpu",
            action_runtime="pytorch:cpu",
            face_providers=("CPUExecutionProvider",),
        ),
    )
    reference = trace_video(video, args.frames, oracle, oracle_model)
    candidate = trace_video(
        video,
        args.frames,
        portable,
        portable_model,
        replay_times=reference.observation_times,
    )
    comparisons = {
        "sampled_frames": reference.sampled_ids == candidate.sampled_ids,
        "detections": _arrays(reference.boxes, candidate.boxes),
        "poses": _arrays(reference.poses, candidate.poses),
        "temporal_windows": reference.window_ids == candidate.window_ids,
        "model_inputs": _arrays(reference.model_inputs, candidate.model_inputs),
        "logits": _arrays(reference.logits, candidate.logits),
        "classes": reference.classes == candidate.classes,
        "fall_decisions": reference.transitions == candidate.transitions,
    }
    first_divergence = None
    for name, value in comparisons.items():
        equal = value if isinstance(value, bool) else bool(value.get("equal"))
        if not equal:
            first_divergence = name
            break
    report = {
        "video": str(video.resolve()),
        "frames": args.frames,
        "shim": "EdgeConv.get_graph_feature: x.get_device() -> x.device only",
        "clock": "oracle observation times recorded then replayed; no Hz sampler",
        "assets": {
            "yolo_sha256": _sha256(ORACLE_ROOT / "yolov8n.pt"),
            "checkpoint_sha256": _sha256(weights_path),
        },
        "comparisons": comparisons,
        "first_divergence": first_divergence,
        "parity": first_divergence is None,
    }
    payload = json.dumps(report, indent=2)
    print(payload)
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(payload + "\n", encoding="utf-8")
    return 0 if report["parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
