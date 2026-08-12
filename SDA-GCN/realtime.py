import cv2
import numpy as np
import os
import torch
import sys
import yaml
from collections import OrderedDict, deque
from ultralytics import YOLO
from insightface.app import FaceAnalysis
import mediapipe as mp
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

from extractkpt.extractkpt import extract_from_crop, clean_out_of_bounds_data, normalize_skeleton_dynamic
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

class FallDetectionSystem:
    def __init__(self):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        print(f"[*] Sử dụng thiết bị: {self.device}")
        
        self.yolo_model = None
        self.app = None
        self.pose_model = None
        self.action_model = None
        self.known_faces = {}
        
        self.last_sent_time = {}
        
        # States
        self.kpts_buffer = []
        self.timestamp_buffer = []
        self.current_action = "Waiting for frames..."
        self.action_color = (255, 255, 255)
        self.pending_events = []
        self.last_global_kpts = None
        
        # Constants
        self.orig_w = 1024
        self.orig_h = 1024
        self.window_size = 64
        self.MOVEMENT_THRESHOLD = 0.1
        self.BACKEND_URL = "http://127.0.0.1:8000/api/v1/vision/events"
        
        self.track_identities = {}
        self.track_last_face_check = {}
        self.frame_count = 0

    def init_models(self):
        print("[*] Đang tải YOLOv8...")
        self.yolo_model = YOLO("yolov8n.pt", verbose=False)
        self.yolo_model.to(self.device)

        print("[*] Đang khởi tạo InsightFace...")
        self.app = FaceAnalysis(name='buffalo_l', providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        self.app.prepare(ctx_id=0, det_size=(640, 640))

        print("[*] Đang khởi tạo MediaPipe Pose...")
        self.pose_model = mp.solutions.pose.Pose(min_detection_confidence=0.5, min_tracking_confidence=0.5)

        print("[*] Đang khởi tạo SDA-GCN (Fall Detection)...")
        config_path = 'work_dir/fall_detection/joint/config.yaml'
        weights_path = 'work_dir/fall_detection/joint/runs-best_val.pt'
        
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
        
        # Face Recognition with Tracking Cache
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
        
        # Extract Keypoints
        crop_rgb = cv2.cvtColor(crop_frame, cv2.COLOR_BGR2RGB)
        kpts = extract_from_crop(crop_rgb, self.pose_model, x1, y1, crop_w, crop_h, self.orig_w, self.orig_h)
        self.kpts_buffer.append(kpts)
        self.timestamp_buffer.append(time.time())
        
        # Movement tracking to cancel false falls
        if self.current_action == "Nga!":
            if self.last_global_kpts is not None:
                movement = np.mean(np.linalg.norm(kpts - self.last_global_kpts, axis=1))
                if movement > self.MOVEMENT_THRESHOLD:
                    self.current_action = "Khong nga"
                    self.action_color = (0, 255, 0)
                    for event in self.pending_events:
                        event["cancelled"] = True
            self.last_global_kpts = kpts
        else:
            self.last_global_kpts = kpts
            
        for event in self.pending_events:
            if event["cancelled"]: continue
            elapsed = time.time() - event["time"]
            if elapsed < 2.0:
                event["last_raw_kpts"] = kpts
            elif elapsed < 3.0:
                if event["pred"] == "Nga!" and event["last_raw_kpts"] is not None:
                    movement = np.mean(np.linalg.norm(kpts - event["last_raw_kpts"], axis=1))
                    if movement > self.MOVEMENT_THRESHOLD:
                        event["cancelled"] = True
                event["last_raw_kpts"] = kpts

    def detect_fall(self):
        if len(self.timestamp_buffer) > 0 and (time.time() - self.timestamp_buffer[0] >= 2.0):
            raw_array = np.array(self.kpts_buffer)
            raw_array = resample_frames(raw_array, target_frames=self.window_size)
            cleaned_array = clean_out_of_bounds_data(raw_array)
            normalized_array = normalize_skeleton_dynamic(cleaned_array)
            
            kpt = normalized_array - normalized_array[:, 0:1, :]
            kpt = normalize_pose(kpt)
            kpt = interpolate_missing(kpt)
            kpt = apply_kalman_filter(kpt)
            
            data_numpy = kpt.transpose(2, 0, 1) 
            data_numpy = data_numpy[:, :, :, np.newaxis] 

            data_tensor = torch.FloatTensor(data_numpy).unsqueeze(0).to(self.device) 
            
            with torch.no_grad():
                output = self.action_model(data_tensor)
                prob = F.softmax(output, dim=1).squeeze()
                pred_idx = torch.argmax(prob).item()
                
                if pred_idx == 1:
                    self.pending_events.append({"time": time.time(), "pred": "Nga!", "cancelled": False, "last_raw_kpts": raw_array[-1]})
                    self.send_event_to_backend("FALL_CONFIRMED", float(prob[1]))
                else:
                    self.pending_events.append({"time": time.time(), "pred": "Khong nga", "cancelled": False, "last_raw_kpts": None})
            
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
            scale = self.orig_w / max(h, w)
            new_w, new_h = int(w * scale), int(h * scale)
            frame = cv2.resize(frame, (new_w, new_h))
            pad_w, pad_h = self.orig_w - new_w, self.orig_h - new_h
            frame = cv2.copyMakeBorder(frame, pad_h // 2, pad_h - pad_h // 2, pad_w // 2, pad_w - pad_w // 2, cv2.BORDER_CONSTANT, value=(0, 0, 0))

            self.frame_count += 1
            if self.frame_count % 2 == 0:
                continue

            results = self.yolo_model.track(frame, persist=True, classes=0, verbose=False)
            person_found = False

            if results[0].boxes is not None and len(results[0].boxes) > 0:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                best_idx = np.argmax((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1]))
                x1, y1, x2, y2 = map(int, boxes[best_idx])
                
                track_id = -1
                if results[0].boxes.id is not None:
                    track_id = int(results[0].boxes.id[best_idx].item())
                
                pad = 30
                x1, y1 = max(0, x1 - pad), max(0, y1 - pad)
                x2, y2 = min(self.orig_w, x2 + pad), min(self.orig_h, y2 + pad)
                
                if (x2 - x1) >= 20 and (y2 - y1) >= 20:
                    person_found = True
                    self.process_person(frame, x1, y1, x2, y2, track_id)

            if not person_found:
                self.kpts_buffer.append(np.zeros((25, 3), dtype=np.float32))
                self.timestamp_buffer.append(time.time())
                for event in self.pending_events:
                    event["cancelled"] = True
                if self.current_action == "Nga!":
                    self.current_action = "Khong nga"
                    self.action_color = (0, 255, 0)

            self.detect_fall()
            
            # Update active events
            active_events = []
            for event in self.pending_events:
                if event["cancelled"]: continue
                if time.time() - event["time"] >= 3.0:
                    self.current_action = event["pred"]
                    self.action_color = (0, 0, 255) if self.current_action == "Nga!" else (0, 255, 0)
                else:
                    active_events.append(event)
            self.pending_events = active_events
            
            cv2.putText(frame, f"Action: {self.current_action}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, self.action_color, 2)
            cv2.putText(frame, f"Buffer: {len(self.kpts_buffer)} frames / 2.0s", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
            
            latest_frame = frame.copy()

        cap.release()
        cv2.destroyAllWindows()

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    
    system = FallDetectionSystem()
    system.init_models()
    system.load_known_faces()
    system.run()

if __name__ == "__main__":
    main()
