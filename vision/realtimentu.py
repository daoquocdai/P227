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
import csv

# Khởi tạo thư mục gốc
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

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

def compute_similarity(embedding1, embedding2):
    return np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))

def main():
    device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
    print(f"[*] Sử dụng thiết bị: {device}")

    # ==========================================
    # 1. KHỞI TẠO CÁC MÔ HÌNH
    # ==========================================
    print("[*] Đang tải YOLOv8...")
    yolo_model = YOLO("yolov8n.pt", verbose=False)
    yolo_model.to(device)

    print("[*] Đang khởi tạo InsightFace...")
    app = FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
    app.prepare(ctx_id=0, det_size=(640, 640))

    print("[*] Đang khởi tạo MediaPipe Pose...")
    mp_pose = mp.solutions.pose
    pose_model = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

    print("[*] Đang khởi tạo SDA-GCN (Fall Detection 120 Classes)...")
    # Sử dụng model huấn luyện trên bone như yêu cầu
    config_path = 'work_dir/fall_detection/ntu25/config.yaml'
    weights_path = 'work_dir/fall_detection/ntu25/runs.pt'

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)

    Model = import_class(config['model'])
    model_args = config.get('model_args', {})
    action_model = Model(**model_args).to(device)

    weights = torch.load(weights_path, map_location=device)
    weights = OrderedDict([[k.split('module.')[-1], v] for k, v in weights.items()])

    # Đã chuyển thành strict=True để đảm bảo load chuẩn 120 classes và 2 persons (150 features)
    action_model.load_state_dict(weights, strict=True)
    action_model.eval()

    # ==========================================
    # 2. TẢI DỮ LIỆU CLASS NAME TỪ LOOKUP TABLE
    # ==========================================
    class_map = {}
    csv_path = 'lookuptable.csv'
    if os.path.exists(csv_path):
        with open(csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                class_map[int(row['index'])] = f"{int(row['index']) + 1}/120: {row['action_name']}"
    else:
        print(f"[CẢNH BÁO] Không tìm thấy file {csv_path}, sẽ chỉ hiển thị index.")

    # ==========================================
    # 3. TẢI DỮ LIỆU KHUÔN MẶT
    # ==========================================
    known_faces = {}
    data_dir = "register face"
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

    # ==========================================
    # 3. MỞ WEBCAM & PIPELINE REAL-TIME
    # ==========================================
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print("[LỖI] Không thể mở camera!")
        return

    cam_fps = cap.get(cv2.CAP_PROP_FPS)
    if cam_fps <= 0 or np.isnan(cam_fps):
        cam_fps = 30 # fallback

    # Tính số frame cần bỏ qua để quy về 30 FPS
    frame_skip = max(1, int(round(cam_fps / 30.0)))
    print(f"[*] Camera FPS: {cam_fps} -> Xử lý cách mỗi {frame_skip} frame (để đạt mốc 30 FPS)")

    orig_w = 1024
    orig_h = 1024

    window_size = 64
    stride = 32
    kpts_buffer = deque(maxlen=window_size)

    current_action = "Waiting for frames..."
    action_color = (255, 255, 255)

    print("[*] Hệ thống đã sẵn sàng. Bấm 'q' để thoát.")

    frame_count = 0
    prev_time = time.time()
    display_fps = 0.0

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

        # Bỏ qua frame để quy về chuẩn 30 FPS
        if frame_count % frame_skip != 0:
            continue

        # Tính FPS
        curr_time = time.time()
        elapsed = curr_time - prev_time
        if elapsed > 0:
            # Dùng trung bình động (EMA) để chỉ số FPS đỡ bị giật
            display_fps = display_fps * 0.9 + (1.0 / elapsed) * 0.1
        prev_time = curr_time

        results = yolo_model.track(frame, persist=True, classes=0, verbose=False)
        person_found = False

        if results[0].boxes is not None and len(results[0].boxes) > 0:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            best_idx = np.argmax((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]))
            x1, y1, x2, y2 = map(int, boxes[best_idx])

            pad = 30
            x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
            x2, y2 = min(orig_w, x2 + pad), min(orig_h, y2 + pad)

            crop_w, crop_h = x2 - x1, y2 - y1
            if crop_w >= 20 and crop_h >= 20:
                person_found = True
                crop_frame = frame[y1:y2, x1:x2]

                name_display = "Unknown"
                face_color = (0, 0, 255)
                faces = app.get(crop_frame)
                if len(faces) > 0:
                    main_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                    best_score = 0
                    for name, known_emb in known_faces.items():
                        score = compute_similarity(known_emb, main_face.embedding)
                        if score > best_score:
                            best_score = score
                            name_display = name

                    if best_score > 0.45:
                        face_color = (0, 255, 0)
                        name_display = f"{name_display} ({best_score:.2f})"
                    else:
                        name_display = "Unknown"

                cv2.rectangle(frame, (x1, y1), (x2, y2), face_color, 2)
                cv2.putText(frame, name_display, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, face_color, 2)

                crop_rgb = cv2.cvtColor(crop_frame, cv2.COLOR_BGR2RGB)
                kpts = extract_from_crop(crop_rgb, pose_model, x1, y1, crop_w, crop_h, orig_w, orig_h)
                kpts_buffer.append(kpts)

        if not person_found:
            kpts_buffer.append(np.zeros((25, 3), dtype=np.float32))
            if current_action == "FALL DETECTED!":
                current_action = "Normal"
                action_color = (0, 255, 0)

        # D. FALL DETECTION INFERENCE (Sliding window)
        if len(kpts_buffer) == window_size:
            raw_array = np.array(kpts_buffer) # Shape: (64, 25, 3)

            cleaned_array = clean_out_of_bounds_data(raw_array)
            normalized_array = normalize_skeleton_dynamic(cleaned_array)

            kpt = normalized_array - normalized_array[:, 0:1, :]
            kpt = normalize_pose(kpt)
            kpt = interpolate_missing(kpt)
            kpt = apply_kalman_filter(kpt)

            data_numpy = kpt.transpose(2, 0, 1) # (3, 64, 25)
            data_numpy = data_numpy[:, :, :, np.newaxis] # (3, 64, 25, 1)

            # Pad thêm người thứ 2 (để tạo kích thước M=2 phù hợp với file weights chuẩn NTU)
            data_numpy = np.pad(data_numpy, ((0,0), (0,0), (0,0), (0,1)), mode='constant') # (3, 64, 25, 2)

            # Tính toán ma trận Bone cho cả 2 người
            bone_data = np.zeros_like(data_numpy)
            for v1, v2 in ntu_pairs:
                bone_data[:, :, v1, :] = data_numpy[:, :, v1, :] - data_numpy[:, :, v2, :]

            data_tensor = torch.FloatTensor(bone_data).unsqueeze(0).to(device) # Shape: (1, 3, 64, 25, 2)

            with torch.no_grad():
                output = action_model(data_tensor)
                prob = F.softmax(output, dim=1).squeeze()

                # Lấy Top 5 dự đoán để in ra màn hình console (giúp bạn debug xem nó đang đoán thành cái gì)
                top5_prob, top5_idx = torch.topk(prob, 5)
                top5_prob = top5_prob.tolist()
                top5_idx = top5_idx.tolist()

                print(f"\n--- Kết quả dự đoán ---")
                for i in range(5):
                    c_name = class_map.get(top5_idx[i], f"Class {top5_idx[i]}")
                    print(f"Top {i+1}: {c_name} (Xác suất: {top5_prob[i]*100:.2f}%)")

                # Vẫn giữ logic ưu tiên nếu hành động ngã (index 42) nằm trong Top 3
                if 42 in top5_idx[:3]:
                    current_action = "43/120: FALL DETECTED!"
                    action_color = (0, 0, 255)
                else:
                    # Lấy hành động có xác suất cao nhất (Top 1) để hiển thị
                    best_idx = top5_idx[0]
                    action_name = class_map.get(best_idx, f"Class {best_idx}")
                    current_action = f"{action_name}"
                    action_color = (0, 255, 0)

            for _ in range(stride):
                kpts_buffer.popleft()

        cv2.putText(frame, f"Action: {current_action}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, action_color, 2)
        cv2.putText(frame, f"Buffer: {len(kpts_buffer)}/{window_size}", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, f"FPS: {display_fps:.1f}", (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        cv2.imshow("Realtime Fall Detection (120 Classes) & Face Recognition", frame)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
