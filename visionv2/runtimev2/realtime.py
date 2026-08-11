import argparse
import json
import os
import sys
import time
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
import torch
import torch.nn.functional as functional
import yaml
from insightface.app import FaceAnalysis
from scipy.interpolate import interp1d
from ultralytics import YOLO

BASE_DIR = Path(__file__).resolve().parent
ORACLE_DIR = BASE_DIR.parent / "P-227-thi"
PROJECT_ROOT = BASE_DIR.parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(ORACLE_DIR) not in sys.path:
    sys.path.append(str(ORACLE_DIR))

from extractkpt.extractkpt import (  # noqa: E402
    clean_out_of_bounds_data,
    extract_from_crop,
    normalize_skeleton_dynamic,
)
from fusion.interpolate import interpolate_missing  # noqa: E402
from fusion.kalman_filter import apply_kalman_filter  # noqa: E402
from fusion.normalize_pose import normalize_pose  # noqa: E402

from visionv2.runtimev2.hardware import (  # noqa: E402
    detector_source,
    load_action_model,
    select_runtime,
)


def resample_frames(kpts_array, target_frames=64):
    n, vertices, channels = kpts_array.shape
    if n == target_frames:
        return kpts_array
    if n == 0:
        return np.zeros((target_frames, vertices, channels), dtype=np.float32)
    if n == 1:
        return np.repeat(kpts_array, target_frames, axis=0)

    x_old = np.linspace(0, 1, n)
    x_new = np.linspace(0, 1, target_frames)
    kpts_flat = kpts_array.reshape(n, -1)
    function = interp1d(x_old, kpts_flat, axis=0, kind="linear", fill_value="extrapolate")
    return function(x_new).reshape(target_frames, vertices, channels)


def compute_similarity(embedding1, embedding2):
    return np.dot(embedding1, embedding2) / (
        np.linalg.norm(embedding1) * np.linalg.norm(embedding2)
    )


def build_parser():
    parser = argparse.ArgumentParser(
        description="Hardware-only portable port of the original VisionV2 preview."
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--video", type=Path, help="Video path instead of the default camera.")
    source.add_argument("--camera", type=int, default=0, help="Camera index (default: 0).")
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "intel", "cpu"),
        default="auto",
        help="Execution backend; auto prefers CUDA, then Intel GPU, then CPU.",
    )
    parser.add_argument(
        "--identity",
        action="store_true",
        default=True,
        help="Keep original InsightFace behavior (enabled by default).",
    )
    parser.add_argument("--max-frames", type=int, help=argparse.SUPPRESS)
    return parser


def _open_capture(args):
    if args.video is not None:
        path = args.video.expanduser().resolve()
        return cv2.VideoCapture(str(path)), str(path)
    if os.name == "nt":
        return cv2.VideoCapture(args.camera, cv2.CAP_DSHOW), f"camera:{args.camera}"
    return cv2.VideoCapture(args.camera), f"camera:{args.camera}"


def run(args):
    selection = select_runtime(args.device)
    print(f"[*] Sử dụng thiết bị: {selection.profile}")

    print("[*] Đang tải YOLOv8...")
    yolo_path = ORACLE_DIR / "yolov8n.pt"
    yolo_model = YOLO(str(detector_source(yolo_path, selection, YOLO)), verbose=False)
    if selection.profile == "intel":
        # Select only the exported model's execution backend; keep the oracle
        # track(frame, persist=True, classes=0, verbose=False) call unchanged.
        yolo_model.overrides["device"] = "intel:gpu"
    else:
        yolo_model.to(selection.torch_device)

    print("[*] Đang khởi tạo InsightFace...")
    app = FaceAnalysis(name="buffalo_l", providers=list(selection.face_providers))
    app.prepare(ctx_id=0, det_size=(640, 640))

    print("[*] Đang khởi tạo MediaPipe Pose...")
    mp_pose = mp.solutions.pose
    pose_model = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

    print("[*] Đang khởi tạo SDA-GCN (Fall Detection)...")
    config_path = ORACLE_DIR / "work_dir" / "fall_detection" / "joint" / "config.yaml"
    weights_path = ORACLE_DIR / "work_dir" / "fall_detection" / "joint" / "runs-best_val.pt"
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    action_model = load_action_model(config, weights_path, selection)

    known_faces = {}
    data_dir = ORACLE_DIR / "register face"
    if data_dir.exists():
        print(f"[*] Đang đọc dữ liệu khuôn mặt từ '{data_dir}'...")
        for item in os.listdir(data_dir):
            item_path = data_dir / item
            if item_path.is_dir():
                embeddings = []
                for filename in os.listdir(item_path):
                    if filename.endswith((".jpg", ".png", ".jpeg")):
                        image_path = item_path / filename
                        image = cv2.imread(str(image_path))
                        faces = app.get(image)
                        if len(faces) > 0:
                            embeddings.append(faces[0].embedding)
                if len(embeddings) > 0:
                    known_faces[item] = np.mean(embeddings, axis=0)
            elif item.endswith((".jpg", ".png", ".jpeg")):
                image = cv2.imread(str(item_path))
                faces = app.get(image)
                if len(faces) > 0:
                    known_faces[os.path.splitext(item)[0]] = faces[0].embedding

    capture, source_name = _open_capture(args)
    if not capture.isOpened():
        raise RuntimeError(f"Không thể mở input: {source_name}")

    orig_w = 1024
    orig_h = 1024
    window_size = 64
    kpts_buffer = []
    timestamp_buffer = []
    current_action = "Waiting for frames..."
    action_color = (255, 255, 255)
    pending_events = []
    last_global_kpts = None
    movement_threshold = 0.1
    tracked_faces = {}
    max_recog_attempts = 5
    throttle_interval = 1.0

    print(json.dumps({"runtime": selection.to_dict()}, indent=2))
    print("[*] Hệ thống đã sẵn sàng. Bấm 'q' để thoát.")

    frame_count = 0
    sampled_frame_ids = []
    predictions = []
    fall_transitions = []
    try:
        while args.max_frames is None or frame_count < args.max_frames:
            success, frame = capture.read()
            if not success:
                break

            height, width = frame.shape[:2]
            scale = 1024 / max(height, width)
            new_w, new_h = int(width * scale), int(height * scale)
            frame = cv2.resize(frame, (new_w, new_h))
            pad_w, pad_h = 1024 - new_w, 1024 - new_h
            frame = cv2.copyMakeBorder(
                frame,
                pad_h // 2,
                pad_h - pad_h // 2,
                pad_w // 2,
                pad_w - pad_w // 2,
                cv2.BORDER_CONSTANT,
                value=(0, 0, 0),
            )

            frame_count += 1
            if frame_count % 2 == 0:
                continue
            sampled_frame_ids.append(frame_count - 1)

            results = yolo_model.track(frame, persist=True, classes=0, verbose=False)
            person_found = False

            if results[0].boxes is not None and len(results[0].boxes) > 0:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                best_idx = np.argmax((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]))
                x1, y1, x2, y2 = map(int, boxes[best_idx])
                track_id = None
                if results[0].boxes.id is not None:
                    track_ids = results[0].boxes.id.cpu().numpy().astype(int)
                    track_id = int(track_ids[best_idx])

                pad = 30
                x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
                x2, y2 = min(orig_w, x2 + pad), min(orig_h, y2 + pad)
                crop_w, crop_h = x2 - x1, y2 - y1
                if crop_w >= 20 and crop_h >= 20:
                    person_found = True
                    crop_frame = frame[y1:y2, x1:x2]
                    name_display = "Unknown"
                    face_color = (0, 0, 255)
                    should_run_insightface = False

                    if track_id is not None:
                        if track_id not in tracked_faces:
                            tracked_faces[track_id] = {
                                "name": None,
                                "score": 0.0,
                                "status": "PENDING",
                                "attempts": 0,
                                "last_attempt_time": 0.0,
                            }
                        info = tracked_faces[track_id]
                        if info["status"] == "RECOGNIZED":
                            name_display = f"{info['name']} ({info['score']:.2f})"
                            face_color = (0, 255, 0)
                        elif info["status"] == "LOCKED_UNKNOWN":
                            name_display = "Unknown"
                            face_color = (0, 0, 255)
                        else:
                            now = time.time()
                            if (
                                now - info["last_attempt_time"] >= throttle_interval
                                and info["attempts"] < max_recog_attempts
                            ):
                                should_run_insightface = True
                    else:
                        should_run_insightface = True

                    if should_run_insightface:
                        faces = app.get(crop_frame)
                        now = time.time()
                        if track_id is not None:
                            tracked_faces[track_id]["attempts"] += 1
                            tracked_faces[track_id]["last_attempt_time"] = now
                        if faces:
                            main_face = max(
                                faces,
                                key=lambda face: (face.bbox[2] - face.bbox[0])
                                * (face.bbox[3] - face.bbox[1]),
                            )
                            best_score = 0
                            best_name = "Unknown"
                            for name, known_embedding in known_faces.items():
                                score = compute_similarity(known_embedding, main_face.embedding)
                                if score > best_score:
                                    best_score = score
                                    best_name = name
                            if best_score > 0.45:
                                face_color = (0, 255, 0)
                                name_display = f"{best_name} ({best_score:.2f})"
                                if track_id is not None:
                                    tracked_faces[track_id]["name"] = best_name
                                    tracked_faces[track_id]["score"] = best_score
                                    tracked_faces[track_id]["status"] = "RECOGNIZED"
                            elif track_id is not None and tracked_faces[track_id]["attempts"] >= max_recog_attempts:
                                tracked_faces[track_id]["status"] = "LOCKED_UNKNOWN"
                        elif track_id is not None and tracked_faces[track_id]["attempts"] >= max_recog_attempts:
                            tracked_faces[track_id]["status"] = "LOCKED_UNKNOWN"

                    if len(tracked_faces) > 100:
                        for key in list(tracked_faces.keys())[:-50]:
                            del tracked_faces[key]

                    cv2.rectangle(frame, (x1, y1), (x2, y2), face_color, 2)
                    id_string = f" [ID:{track_id}]" if track_id is not None else ""
                    cv2.putText(
                        frame,
                        f"{name_display}{id_string}",
                        (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        face_color,
                        2,
                    )

                    crop_rgb = cv2.cvtColor(crop_frame, cv2.COLOR_BGR2RGB)
                    kpts = extract_from_crop(
                        crop_rgb, pose_model, x1, y1, crop_w, crop_h, orig_w, orig_h
                    )
                    kpts_buffer.append(kpts)
                    timestamp_buffer.append(time.time())

                    if current_action == "Nga!":
                        if last_global_kpts is not None:
                            movement = np.mean(np.linalg.norm(kpts - last_global_kpts, axis=1))
                            if movement > movement_threshold:
                                current_action = "Khong nga"
                                action_color = (0, 255, 0)
                                for event in pending_events:
                                    event["cancelled"] = True
                        last_global_kpts = kpts
                    else:
                        last_global_kpts = kpts

                    for event in pending_events:
                        if event["cancelled"]:
                            continue
                        elapsed = time.time() - event["time"]
                        if elapsed < 2.0:
                            event["last_raw_kpts"] = kpts
                        elif elapsed < 3.0:
                            if event["pred"] == "Nga!" and event["last_raw_kpts"] is not None:
                                movement = np.mean(
                                    np.linalg.norm(kpts - event["last_raw_kpts"], axis=1)
                                )
                                if movement > movement_threshold:
                                    event["cancelled"] = True
                            event["last_raw_kpts"] = kpts

            if not person_found:
                kpts_buffer.append(np.zeros((25, 3), dtype=np.float32))
                timestamp_buffer.append(time.time())
                for event in pending_events:
                    event["cancelled"] = True
                if current_action == "Nga!":
                    current_action = "Khong nga"
                    action_color = (0, 255, 0)

            if timestamp_buffer and time.time() - timestamp_buffer[0] >= 2.0:
                raw_array = np.array(kpts_buffer)
                raw_array = resample_frames(raw_array, target_frames=window_size)
                cleaned_array = clean_out_of_bounds_data(raw_array)
                normalized_array = normalize_skeleton_dynamic(cleaned_array)
                keypoint = normalized_array - normalized_array[:, 0:1, :]
                keypoint = normalize_pose(keypoint)
                keypoint = interpolate_missing(keypoint)
                keypoint = apply_kalman_filter(keypoint)
                data_numpy = keypoint.transpose(2, 0, 1)
                data_numpy = data_numpy[:, :, :, np.newaxis]
                data_tensor = torch.FloatTensor(data_numpy).unsqueeze(0).to(selection.torch_device)

                with torch.no_grad():
                    output = action_model(data_tensor)
                    probability = functional.softmax(output, dim=1).squeeze()
                    pred_idx = torch.argmax(probability).item()
                    predictions.append(pred_idx)
                    if pred_idx == 1:
                        pending_events.append(
                            {
                                "time": time.time(),
                                "pred": "Nga!",
                                "cancelled": False,
                                "last_raw_kpts": raw_array[-1],
                            }
                        )
                    else:
                        pending_events.append(
                            {
                                "time": time.time(),
                                "pred": "Khong nga",
                                "cancelled": False,
                                "last_raw_kpts": None,
                            }
                        )

                current_time = time.time()
                while timestamp_buffer and current_time - timestamp_buffer[0] > 1.0:
                    timestamp_buffer.pop(0)
                    kpts_buffer.pop(0)

            active_events = []
            for event in pending_events:
                if event["cancelled"]:
                    continue
                if time.time() - event["time"] >= 3.0:
                    previous_action = current_action
                    current_action = event["pred"]
                    action_color = (0, 0, 255) if current_action == "Nga!" else (0, 255, 0)
                    if current_action != previous_action:
                        fall_transitions.append({"frame": frame_count - 1, "action": current_action})
                else:
                    active_events.append(event)
            pending_events = active_events

            cv2.putText(
                frame,
                f"Action: {current_action}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                action_color,
                2,
            )
            cv2.putText(
                frame,
                f"Buffer: {len(kpts_buffer)} frames / 2.0s",
                (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )
            cv2.imshow("Realtime Fall Detection & Face Recognition", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()

    return {
        "frames_read": frame_count,
        "sampled_frames": len(sampled_frame_ids),
        "prediction_count": len(predictions),
        "class_counts": {
            str(class_id): predictions.count(class_id) for class_id in sorted(set(predictions))
        },
        "fall_transitions": fall_transitions,
        "runtime": selection.to_dict(),
    }


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        report = run(args)
    except (RuntimeError, ValueError) as error:
        print(f"[LỖI] {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
