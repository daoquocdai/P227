import cv2
import numpy as np
import os
import torch
import sys
import yaml
from collections import OrderedDict
from insightface.app import FaceAnalysis
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import torch.nn.functional as F
import time
import requests
import uuid
from datetime import datetime, timezone
import threading
from flask import Flask, Response
from scipy.interpolate import interp1d
import logging

# Append local path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Đã bỏ hàm extract_from_crop cũ, chỉ giữ lại clean_out_of_bounds_data
from extractkpt.extractkpt import clean_out_of_bounds_data
from feeders.bone_pairs import ntu_pairs
from fusion.normalize_pose import normalize_pose
from fusion.interpolate import interpolate_missing
from fusion.kalman_filter import apply_kalman_filter

app_flask = Flask(__name__)
latest_frame = None

def generate_frames():
    global latest_frame
    while True:
        if latest_frame is None:
            time.sleep(0.1)
            continue
        ret, buffer = cv2.imencode('.jpg', latest_frame)
        if not ret:
            continue
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
        time.sleep(0.03)

@app_flask.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

def run_flask():
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app_flask.run(host='0.0.0.0', port=8001, debug=False, use_reloader=False)

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


# ==============================
# HÀM TRÍCH XUẤT KEYPOINTS MỚI (Từ toàn khung hình MediaPipe)
# ==============================
def extract_from_landmarks(landmarks):
    TOTAL_JOINTS = 25
    keypoints = np.zeros((TOTAL_JOINTS, 3), dtype=np.float32)
    
    def get_pt(idx):
        return np.array([landmarks[idx].x, landmarks[idx].y, landmarks[idx].z], dtype=np.float32)

    keypoints[0] = (get_pt(23) + get_pt(24)) / 2.0     
    keypoints[20] = (get_pt(11) + get_pt(12)) / 2.0    
    keypoints[1] = (keypoints[0] + keypoints[20]) / 2.0 
    keypoints[2] = (get_pt(0) + keypoints[20]) / 2.0    
    keypoints[3] = get_pt(0)                            

    keypoints[4] = get_pt(11) 
    keypoints[5] = get_pt(13) 
    keypoints[6] = get_pt(15) 
    keypoints[7] = (get_pt(17) + get_pt(19)) / 2.0 
    keypoints[21] = get_pt(19) 
    keypoints[22] = get_pt(21) 

    keypoints[8] = get_pt(12)  
    keypoints[9] = get_pt(14)  
    keypoints[10] = get_pt(16) 
    keypoints[11] = (get_pt(18) + get_pt(20)) / 2.0 
    keypoints[23] = get_pt(20) 
    keypoints[24] = get_pt(22) 

    keypoints[12] = get_pt(23) 
    keypoints[13] = get_pt(25) 
    keypoints[14] = get_pt(27) 
    keypoints[15] = get_pt(31) 
    
    keypoints[16] = get_pt(24) 
    keypoints[17] = get_pt(26) 
    keypoints[18] = get_pt(28) 
    keypoints[19] = get_pt(32) 

    return keypoints


class FallDetectionSystem:
    def __init__(self):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"[*] Sử dụng thiết bị: {self.device}")
        
        self.app = None
        self.pose_model = None
        self.action_model = None
        self.known_faces = {}
        
        self.last_sent_time = {}
        
        # Biến lưu trữ kết quả Tracking bất đồng bộ từ MediaPipe
        self.latest_pose_result = None
        
        # States
        self.kpts_buffer = []
        self.timestamp_buffer = []
        self.current_action = "Waiting for frames..."
        self.action_color = (255, 255, 255)
        
        # Constants
        self.orig_w = 1280
        self.orig_h = 720
        self.window_size = 64
        self.BACKEND_URL = "http://127.0.0.1:8000/api/v1/vision/events"
        
        self.track_identities = {}
        self.track_last_face_check = {}
        self.frame_count = 0

    # Hàm Callback nhận dữ liệu từ luồng nền của MediaPipe
    def _pose_callback(self, result: vision.PoseLandmarkerResult, output_image: mp.Image, timestamp_ms: int):
        self.latest_pose_result = result

    def init_models(self):
        print("[*] Đang khởi tạo InsightFace...")
        self.app = FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        self.app.prepare(ctx_id=0, det_size=(640, 640))

        print("[*] Đang khởi tạo MediaPipe Pose (LIVE_STREAM mode)...")
        # CHÚ Ý: ĐỔI ĐƯỜNG DẪN FILE .TASK Ở ĐÂY
        model_path = 'pose_landmarker_full.task' 
        
        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.LIVE_STREAM,
            result_callback=self._pose_callback,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_tracking_confidence=0.5
        )
        self.pose_model = vision.PoseLandmarker.create_from_options(options)

        print("[*] Đang khởi tạo SDA-GCN (Fall Detection)...")
        config_path = 'work_dir/fall_detection/fall/config.yaml'
        weights_path = 'work_dir/fall_detection/fall/runs-best_val.pt'
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            
        Model = import_class(config['model'])
        model_args = config.get('model_args', {})
        self.action_model = Model(**model_args).to(self.device)
        
        weights = torch.load(weights_path, map_location=self.device)
        weights = OrderedDict([[k.split('module.')[-1], v] for k, v in weights.items()])
        self.action_model.load_state_dict(weights, strict=False)
        self.action_model.eval()
        
    def load_known_faces(self, data_dir="register face"):
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
                            faces = self.app.get(img)
                            if len(faces) > 0:
                                embeddings.append(faces[0].embedding)
                    if len(embeddings) > 0:
                        self.known_faces[name] = np.mean(embeddings, axis=0)
                elif item.endswith(('.jpg', '.png', '.jpeg')):
                    name = os.path.splitext(item)[0]
                    img_path = os.path.join(data_dir, item)
                    img = cv2.imread(img_path)
                    faces = self.app.get(img)
                    if len(faces) > 0:
                        self.known_faces[name] = faces[0].embedding

    def send_event_to_backend(self, event_type, confidence=0.9, identity_status="UNKNOWN", identity_name=None):
        throttle_key = f"{event_type}_{identity_name}"
        now = time.time()
        if now - self.last_sent_time.get(throttle_key, 0) < 5.0:
            return
        self.last_sent_time[throttle_key] = now
        
        data = {
            "event_id": str(uuid.uuid4()),
            "camera_id": "fb61abc0-a568-499e-a95f-9fc824edd3a5",
            "camera_location": "SDA-GCN External AI",
            "event_type": event_type,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "confidence": float(confidence),
            "identity_status": identity_status,
            "identity_name": identity_name
        }
        
        def post_request():
            try:
                requests.post(self.BACKEND_URL, json=data, timeout=2)
            except Exception as e:
                print(f"[CẢNH BÁO] Không thể gửi sự kiện tới Backend: {e}")
                
        threading.Thread(target=post_request, daemon=True).start()

    def process_person(self, frame, x1, y1, x2, y2, track_id):
        crop_w, crop_h = x2 - x1, y2 - y1
        crop_frame = frame[y1:y2, x1:x2]
        
        name_display = "Unknown"
        face_color = (0, 0, 255)
        
        if track_id != -1 and track_id in self.track_identities:
            name_display = self.track_identities[track_id]["name"]
            best_score = self.track_identities[track_id]["score"]
            face_color = (0, 255, 0)
            name_display = f"{name_display} ({best_score:.2f})"
        else:
            if track_id not in self.track_last_face_check or (self.frame_count - self.track_last_face_check.get(track_id, 0) >= 15):
                faces = self.app.get(crop_frame)
                if len(faces) > 0:
                    main_face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                    best_score = 0
                    for name, known_emb in self.known_faces.items():
                        score = compute_similarity(known_emb, main_face.embedding)
                        if score > best_score:
                            best_score = score
                            name_display = name
                    
                    if best_score > 0.45:
                        face_color = (0, 255, 0)
                        if track_id != -1:
                            self.track_identities[track_id] = {"name": name_display, "score": best_score}
                        self.send_event_to_backend("PERSON_RECOGNIZED", best_score, "KNOWN", name_display)
                        name_display = f"{name_display} ({best_score:.2f})"
                    else:
                        self.send_event_to_backend("UNKNOWN_PERSON", 0.9, "UNKNOWN")
                        name_display = "Unknown"
                
                if track_id != -1:
                    self.track_last_face_check[track_id] = self.frame_count

        cv2.rectangle(frame, (x1, y1), (x2, y2), face_color, 2)
        cv2.putText(frame, name_display, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, face_color, 2)
        
    def detect_fall(self):
        if len(self.timestamp_buffer) > 0 and (time.time() - self.timestamp_buffer[0] >= 2.0):
            raw_array = np.array(self.kpts_buffer)
            
            kpt = clean_out_of_bounds_data(raw_array)
            kpt = interpolate_missing(kpt)
            kpt = kpt - kpt[:, 0:1, :] 
            kpt = normalize_pose(kpt)
            kpt = apply_kalman_filter(kpt)
            kpt = resample_frames(kpt, target_frames=self.window_size)
            
            data_numpy = kpt.transpose(2, 0, 1) 
            data_numpy = data_numpy[:, :, :, np.newaxis] 

            data_tensor = torch.FloatTensor(data_numpy).unsqueeze(0).to(self.device) 
            
            with torch.no_grad():
                output = self.action_model(data_tensor)
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
            
            current_time = time.time()
            while len(self.timestamp_buffer) > 0 and (current_time - self.timestamp_buffer[0] > 1.0):
                self.timestamp_buffer.pop(0)
                self.kpts_buffer.pop(0)

    def run(self):
        print("[*] Đang kết nối trực tiếp tới Camera máy tính...")
        cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
        if not cap.isOpened():
            print("[LỖI] Không thể mở camera!")
            return

        print("[*] Hệ thống đã sẵn sàng. Truy cập stream tại: http://localhost:8001/video_feed")
        global latest_frame
        
        while True:
            ret, frame = cap.read()
            if not ret: break
            
            h, w = frame.shape[:2]
            scale = min(self.orig_w / w, self.orig_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
            frame = cv2.resize(frame, (new_w, new_h))
            
            pad_w = self.orig_w - new_w
            pad_h = self.orig_h - new_h
            frame = cv2.copyMakeBorder(frame, pad_h // 2, pad_h - pad_h // 2, pad_w // 2, pad_w - pad_w // 2, cv2.BORDER_CONSTANT, value=(0, 0, 0))

            self.frame_count += 1
            
            # 1. Gửi Frame vào luồng MediaPipe (Bất đồng bộ)
            # 1. Gửi Frame vào luồng MediaPipe (Bất đồng bộ)
            timestamp_ms = int(time.time() * 1000)
            
            # Ép buộc thời gian phải luôn tăng (Monotonically increasing)
            if not hasattr(self, 'last_timestamp_ms'):
                self.last_timestamp_ms = 0
            if timestamp_ms <= self.last_timestamp_ms:
                timestamp_ms = self.last_timestamp_ms + 1
            self.last_timestamp_ms = timestamp_ms

            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            self.pose_model.detect_async(mp_image, timestamp_ms)

            # 2. Xử lý dữ liệu từ kết quả Tracking mới nhất
            person_found = False
            
            if self.latest_pose_result and self.latest_pose_result.pose_landmarks:
                person_found = True
                landmarks = self.latest_pose_result.pose_landmarks[0]
                
                # Trích xuất 25 điểm khớp
                kpts = extract_from_landmarks(landmarks)
                
                # Tính toán Bounding Box từ các điểm khớp (dùng cho InsightFace)
                xs = [lm.x for lm in landmarks]
                ys = [lm.y for lm in landmarks]
                x_min, x_max = min(xs), max(xs)
                y_min, y_max = min(ys), max(ys)
                
                pad = 30
                x1 = max(0, int(x_min * self.orig_w) - pad)
                y1 = max(0, int(y_min * self.orig_h) - pad)
                x2 = min(self.orig_w, int(x_max * self.orig_w) + pad)
                y2 = min(self.orig_h, int(y_max * self.orig_h) + pad)
                
                # Gắn track_id = 1 giả lập (Vì MediaPipe LIVE_STREAM mặc định track 1 người xuyên suốt)
                if (x2 - x1) >= 20 and (y2 - y1) >= 20:
                    self.process_person(frame, x1, y1, x2, y2, track_id=1)
                
                # Đưa vào buffer
                self.kpts_buffer.append(kpts)
                self.timestamp_buffer.append(time.time())

            # 3. Nếu MediaPipe mất dấu người
            if not person_found:
                if len(self.kpts_buffer) > 0:
                    last_kpts = self.kpts_buffer[-1].copy()
                else:
                    last_kpts = np.zeros((25, 3), dtype=np.float32)
                
                self.kpts_buffer.append(last_kpts)
                self.timestamp_buffer.append(time.time())
                
                self.current_action = "Khong nga (Lost)"
                self.action_color = (0, 255, 0)

            # 4. Gọi SDA-GCN
            self.detect_fall()
            
            # 5. Vẽ thông tin lên màn hình
            cv2.putText(frame, f"Action: {self.current_action}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, self.action_color, 2)
            cv2.putText(frame, f"Buffer: {len(self.kpts_buffer)} frames / 2.0s", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            latest_frame = frame.copy()

        cap.release()
        self.pose_model.close()
        cv2.destroyAllWindows()

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    system = FallDetectionSystem()
    system.init_models()
    system.load_known_faces()
    system.run()

if __name__ == "__main__":
    main()