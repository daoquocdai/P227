import cv2
import numpy as np
import os
os.environ.setdefault('GLOG_minloglevel', '2')
import torch
import sys
import yaml
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import torch.nn.functional as F
import time
import uuid
from datetime import datetime, timezone
import threading
from flask import Flask, Response
from scipy.interpolate import interp1d
import logging
import warnings
warnings.filterwarnings("ignore", message=r"SymbolDatabase.GetPrototype\(\) is deprecated")
import argparse
import onnxruntime as ort
from collections import deque

from runtime.hardware import BackendResolutionError, resolve_backend
from runtime.inference import ActionInference, StageSpec, choose_onnx_providers, print_diagnostics
from runtime.events import EventSender
from runtime.identity import IdentityStage, IdentityState
from runtime.pipeline import FixedRateScheduler
from runtime.source import SourceKind, create_source, parse_source
from runtime.timing import (LatestPoseStore, MediaPipeTimestampAdapter, PosePacket,
                            PoseSample, PoseSubmission, source_span_s)

# Append local path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Đã bỏ hàm extract_from_crop cũ, chỉ giữ lại clean_out_of_bounds_data
from extractkpt.common.cleaning import clean_out_of_bounds_data
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

@app_flask.route('/')
def preview_page():
    return '<!doctype html><title>Vision Preview</title><img src="/video_feed" style="max-width:100%;height:auto">'

def run_flask():
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    app_flask.run(host='127.0.0.1', port=8001, debug=False, use_reloader=False)

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
    def __init__(self, device_mode="auto", preview="window", backend_url=None, identity="on",
                 vision_fps=15.0, identity_interval=0.5, face_det_size=416,
                 rebuild_face_cache=False, log_level="info", identity_debug=False,
                 source_spec=None, source_fps=None):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.backend = resolve_backend(device_mode)
        self.preview = preview
        self.event_sender = EventSender(backend_url)
        self.identity_enabled = identity == "on"
        self.target_vision_fps = vision_fps
        self.identity_interval = identity_interval
        self.face_det_size = face_det_size
        self.rebuild_face_cache = rebuild_face_cache
        self.log_level = log_level
        self.identity_debug = identity_debug
        self.source_spec = source_spec or parse_source("0")
        self.source_fps_override = source_fps
        self.identity_stage = None
        self.frame_source = None
        
        self.app = None
        self.pose_model = None
        self.action_model = None
        self.pose_stage = StageSpec("Pose", "MediaPipe", "CPU", "fp32", "MediaPipe Tasks Python does not expose an OpenVINO provider")
        self.face_stage = None
        self.known_faces = {}
        
        self.last_sent_time = {}
        self.pose_store = LatestPoseStore()
        self.pose_timestamp_adapter = MediaPipeTimestampAdapter()
        self._last_pose_sequence = 0
        
        # States
        self.pose_samples = deque()
        self.current_action = "Waiting for frames..."
        self.action_color = (255, 255, 255)
        
        # BỘ ĐẾM SỰ KIỆN HARDCODE (HÀNG CHỜ)
        self.pending_event = None
        
        # Constants
        self.orig_w = 1280
        self.orig_h = 720
        self.window_size = 64
        
        self.frame_count = 0
        self.pose_inference_ms = 0.0
        self.total_vision_ms = 0.0
        self.effective_fps = 0.0
        self._pose_submissions = {}
        self.current_sda_gcn_ms = None
        self.current_identity_ms = None
        self._last_identity_event_timestamp = 0.0
        self._gallery_status_logged = False

    def _pose_callback(self, result: vision.PoseLandmarkerResult, output_image: mp.Image, timestamp_ms: int):
        submission = self._pose_submissions.pop(timestamp_ms, None)
        if submission is not None:
            latency = (time.perf_counter() - submission.submitted_perf_counter_s) * 1000.0
            self.pose_inference_ms = latency
            self.pose_store.publish(PosePacket(submission.source_time_s, submission.frame_sequence,
                                               result, latency, submission.frame))

    def init_models(self):
        if self.identity_enabled:
            print("[*] Đang khởi tạo Identity worker...")
            providers, self.face_stage = choose_onnx_providers(self.backend, ort.get_available_providers())
            self.identity_stage = IdentityStage(
                providers, os.path.join(self.base_dir, "register face"),
                os.path.join(self.base_dir, "work_dir/identity_cache/identity_gallery.npz"),
                det_size=self.face_det_size, interval=self.identity_interval,
                rebuild_cache=self.rebuild_face_cache, debug=self.log_level == "debug",
                identity_debug=self.identity_debug,
            )
            self.identity_stage.start()
        else:
            self.face_stage = StageSpec("Face", "DISABLED", "", "n/a")

        print("[*] Đang khởi tạo MediaPipe Pose (LIVE_STREAM mode)...")
        model_path = os.path.join(self.base_dir, 'pose_landmarker_full.task')
        
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
        config_path = os.path.join(self.base_dir, 'work_dir/fall_detection/fall/config.yaml')
        weights_path = os.path.join(self.base_dir, 'work_dir/fall_detection/fall/runs-best_val.pt')
        
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
            
        Model = import_class(config['model'])
        model_args = config.get('model_args', {})
        self.action_model = ActionInference(
            Model(**model_args), weights_path, self.backend,
            os.path.join(self.base_dir, 'work_dir/runtime_cache'),
        )
        print_diagnostics(self.backend, self.pose_stage, self.action_model.stage, self.face_stage)
        print(f"Identity        : {'ENABLED' if self.identity_enabled else 'DISABLED'}")
        if self.identity_enabled:
            print(f"Identity rate   : <= {1.0 / self.identity_interval:.1f} Hz")
            print(f"Face det size   : {self.face_det_size}x{self.face_det_size}")
        preview_label = {'window': 'OpenCV Window', 'web': 'Web MJPEG', 'none': 'DISABLED'}[self.preview]
        print(f"Preview         : {preview_label}")
        if self.event_sender.enabled:
            print(f"Event Backend   : {self.event_sender.backend_url}")
            print("Event Delivery  : asynchronous (bounded queue)\n")
        else:
            print("Event Backend   : DISABLED (standalone)\n")
        print(f"Model init      : {self.action_model.model_initialize_ms:.1f} ms")
        print(f"Model warmup    : {self.action_model.model_warmup_ms:.1f} ms\n")
        
    def load_known_faces(self, data_dir=None):
        # Identity worker owns model initialization and registered embeddings.
        return

    def send_event_to_backend(self, event_type, confidence=0.9, identity_status="UNKNOWN", identity_name=None):
        throttle_key = f"{event_type}_{identity_name}"
        now = time.monotonic()
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
        
        self.event_sender.enqueue(data)

    def process_person(self, frame, x1, y1, x2, y2, track_id, frame_sequence=None,
                       source_time_s=None, overlay_frame=None):
        overlay_frame = frame if overlay_frame is None else overlay_frame
        if not self.identity_enabled:
            cv2.rectangle(overlay_frame, (x1, y1), (x2, y2), (255, 255, 0), 2)
            return
        crop_frame = frame[y1:y2, x1:x2]
        processed_before = self.identity_stage.frames_processed
        previous_state = self.identity_stage.result.state
        self.identity_stage.submit(crop_frame.copy(), (x1, y1, x2, y2),
                                   source_time_s=source_time_s, frame_sequence=frame_sequence)
        result = self.identity_stage.poll()
        if result.state != previous_state and self.log_level in {"debug", "info"}:
            detail = f" | {result.name} | similarity={result.confidence:.2f}" if result.name else ""
            print(f"[Identity] {previous_state.value} → {result.state.value}{detail}")
        if self.identity_stage.frames_processed != processed_before:
            self.current_identity_ms = result.inference_ms
            if result.timestamp != self._last_identity_event_timestamp:
                if result.state == IdentityState.LOCKED_KNOWN:
                    self.send_event_to_backend("PERSON_RECOGNIZED", result.confidence, "KNOWN", result.name)
                elif result.state == IdentityState.LOCKED_UNKNOWN:
                    self.send_event_to_backend("UNKNOWN_PERSON", 0.9, "UNKNOWN")
                self._last_identity_event_timestamp = result.timestamp
        name_display = result.state.value
        face_color = (0, 165, 255)
        if result.state == IdentityState.LOCKED_KNOWN:
            name_display = f"{result.name} ({result.confidence:.2f})"
            face_color = (0, 255, 0)
        elif result.state == IdentityState.LOCKED_UNKNOWN:
            name_display = "Unknown"
            face_color = (0, 0, 255)
        cv2.rectangle(overlay_frame, (x1, y1), (x2, y2), face_color, 2)
        cv2.putText(overlay_frame, name_display, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, face_color, 2)
        
    def detect_fall(self, current_source_time_s):
        # 1. LOGIC KIỂM DUYỆT (HARDCODE STATE MACHINE)
        if self.pending_event is not None and self.pose_samples:
            event = self.pending_event
            elapsed = current_source_time_s - event["started_source_time_s"]
            
            # Lấy raw keypoints ở frame hiện tại để làm thước đo tỷ lệ cơ thể
            current_kpts = self.pose_samples[-1].keypoints.copy()
            
            # Tính chiều dài lưng (Khoảng cách từ Cổ index 2 đến Hông index 0)
            torso_len = np.linalg.norm(current_kpts[2] - current_kpts[0])
            if torso_len < 1e-5: 
                torso_len = 1e-5

            # Hàm kiểm tra chuyển động chống pha loãng tín hiệu
            def has_moved(current, anchor, torso_length):
                # Tính khoảng cách xê dịch của toàn bộ 25 khớp
                diff = np.linalg.norm(current - anchor, axis=1) 
                
                # Màng lọc 1: Loại bỏ nhiễu tĩnh (< 15% torso)
                moved_joints = diff[diff > 0.15 * torso_length]
                
                # Màng lọc 2: Chốt hành động (Ít nhất 1 khớp xê dịch mạnh > 40% torso)
                if len(moved_joints) >= 1:
                    avg_movement = np.mean(moved_joints)
                    if avg_movement > 0.40 * torso_length:
                        return True
                return False

            # DÒNG THỜI GIAN CUỐN CHIẾU
            if elapsed >= 2.0 and event["state"] == "FALL_DETECTED":
                event["anchor_kpts"] = current_kpts
                event["state"] = "WARNING_PENDING"
                event["next_check_source_time_s"] = event["started_source_time_s"] + 3.0
                
            elif event["state"] == "WARNING_PENDING" and current_source_time_s >= event["next_check_source_time_s"]:
                if has_moved(current_kpts, event["anchor_kpts"], torso_len):
                    self.pending_event = None # Khớp xê dịch mạnh -> Bẻ lái hủy
                else:
                    event["state"] = "WARNING"
                    self.current_action = "Co the nga (Cho...)"
                    self.action_color = (0, 165, 255) # Cam
                    event["anchor_kpts"] = current_kpts
                    event["next_check_source_time_s"] = event["started_source_time_s"] + 5.0
                    
            elif event["state"] == "WARNING" and current_source_time_s >= event["next_check_source_time_s"]:
                if has_moved(current_kpts, event["anchor_kpts"], torso_len):
                    self.pending_event = None
                else:
                    event["state"] = "ALERT"
                    self.current_action = f"Nga! ({event['conf']:.2f})"
                    self.action_color = (0, 0, 255) # Đỏ
                    
                    # Phát API cảnh báo (Gửi duy nhất 1 lần ở Giây thứ 5.0)
                    self.send_event_to_backend("FALL_CONFIRMED", event["conf"])
                    
                    event["anchor_kpts"] = current_kpts
                    event["next_check_source_time_s"] = current_source_time_s + 2.0
                    
            elif event["state"] == "ALERT" and current_source_time_s >= event["next_check_source_time_s"]:
                # Cuốn chiếu kiểm tra mỗi 2 giây
                if has_moved(current_kpts, event["anchor_kpts"], torso_len):
                    self.pending_event = None
                else:
                    event["anchor_kpts"] = current_kpts
                    event["next_check_source_time_s"] = current_source_time_s + 2.0

            # Khôi phục trạng thái an toàn nếu bị hủy
            if self.pending_event is None:
                self.current_action = "Khong nga (Reset)"
                self.action_color = (0, 255, 0)
                
        # 2. LOGIC ĐÁNH LỬA AI (Chỉ chạy khi Hàng chờ trống)
        else:
            if source_span_s(self.pose_samples, current_source_time_s) >= 2.0:
                raw_array = np.array([sample.keypoints for sample in self.pose_samples])
                
                kpt = clean_out_of_bounds_data(raw_array)
                kpt = interpolate_missing(kpt)
                kpt = kpt - kpt[:, 0:1, :] 
                kpt = normalize_pose(kpt)
                kpt = apply_kalman_filter(kpt)
                kpt = resample_frames(kpt, target_frames=self.window_size)
                
                data_numpy = kpt.transpose(2, 0, 1) 
                data_numpy = data_numpy[:, :, :, np.newaxis] 

                data_tensor = torch.from_numpy(data_numpy).unsqueeze(0).float()

                with torch.inference_mode():
                    output = self.action_model(data_tensor)
                    self.current_sda_gcn_ms = self.action_model.last_inference_ms
                    prob = F.softmax(output, dim=1).squeeze()
                    pred_idx = torch.argmax(prob).item()
                    conf = float(prob[pred_idx]) 
                    
                    if pred_idx == 0: # AI Báo Ngã
                        # Cơ chế Lock-out: Bỏ sự kiện vào hàng chờ
                        self.pending_event = {
                            "started_source_time_s": current_source_time_s,
                            "state": "FALL_DETECTED",
                            "anchor_kpts": None,
                            "next_check_source_time_s": 0,
                            "conf": conf
                        }
                        self.current_action = f"Phat hien nga ({conf:.2f}) - Kiem tra..."
                        self.action_color = (0, 255, 255) # Vàng
                    else:
                        action_names = {1: "Dung", 2: "Cui", 3: "Ngoi", 4: "Nam"}
                        action_name = action_names.get(pred_idx, "Khong xac dinh")
                        self.current_action = f"{action_name} ({conf:.2f})"
                        self.action_color = (0, 255, 0) # Xanh

                # TRẢ VỀ ĐÚNG VỊ TRÍ CŨ TRONG CODE GỐC: Chỉ cắt buffer SAU KHI AI đã chạy
                while self.pose_samples and (current_source_time_s - self.pose_samples[0].source_time_s > 1.0):
                    self.pose_samples.popleft()

        # 3. CHỐNG TRÀN RAM (Bảo vệ dự phòng cho hệ thống)
        while self.pose_samples and (current_source_time_s - self.pose_samples[0].source_time_s > 2.5):
            self.pose_samples.popleft()

    def run(self):
        self.frame_source = create_source(self.source_spec, self.source_fps_override)
        self.frame_source.start()
        metadata = self.frame_source.metadata
        print("\n[Source]")
        print(f"Type          : {'Camera' if metadata.kind == SourceKind.CAMERA else 'Video'}")
        if metadata.kind == SourceKind.CAMERA:
            print(f"Index         : {self.source_spec.value}")
        else:
            print(f"File          : {metadata.name}")
        print(f"Resolution    : {metadata.width}x{metadata.height}")
        print(f"Source FPS    : {metadata.source_fps or 'unknown'}")
        if metadata.frame_count is not None:
            print(f"Frames        : {metadata.frame_count}")
            print(f"Duration      : {metadata.duration_s:.3f} s")
        print(f"Vision FPS    : {self.target_vision_fps}")
        print(f"Clock         : {metadata.timestamp_strategy}")
        if metadata.kind == SourceKind.VIDEO_FILE:
            print("Playback      : realtime")
        scheduler = FixedRateScheduler(self.target_vision_fps)
        last_capture_sequence = 0
        capture_dropped = 0

        if self.preview == "web":
            print("[*] Web preview: http://127.0.0.1:8001/")
        elif self.preview == "window":
            print("[*] OpenCV preview đã sẵn sàng. Nhấn q để thoát.")
        else:
            print("[*] Preview disabled; Vision inference đang chạy.")
        global latest_frame
        fps_window_started = time.perf_counter()
        fps_window_frames = 0
        sda_window_samples = []
        identity_window_samples = []
        
        while True:
            scheduler.wait()
            vision_started = time.perf_counter()
            snapshot = self.frame_source.store.wait_newer(last_capture_sequence, scheduler.interval)
            if snapshot is None or snapshot.sequence == last_capture_sequence:
                if self.frame_source.ended:
                    break
                continue
            capture_dropped += max(0, snapshot.sequence - last_capture_sequence - 1) if last_capture_sequence else 0
            last_capture_sequence = snapshot.sequence
            frame = snapshot.frame.copy()
            
            h, w = frame.shape[:2]
            scale = min(self.orig_w / w, self.orig_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
            frame = cv2.resize(frame, (new_w, new_h))
            
            pad_w = self.orig_w - new_w
            pad_h = self.orig_h - new_h
            frame = cv2.copyMakeBorder(frame, pad_h // 2, pad_h - pad_h // 2, pad_w // 2, pad_w - pad_w // 2, cv2.BORDER_CONSTANT, value=(0, 0, 0))

            self.frame_count += 1
            self.current_identity_ms = None
            if self.identity_stage and not self._gallery_status_logged:
                gallery = self.identity_stage.poll_status()
                if gallery:
                    print("\n[Identity Gallery]")
                    print(f"Persons         : {gallery['persons']}")
                    print(f"Images          : {gallery['images']}")
                    print(f"Cached          : {gallery['cached']}")
                    print(f"Recomputed      : {gallery['recomputed']}")
                    print(f"Skipped         : {gallery['skipped']}")
                    print(f"Load time       : {gallery['gallery_ms']:.0f} ms")
                    print(f"Identity ready  : {gallery['ready_ms']:.0f} ms")
                    self._gallery_status_logged = True
            
            timestamp_ms = self.pose_timestamp_adapter.convert(snapshot.source_time_s)

            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            self._pose_submissions[timestamp_ms] = PoseSubmission(
                snapshot.source_time_s, snapshot.sequence, time.perf_counter(), frame.copy())
            while len(self._pose_submissions) > 8:
                self._pose_submissions.pop(next(iter(self._pose_submissions)))
            self.pose_model.detect_async(mp_image, timestamp_ms)

            pose_packet = self.pose_store.latest()
            new_pose_packet = bool(pose_packet and pose_packet.frame_sequence > self._last_pose_sequence)
            if new_pose_packet:
                self._last_pose_sequence = pose_packet.frame_sequence
            if new_pose_packet and pose_packet.result.pose_landmarks:
                landmarks = pose_packet.result.pose_landmarks[0]
                
                kpts = extract_from_landmarks(landmarks)
                
                xs = [lm.x for lm in landmarks]
                ys = [lm.y for lm in landmarks]
                x_min, x_max = min(xs), max(xs)
                y_min, y_max = min(ys), max(ys)
                
                pad = 30
                x1 = max(0, int(x_min * self.orig_w) - pad)
                y1 = max(0, int(y_min * self.orig_h) - pad)
                x2 = min(self.orig_w, int(x_max * self.orig_w) + pad)
                y2 = min(self.orig_h, int(y_max * self.orig_h) + pad)
                
                if (x2 - x1) >= 20 and (y2 - y1) >= 20:
                    self.process_person(pose_packet.frame, x1, y1, x2, y2, track_id=None,
                                        frame_sequence=pose_packet.frame_sequence,
                                        source_time_s=pose_packet.source_time_s,
                                        overlay_frame=frame)
                
                self.pose_samples.append(PoseSample(pose_packet.source_time_s, kpts))

            elif new_pose_packet:
                if self.identity_stage:
                    identity_before = self.identity_stage.result
                    self.identity_stage.update_presence(None, pose_packet.source_time_s)
                    if identity_before.state != self.identity_stage.result.state and self.log_level in {"debug", "info"}:
                        label = identity_before.name or identity_before.state.value
                        print(f"[Identity] {label} left scene → reset")
                if self.pose_samples:
                    last_kpts = self.pose_samples[-1].keypoints.copy()
                else:
                    last_kpts = np.zeros((25, 3), dtype=np.float32)
                
                self.pose_samples.append(PoseSample(pose_packet.source_time_s, last_kpts))
                
                if self.pending_event is None:
                    self.current_action = "Khong nga (Lost)"
                    self.action_color = (0, 255, 0)

            self.current_sda_gcn_ms = None
            if self.pose_samples:
                self.detect_fall(self.pose_samples[-1].source_time_s)
            if self.current_sda_gcn_ms is not None:
                sda_window_samples.append(self.current_sda_gcn_ms)
            if self.current_identity_ms is not None:
                identity_window_samples.append(self.current_identity_ms)
            
            cv2.putText(frame, f"Action: {self.current_action}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, self.action_color, 2)
            cv2.putText(frame, f"Buffer: {len(self.pose_samples)} frames / 2.0s", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)

            self.total_vision_ms = (time.perf_counter() - vision_started) * 1000.0
            fps_window_frames += 1
            fps_elapsed = time.perf_counter() - fps_window_started
            self.effective_fps = fps_window_frames / fps_elapsed if fps_elapsed else 0.0
            if self.preview == "window":
                cv2.imshow("SDA-GCN Vision", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
            if self.frame_count % 30 == 0:
                sda_metric = f"{self.current_sda_gcn_ms:.1f}" if self.current_sda_gcn_ms is not None else "N/A"
                identity_metric = f"{self.current_identity_ms:.1f}" if self.current_identity_ms is not None else "N/A"
                sda_average = f"{np.mean(sda_window_samples):.1f}" if sda_window_samples else "N/A"
                identity_average = f"{np.mean(identity_window_samples):.1f}" if identity_window_samples else "N/A"
                identity_label = "DISABLED"
                if self.identity_stage:
                    result = self.identity_stage.result
                    identity_label = result.state.value
                    if result.state == IdentityState.LOCKED_KNOWN:
                        identity_label += f":{result.name}({result.confidence:.2f})"
                if self.log_level in {"debug", "info"}:
                    source_progress = f" | Source={snapshot.source_time_s:.1f}/{metadata.duration_s:.1f}s" if metadata.duration_s else ""
                    print(f"[Metrics] FPS={self.effective_fps:.1f}/{self.target_vision_fps:.0f}{source_progress} | "
                          f"Pose={self.pose_inference_ms:.0f}ms | Fall={sda_average}ms | "
                          f"ID={identity_label} | Drop={capture_dropped} | Miss={scheduler.deadline_miss_count}")
                if self.log_level == "debug":
                    print(f"[Metrics Debug] capture_fps={self.frame_source.capture_fps:.1f} "
                          f"source_frame_index={snapshot.source_frame_index} source_time_s={snapshot.source_time_s:.3f} "
                          f"playback_drift_ms={getattr(self.frame_source, 'playback_drift_ms', 0.0):.1f} "
                          f"mediapipe_timestamp_ms={self.pose_timestamp_adapter.last_timestamp_ms} "
                          f"identity_ms={identity_average} identity_hz={self.identity_stage.effective_hz if self.identity_stage else 0.0:.2f} "
                          f"identity_submitted={self.identity_stage.frames_submitted if self.identity_stage else 0} "
                          f"identity_processed={self.identity_stage.frames_processed if self.identity_stage else 0} "
                          f"identity_dropped={self.identity_stage.frames_dropped if self.identity_stage else 0} "
                          f"identity_ready={self.identity_stage.ready if self.identity_stage else False}")
                fps_window_started = time.perf_counter()
                fps_window_frames = 0
                sda_window_samples.clear()
                identity_window_samples.clear()
            
            latest_frame = frame.copy()

        if metadata.kind == SourceKind.VIDEO_FILE:
            final_packet = self.frame_source.store.latest()
            print(f"[Source EOF] source_time={final_packet.source_time_s:.3f}s | "
                  f"playback_wall={self.frame_source.playback_elapsed_s:.3f}s")
        self.shutdown()

    def shutdown(self):
        if self.frame_source:
            self.frame_source.stop()
            self.frame_source = None
        if self.identity_stage:
            self.identity_stage.stop()
            self.identity_stage = None
        if self.pose_model:
            self.pose_model.close()
            self.pose_model = None
        cv2.destroyAllWindows()

def parse_args():
    parser = argparse.ArgumentParser(description="Realtime Vision-only fall detection")
    parser.add_argument("--device", choices=("auto", "cuda", "amd", "intel", "cpu"), default="auto",
                        help="Hardware backend override (default: auto)")
    parser.add_argument("--preview", choices=("window", "web", "none"), default="window",
                        help="Annotated preview mode (default: window)")
    parser.add_argument("--send-events", action="store_true", help="Enable asynchronous P-227 event delivery")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000/api/v1/vision/events",
                        help="Event endpoint used with --send-events")
    parser.add_argument("--identity", choices=("on", "off"), default="on",
                        help="Enable InsightFace identity recognition (default: on)")
    parser.add_argument("--source", default="0",
                        help="Camera index or local video path (default: 0)")
    parser.add_argument("--source-fps", type=float,
                        help="Override video FPS when metadata is invalid")
    parser.add_argument("--vision-fps", type=float, default=15.0, help="Fall pipeline target rate (default: 15)")
    parser.add_argument("--identity-interval", type=float, default=0.5, help="Minimum identity submit interval in seconds")
    parser.add_argument("--face-det-size", type=int, default=416, help="InsightFace detector input size (default: 416)")
    parser.add_argument("--rebuild-face-cache", action="store_true", help="Recompute every registered face embedding")
    parser.add_argument("--log-level", choices=("debug", "info", "warning", "error"), default="info")
    parser.add_argument("--identity-debug", action="store_true", help="Log each identity matching attempt")
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

    system = FallDetectionSystem(args.device, args.preview, args.backend_url if args.send_events else None,
                                 args.identity, args.vision_fps, args.identity_interval, args.face_det_size,
                                 args.rebuild_face_cache, args.log_level, args.identity_debug,
                                 source_spec, args.source_fps)
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
