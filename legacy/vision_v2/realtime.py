import cv2
import numpy as np
import os
import torch
import sys
import yaml
from collections import OrderedDict
from ultralytics import YOLO
from insightface.app import FaceAnalysis
import mediapipe as mp
import torch.nn.functional as F
import time
from collections import deque
from scipy.interpolate import interp1d
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from extractkpt.extractkpt import extract_from_crop, clean_out_of_bounds_data, normalize_skeleton_dynamic
from feeders.bone_pairs import ntu_pairs
from fusion.normalize_pose import normalize_pose
from fusion.interpolate import interpolate_missing
from fusion.kalman_filter import apply_kalman_filter

def import_class(import_str):
    mod_str, _sep, class_str = import_str.rpartition('.')
    __import__(mod_str)
    try:
        return getattr(sys.modules[mod_str], class_str)
    except AttributeError:
        raise ImportError(f'Class {class_str} cannot be found')

def resample_frames(kpts_array, target_frames=64):
    N, V, C = kpts_array.shape
    if N == target_frames:
        return kpts_array
    elif N == 0:
        return np.zeros((target_frames, V, C), dtype=np.float32)
    elif N == 1:
        return np.repeat(kpts_array, target_frames, axis=0)
    
    x_old = np.linspace(0, 1, N)
    x_new = np.linspace(0, 1, target_frames)
    kpts_flat = kpts_array.reshape(N, -1)
    f = interp1d(x_old, kpts_flat, axis=0, kind='linear', fill_value="extrapolate")
    resampled_flat = f(x_new)
    return resampled_flat.reshape(target_frames, V, C)

def compute_similarity(embedding1, embedding2):
    return np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))

def main():
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"[*] Sử dụng thiết bị: {device}")

    print("[*] Đang tải YOLOv8...")
    yolo_path = os.path.join(BASE_DIR, "yolov8n.pt")
    yolo_model = YOLO(yolo_path if os.path.exists(yolo_path) else "yolov8n.pt", verbose=False)
    yolo_model.to(device)

    print("[*] Đang khởi tạo InsightFace...")
    app = FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(640, 640))

    print("[*] Đang khởi tạo MediaPipe Pose...")
    mp_pose = mp.solutions.pose
    pose_model = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

    print("[*] Đang khởi tạo SDA-GCN (Fall Detection)...")
    config_path = os.path.join(BASE_DIR, 'work_dir', 'fall_detection', 'joint', 'config.yaml')
    weights_path = os.path.join(BASE_DIR, 'work_dir', 'fall_detection', 'joint', 'runs-best_val.pt')
    
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
        
    Model = import_class(config['model'])
    model_args = config.get('model_args', {})
    action_model = Model(**model_args).to(device)
    
    weights = torch.load(weights_path, map_location=device)
    weights = OrderedDict([[k.split('module.')[-1], v] for k, v in weights.items()])
    action_model.load_state_dict(weights, strict=False)
    action_model.eval()

    known_faces = {}
    data_dir = os.path.join(BASE_DIR, "register face")
    if os.path.exists(data_dir):
        print(f"[*] Đang đọc dữ liệu khuôn mặt từ '{data_dir}'...")
        for item in os.listdir(data_dir):
            item_path = os.path.join(data_dir, item)
            if os.path.isdir(item_path):
                name = item
                embeddings = []
                for filename in os.listdir(item_path):
                    if filename.endswith(('.jpg', '.png', '.jpeg')):
                        img_path = os.path.join(item_path, filename)
                        img = cv2.imread(img_path)
                        faces = app.get(img)
                        if len(faces) > 0:
                            embeddings.append(faces[0].embedding)
                if len(embeddings) > 0:
                    known_faces[name] = np.mean(embeddings, axis=0)
            elif item.endswith(('.jpg', '.png', '.jpeg')):
                name = os.path.splitext(item)[0]
                img_path = os.path.join(data_dir, item)
                img = cv2.imread(img_path)
                faces = app.get(img)
                if len(faces) > 0:
                    known_faces[name] = faces[0].embedding

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("[LỖI] Không thể mở camera!")
        return

    # Cố định kích thước video theo yêu cầu
    orig_w = 1024
    orig_h = 1024
    
    window_size = 64
    kpts_buffer = []
    timestamp_buffer = []
    
    current_action = "Waiting for frames..."
    action_color = (255, 255, 255)
    
    pending_events = []
    last_global_kpts = None
    MOVEMENT_THRESHOLD = 0.1

    # Smart Face Recognition Tracking Cache
    tracked_faces = {}  # { track_id: {"name": str, "score": float, "status": str, "attempts": int, "last_attempt_time": float} }
    MAX_RECOG_ATTEMPTS = 5
    THROTTLE_INTERVAL = 1.0  # Thời gian chờ giữa các lần thử nhận diện người lạ (giây)
    
    print("[*] Hệ thống đã sẵn sàng. Bấm 'q' để thoát.")

    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        h, w = frame.shape[:2]
        scale = 1024 / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        frame = cv2.resize(frame, (new_w, new_h))
        pad_w, pad_h = 1024 - new_w, 1024 - new_h
        frame = cv2.copyMakeBorder(frame, pad_h // 2, pad_h - pad_h // 2, pad_w // 2, pad_w - pad_w // 2, cv2.BORDER_CONSTANT, value=(0, 0, 0))

        frame_count += 1
        if frame_count % 2 == 0:
            continue

        # A. YOLO DETECT & TRACKING
        results = yolo_model.track(frame, persist=True, classes=0, verbose=False)
        person_found = False

        if results[0].boxes is not None and len(results[0].boxes) > 0:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            best_idx = np.argmax((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]))
            x1, y1, x2, y2 = map(int, boxes[best_idx])
            
            # Lấy track_id nếu YOLO tracking cấp id
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
                
                # B. FACE RECOGNITION (SMART CACHING WITH YOLO TRACKING)
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
                            "last_attempt_time": 0.0
                        }
                    
                    info = tracked_faces[track_id]
                    if info["status"] == "RECOGNIZED":
                        # Đã nhận diện được trước đó -> BỎ QUA INSIGHTFACE!
                        name_display = f"{info['name']} ({info['score']:.2f})"
                        face_color = (0, 255, 0)
                    elif info["status"] == "LOCKED_UNKNOWN":
                        # Đã thử tối đa số lần cho người lạ -> BỎ QUA INSIGHTFACE!
                        name_display = "Unknown"
                        face_color = (0, 0, 255)
                    else: # PENDING
                        now = time.time()
                        if (now - info["last_attempt_time"] >= THROTTLE_INTERVAL) and (info["attempts"] < MAX_RECOG_ATTEMPTS):
                            should_run_insightface = True
                        else:
                            name_display = "Unknown"
                            face_color = (0, 0, 255)
                else:
                    should_run_insightface = True

                if should_run_insightface:
                    faces = app.get(crop_frame)
                    now = time.time()
                    if track_id is not None:
                        tracked_faces[track_id]["attempts"] += 1
                        tracked_faces[track_id]["last_attempt_time"] = now

                    if len(faces) > 0:
                        main_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                        best_score = 0
                        best_name = "Unknown"
                        for name, known_emb in known_faces.items():
                            score = compute_similarity(known_emb, main_face.embedding)
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
                        else:
                            name_display = "Unknown"
                            face_color = (0, 0, 255)
                            if track_id is not None and tracked_faces[track_id]["attempts"] >= MAX_RECOG_ATTEMPTS:
                                tracked_faces[track_id]["status"] = "LOCKED_UNKNOWN"
                    else:
                        name_display = "Unknown"
                        face_color = (0, 0, 255)
                        if track_id is not None and tracked_faces[track_id]["attempts"] >= MAX_RECOG_ATTEMPTS:
                            tracked_faces[track_id]["status"] = "LOCKED_UNKNOWN"

                # Dọn dẹp cache nếu danh sách quá lớn
                if len(tracked_faces) > 100:
                    for k in list(tracked_faces.keys())[:-50]:
                        del tracked_faces[k]

                cv2.rectangle(frame, (x1, y1), (x2, y2), face_color, 2)
                id_str = f" [ID:{track_id}]" if track_id is not None else ""
                cv2.putText(frame, f"{name_display}{id_str}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, face_color, 2)
                
                # C. EXTRACT KEYPOINTS (MEDIAPIPE)
                crop_rgb = cv2.cvtColor(crop_frame, cv2.COLOR_BGR2RGB)
                kpts = extract_from_crop(crop_rgb, pose_model, x1, y1, crop_w, crop_h, orig_w, orig_h)
                kpts_buffer.append(kpts)
                timestamp_buffer.append(time.time())
                
                if current_action == "Nga!":
                    if last_global_kpts is not None:
                        movement = np.mean(np.linalg.norm(kpts - last_global_kpts, axis=1))
                        if movement > MOVEMENT_THRESHOLD:
                            current_action = "Khong nga"
                            action_color = (0, 255, 0)
                            for event in pending_events:
                                event["cancelled"] = True
                    last_global_kpts = kpts
                else:
                    last_global_kpts = kpts
                    
                for event in pending_events:
                    if event["cancelled"]: continue
                    elapsed = time.time() - event["time"]
                    if elapsed < 2.0:
                        event["last_raw_kpts"] = kpts
                    elif elapsed < 3.0:
                        if event["pred"] == "Nga!" and event["last_raw_kpts"] is not None:
                            movement = np.mean(np.linalg.norm(kpts - event["last_raw_kpts"], axis=1))
                            if movement > MOVEMENT_THRESHOLD:
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

        # D. FALL DETECTION INFERENCE (Time-based sliding window 2s)
        if len(timestamp_buffer) > 0 and (time.time() - timestamp_buffer[0] >= 2.0):
            raw_array = np.array(kpts_buffer)
            raw_array = resample_frames(raw_array, target_frames=window_size)
            cleaned_array = clean_out_of_bounds_data(raw_array)
            normalized_array = normalize_skeleton_dynamic(cleaned_array)
            
            kpt = normalized_array - normalized_array[:, 0:1, :]
            kpt = normalize_pose(kpt)
            kpt = interpolate_missing(kpt)
            kpt = apply_kalman_filter(kpt)
            
            data_numpy = kpt.transpose(2, 0, 1) 
            data_numpy = data_numpy[:, :, :, np.newaxis] 

            data_tensor = torch.FloatTensor(data_numpy).unsqueeze(0).to(device) 
            
            with torch.no_grad():
                output = action_model(data_tensor)
                prob = F.softmax(output, dim=1).squeeze()
                pred_idx = torch.argmax(prob).item()
                
                if pred_idx == 1:
                    pending_events.append({"time": time.time(), "pred": "Nga!", "cancelled": False, "last_raw_kpts": raw_array[-1]})
                else:
                    pending_events.append({"time": time.time(), "pred": "Khong nga", "cancelled": False, "last_raw_kpts": None})
            
            current_time = time.time()
            while len(timestamp_buffer) > 0 and (current_time - timestamp_buffer[0] > 1.0):
                timestamp_buffer.pop(0)
                kpts_buffer.pop(0)
                
        active_events = []
        for event in pending_events:
            if event["cancelled"]: continue
            if time.time() - event["time"] >= 3.0:
                current_action = event["pred"]
                action_color = (0, 0, 255) if current_action == "Nga!" else (0, 255, 0)
            else:
                active_events.append(event)
        pending_events = active_events
        
        cv2.putText(frame, f"Action: {current_action}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, action_color, 2)
        cv2.putText(frame, f"Buffer: {len(kpts_buffer)} frames / 2.0s", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        
        cv2.imshow("Realtime Fall Detection & Face Recognition", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
