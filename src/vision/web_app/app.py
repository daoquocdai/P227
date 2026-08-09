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
from flask import Flask, render_template, Response, jsonify

# Khởi tạo thư mục gốc (lùi 1 cấp vì đang ở trong web_app)
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from src.vision.extractkpt.extractkpt import extract_from_crop, clean_out_of_bounds_data, normalize_skeleton_dynamic
from src.vision.feeders.bone_pairs import ntu_pairs
from src.vision.fusion.normalize_pose import normalize_pose
from src.vision.fusion.interpolate import interpolate_missing
from src.vision.fusion.kalman_filter import apply_kalman_filter

app_flask = Flask(__name__)

# Biến toàn cục lưu trạng thái
global_status = {
    "action": "Waiting for frames...",
    "person_name": "Unknown"
}

def import_class(import_str):
    mod_str, _sep, class_str = import_str.rpartition('.')
    __import__(mod_str)
    try:
        return getattr(sys.modules[mod_str], class_str)
    except AttributeError:
        raise ImportError(f'Class {class_str} cannot be found')

def compute_similarity(embedding1, embedding2):
    return np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))

# ==========================================
# 1. KHỞI TẠO CÁC MÔ HÌNH (Chạy 1 lần)
# ==========================================
device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f"[*] Sử dụng thiết bị: {device}")

print("[*] Đang tải YOLOv8...")
yolo_model = YOLO(os.path.join(parent_dir, "yolov8n.pt"), verbose=False)
yolo_model.to(device)

print("[*] Đang khởi tạo InsightFace...")
app_face = FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'], root=parent_dir)
app_face.prepare(ctx_id=0, det_size=(640, 640))

print("[*] Đang khởi tạo MediaPipe Pose...")
mp_pose = mp.solutions.pose
pose_model = mp_pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

print("[*] Đang khởi tạo SDA-GCN (Fall Detection)...")
config_path = os.path.join(parent_dir, 'work_dir/fall_detection/ntu25-bone/config.yaml')
weights_path = os.path.join(parent_dir, 'work_dir/fall_detection/ntu25-bone/runs-best_val.pt')

with open(config_path, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
    
Model = import_class(config['model'])
model_args = config.get('model_args', {})
action_model = Model(**model_args).to(device)

weights = torch.load(weights_path, map_location=device, weights_only=False)
weights = OrderedDict([[k.split('module.')[-1], v] for k, v in weights.items()])
action_model.load_state_dict(weights, strict=False)
action_model.eval()

# ==========================================
# 2. TẢI DỮ LIỆU KHUÔN MẶT
# ==========================================
known_faces = {}
data_dir = os.path.join(parent_dir, "register face")
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
                    faces = app_face.get(img)
                    if len(faces) > 0:
                        embeddings.append(faces[0].embedding)
            if len(embeddings) > 0:
                known_faces[name] = np.mean(embeddings, axis=0)

def generate_frames():
    global global_status
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    
    # Cố định kích thước video
    orig_w = 1024
    orig_h = 1024
    
    window_size = 64
    stride = 32
    kpts_buffer = deque(maxlen=window_size)
    
    current_action = "Waiting for frames..."
    action_color = (255, 255, 255)
    
    pending_fall = False
    fall_start_time = 0
    last_raw_kpts = None
    MOVEMENT_THRESHOLD = 0.2
    
    frame_count = 0
    while True:
        ret, frame = cap.read()
        if not ret: break
        
        # Đổi kích cỡ frame thành 1024x1024 không làm méo (Letterbox)
        h, w = frame.shape[:2]
        scale = 1024 / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        frame = cv2.resize(frame, (new_w, new_h))
        pad_w, pad_h = 1024 - new_w, 1024 - new_h
        frame = cv2.copyMakeBorder(frame, pad_h // 2, pad_h - pad_h // 2, pad_w // 2, pad_w - pad_w // 2, cv2.BORDER_CONSTANT, value=(0, 0, 0))

        frame_count += 1
        if frame_count % 2 == 0:
            continue

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
                faces = app_face.get(crop_frame)
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
                        global_status["person_name"] = name_display
                        name_display = f"{name_display} ({best_score:.2f})"
                    else:
                        global_status["person_name"] = "Unknown"
                        name_display = "Unknown"

                cv2.rectangle(frame, (x1, y1), (x2, y2), face_color, 2)
                cv2.putText(frame, name_display, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, face_color, 2)
                
                crop_rgb = cv2.cvtColor(crop_frame, cv2.COLOR_BGR2RGB)
                kpts = extract_from_crop(crop_rgb, pose_model, x1, y1, crop_w, crop_h, orig_w, orig_h)
                kpts_buffer.append(kpts)
                
                if pending_fall or current_action == "FALL DETECTED!":
                    if last_raw_kpts is not None:
                        movement = np.mean(np.linalg.norm(kpts - last_raw_kpts, axis=1))
                        if movement > MOVEMENT_THRESHOLD:
                            pending_fall = False
                            current_action = "Normal"
                    last_raw_kpts = kpts

        if not person_found:
            kpts_buffer.append(np.zeros((25, 3), dtype=np.float32))
            pending_fall = False
            if current_action == "FALL DETECTED!":
                current_action = "Normal"

        if len(kpts_buffer) == window_size:
            raw_array = np.array(kpts_buffer)
            
            cleaned_array = clean_out_of_bounds_data(raw_array)
            normalized_array = normalize_skeleton_dynamic(cleaned_array)
            
            kpt = normalized_array - normalized_array[:, 0:1, :]
            kpt = normalize_pose(kpt)
            kpt = interpolate_missing(kpt)
            kpt = apply_kalman_filter(kpt)
            
            data_numpy = kpt.transpose(2, 0, 1)
            data_numpy = data_numpy[:, :, :, np.newaxis]
            
            bone_data = np.zeros_like(data_numpy)
            for v1, v2 in ntu_pairs:
                bone_data[:, :, v1] = data_numpy[:, :, v1] - data_numpy[:, :, v2]
                
            data_tensor = torch.FloatTensor(bone_data).unsqueeze(0).to(device)
            
            with torch.no_grad():
                output = action_model(data_tensor)
                prob = F.softmax(output, dim=1).squeeze()
                pred_idx = torch.argmax(prob).item()
                
                if pred_idx == 1:
                    if not pending_fall and current_action != "FALL DETECTED!":
                        pending_fall = True
                        fall_start_time = time.time()
                        last_raw_kpts = raw_array[-1]
                else:
                    pending_fall = False
                    current_action = "Normal"
            
            for _ in range(stride):
                kpts_buffer.popleft()
                
        if pending_fall:
            if time.time() - fall_start_time >= 2.0:
                current_action = "FALL DETECTED!"
                pending_fall = False
            else:
                current_action = "Normal"
        
        # Cập nhật global_status cho Web
        global_status["action"] = current_action
        
        # Encode frame để gửi stream qua HTTP
        ret, buffer = cv2.imencode('.jpg', frame)
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')

@app_flask.route('/')
def index():
    return render_template('index.html')

@app_flask.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app_flask.route('/status')
def status():
    return jsonify(global_status)

if __name__ == '__main__':
    app_flask.run(host='0.0.0.0', port=5000, debug=False, threaded=True)
