import os
import sys
import threading
import time
import warnings
from collections import deque
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("GLOG_minloglevel", "2")

import mediapipe as mp
import onnxruntime as ort
import torch
import torch.nn.functional as functional
import yaml
from extractkpt.common.cleaning import clean_out_of_bounds_data
from fusion.interpolate import interpolate_missing
from fusion.kalman_filter import apply_kalman_filter
from fusion.normalize_pose import normalize_pose
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
from scipy.interpolate import interp1d

from .callbacks import VisionCallbacks
from .config import VisionSessionConfig
from .contracts import FrameTransform, VisionDetection, VisionEvent, VisionFrameResult, VisionSourceFrame
from .runtime.hardware import (
    FaceAccelerationError,
    probe_capabilities,
    resolve_action_backend,
    resolve_face_providers,
)
from .runtime.identity import IdentityStage, IdentityState
from .runtime.inference import ActionInference, StageSpec, face_stage_spec, print_diagnostics
from .runtime.scheduler import FixedRateScheduler
from .runtime.source import ExternalFrameSource, SourceKind, create_source, parse_source
from .runtime.timing import (
    LatestPoseStore,
    MediaPipeTimestampAdapter,
    PosePacket,
    PoseSample,
    PoseSubmission,
    source_span_s,
)

warnings.filterwarnings("ignore", message=r"SymbolDatabase.GetPrototype\(\) is deprecated")


def import_class(import_str):
    mod_str, _sep, class_str = import_str.rpartition(".")
    __import__(mod_str)
    try:
        return getattr(sys.modules[mod_str], class_str)
    except AttributeError:
        raise ImportError(f"Class {class_str} cannot be found")


def resample_frames(kpts_array, target_frames=64):
    frame_count, joint_count, coordinate_count = kpts_array.shape
    if frame_count == target_frames:
        return kpts_array
    elif frame_count == 0:
        return np.zeros((target_frames, joint_count, coordinate_count), dtype=np.float32)
    elif frame_count == 1:
        return np.repeat(kpts_array, target_frames, axis=0)

    x_old = np.linspace(0, 1, frame_count)
    x_new = np.linspace(0, 1, target_frames)
    kpts_flat = kpts_array.reshape(frame_count, -1)
    f = interp1d(x_old, kpts_flat, axis=0, kind="linear", fill_value="extrapolate")
    resampled_flat = f(x_new)
    return resampled_flat.reshape(target_frames, joint_count, coordinate_count)


def compute_similarity(embedding1, embedding2):
    return np.dot(embedding1, embedding2) / (np.linalg.norm(embedding1) * np.linalg.norm(embedding2))


def extract_from_landmarks(landmarks):
    total_joints = 25
    keypoints = np.zeros((total_joints, 3), dtype=np.float32)

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


class VisionSession:
    def __init__(self, config: VisionSessionConfig, callbacks: VisionCallbacks | None = None):
        self.config = config
        self.callbacks = callbacks or VisionCallbacks()
        self.base_dir = str(config.package_root or Path(__file__).resolve().parents[1])
        self.hardware_capabilities = probe_capabilities()
        self.backend = resolve_action_backend(config.device, self.hardware_capabilities)
        self.preview = config.preview
        self.identity_enabled = config.identity_enabled
        self.inference_enabled = config.inference_enabled
        self.target_vision_fps = config.vision_fps
        self.identity_interval = config.identity_interval
        self.face_det_size = config.face_det_size
        self.rebuild_face_cache = config.rebuild_face_cache
        self.log_level = config.log_level
        self.identity_debug = config.identity_debug
        self.identity_process_priority = config.identity_process_priority
        self.identity_cpu_affinity = config.identity_cpu_affinity
        self.identity_gallery_mode = config.identity_gallery_mode
        self.identity_gallery_snapshot = config.identity_gallery_snapshot
        self.source_spec = parse_source(config.source) if config.source_mode == "managed" else None
        self.source_fps_override = config.source_fps
        self.identity_stage = None
        self.frame_source = None
        self._last_source_status = None

        self.app = None
        self.pose_model = None
        self.action_model = None
        self.pose_stage = StageSpec(
            "Pose", "MediaPipe", "CPU", "fp32", "MediaPipe Tasks Python does not expose an OpenVINO provider"
        )
        self.face_stage = None
        self.face_requested_providers = ()
        self.face_effective_providers = ()
        self.face_startup_error = None
        self.face_effective_det_size = None
        self._identity_start_attempted = False
        self._last_identity_queue = {"submitted": 0, "processed": 0, "dropped": 0, "max_depth": 0}
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
        self._current_packet = None
        self._latest_detection = None
        self._pending_generated_events = []
        self._pending_fall_diagnostics = []
        self._frame_transform = None
        self._event_frame_sequence = 0
        self._event_source_time_s = 0.0
        self._event_source_epoch = 0
        self.latest_result = None
        self._vision_stop_requested = False
        self._control_lock = threading.RLock()
        self._active_source_epoch = None
        self._profile_source_callback = deque(maxlen=4096)
        self._profile_result_callback = deque(maxlen=4096)
        self._profile_pose = deque(maxlen=4096)
        self._profile_sda = deque(maxlen=2048)
        self._profile_identity = deque(maxlen=1024)
        self._profile_cycle = deque(maxlen=4096)
        self._scheduler_deadline_misses = 0
        self._capture_frames_dropped = 0

    def _pose_callback(self, result: vision.PoseLandmarkerResult, output_image: mp.Image, timestamp_ms: int):
        submission = self._pose_submissions.pop(timestamp_ms, None)
        if submission is not None:
            latency = (time.perf_counter() - submission.submitted_perf_counter_s) * 1000.0
            self.pose_inference_ms = latency
            self._profile_pose.append((time.monotonic(), latency))
            self.pose_store.publish(
                PosePacket(
                    submission.source_time_s,
                    submission.frame_sequence,
                    result,
                    latency,
                    submission.frame,
                    submission.source_frame_index,
                    submission.wall_time_utc,
                    submission.source_epoch,
                    submission.source_frame,
                )
            )

    def _source_frame_callback(self, packet):
        callback = self.callbacks.on_source_frame
        if callback is None:
            return
        started = time.perf_counter()
        callback(
            VisionSourceFrame(
                camera_id=self.config.camera_id,
                frame_sequence=packet.sequence,
                source_frame_index=packet.source_frame_index,
                source_epoch=packet.source_epoch,
                source_time_s=packet.source_time_s,
                captured_wall_time=packet.wall_time_utc,
                frame=packet.frame,
            )
        )
        self._profile_source_callback.append((time.monotonic(), (time.perf_counter() - started) * 1000.0))

    def _record_sda_inference(self):
        self._profile_sda.append(
            (
                time.monotonic(),
                self.action_model.last_inference_ms,
                self.action_model.last_started_monotonic_s,
                self.action_model.invocation_count,
                self.action_model.last_started_wall_time_s,
                self.action_model.last_finished_wall_time_s,
            )
        )

    def init_models(self):
        with self._control_lock:
            if self.action_model is not None:
                if self.identity_enabled and self.identity_stage is None:
                    self._start_identity_stage()
                return
            if self.identity_enabled:
                self._start_identity_stage()
            else:
                self.face_stage = StageSpec("Face", "DISABLED", "", "n/a")

        print("[*] Initializing MediaPipe Pose (LIVE_STREAM mode)...")
        model_path = os.path.join(self.base_dir, "pose_landmarker_full.task")

        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.PoseLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.LIVE_STREAM,
            result_callback=self._pose_callback,
            num_poses=1,
            min_pose_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.pose_model = vision.PoseLandmarker.create_from_options(options)

        print("[*] Initializing SDA-GCN (Fall Detection)...")
        config_path = os.path.join(self.base_dir, "work_dir/fall_detection/fall/config.yaml")
        weights_path = os.path.join(self.base_dir, "work_dir/fall_detection/fall/runs-best_val.pt")

        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        model_cls = import_class(config["model"])
        model_args = config.get("model_args", {})
        self.action_model = ActionInference(
            model_cls(**model_args),
            weights_path,
            self.backend,
            os.path.join(self.base_dir, "work_dir/runtime_cache"),
        )
        print_diagnostics(self.backend, self.pose_stage, self.action_model.stage, self.face_stage)
        print(f"Identity        : {'ENABLED' if self.identity_enabled else 'DISABLED'}")
        if self.identity_enabled:
            print(f"Identity rate   : <= {1.0 / self.identity_interval:.1f} Hz")
            det_size = self.face_effective_det_size or self.face_det_size
            print(f"Face det size   : {det_size}x{det_size}")
        preview_label = {"window": "OpenCV Window", "web": "Web MJPEG", "none": "DISABLED"}[self.preview]
        print(f"Preview         : {preview_label}")
        print(f"Event Callback  : {'ENABLED' if self.callbacks.on_event else 'DISABLED'}\n")
        print(f"Model init      : {self.action_model.model_initialize_ms:.1f} ms")
        print(f"Model warmup    : {self.action_model.model_warmup_ms:.1f} ms\n")

    def _start_identity_stage(self):
        with self._control_lock:
            if self.identity_stage is not None or not self.identity_enabled or self._identity_start_attempted:
                return
            self._identity_start_attempted = True
            print("[*] Initializing Identity worker...")
            try:
                face_spec = resolve_face_providers(
                    self.config.device,
                    self.hardware_capabilities,
                    ort.get_available_providers(),
                )
            except FaceAccelerationError as exc:
                self.face_stage = StageSpec("Face", "UNAVAILABLE", "", "n/a", str(exc))
                self.face_startup_error = str(exc)
                print(f"[Identity Acceleration Error] {exc}")
                return
            providers = list(face_spec.providers)
            self.face_requested_providers = tuple(face_spec.providers)
            self.face_stage = face_stage_spec(face_spec)
            self.face_startup_error = None
            effective_det_size = 640 if face_spec.device == "DirectML" else self.face_det_size
            self.face_effective_det_size = effective_det_size
            stage = IdentityStage(
                providers,
                os.path.join(self.base_dir, "register face"),
                os.path.join(self.base_dir, "work_dir/identity_cache/identity_gallery.npz"),
                det_size=effective_det_size,
                interval=self.identity_interval,
                rebuild_cache=self.rebuild_face_cache,
                debug=self.log_level == "debug",
                identity_debug=self.identity_debug,
                process_priority=self.identity_process_priority,
                cpu_affinity=self.identity_cpu_affinity,
                gallery_mode=self.identity_gallery_mode,
                gallery_snapshot=self.identity_gallery_snapshot,
            )
            stage.start()
            self.identity_stage = stage

    def _reset_temporal_state(self):
        self.pose_samples.clear()
        self.pending_event = None
        self.current_action = "Waiting for frames..."
        self.action_color = (255, 255, 255)
        self._pose_submissions.clear()
        self.pose_store.clear()
        self._last_pose_sequence = 0
        self._latest_detection = None
        self.latest_result = None
        self._pending_generated_events = []
        self._pending_fall_diagnostics = []
        self._event_frame_sequence = 0
        self._event_source_time_s = 0.0
        self._event_source_epoch = 0
        self._last_identity_event_timestamp = 0.0
        if self.identity_stage is not None:
            self.identity_stage.reset()

    def set_inference_enabled(self, enabled: bool):
        enabled = bool(enabled)
        old_identity = None
        with self._control_lock:
            if self.inference_enabled == enabled:
                return
            self.inference_enabled = enabled
            self._reset_temporal_state()
            if not enabled:
                old_identity, self.identity_stage = self.identity_stage, None
                self._identity_start_attempted = False
        if old_identity is not None:
            old_identity.stop()
        if enabled and self.identity_enabled and self.action_model is not None:
            self._start_identity_stage()

    def set_identity_enabled(self, enabled: bool):
        enabled = bool(enabled)
        old_identity = None
        should_start = False
        with self._control_lock:
            if self.identity_enabled == enabled:
                should_start = enabled and self.action_model is not None and self.identity_stage is None
                if not should_start:
                    return
            else:
                self.identity_enabled = enabled
                self.config.identity_enabled = enabled
                self._last_identity_event_timestamp = 0.0
                self._latest_detection = None
                if not enabled:
                    old_identity, self.identity_stage = self.identity_stage, None
                    self._identity_start_attempted = False
                    self.face_stage = StageSpec("Face", "DISABLED", "", "n/a")
                else:
                    should_start = self.action_model is not None and self.identity_stage is None
                    self._identity_start_attempted = False
                    self.face_startup_error = None
        if old_identity is not None:
            old_identity.stop()
        if should_start:
            self._start_identity_stage()

    def update_identity_gallery(self, snapshot):
        """Store/broadcast a supplied gallery without blocking the Fall loop."""
        with self._control_lock:
            if self.identity_gallery_mode != "supplied":
                raise RuntimeError("This Vision session uses the filesystem gallery")
            self.identity_gallery_snapshot = snapshot
            self.config.identity_gallery_snapshot = snapshot
            stage = self.identity_stage
            self._last_identity_event_timestamp = 0.0
            self._latest_detection = None
            self._pending_generated_events = [
                event
                for event in self._pending_generated_events
                if event.event_type.strip().lower() not in {"unknown_person", "person_recognized"}
            ]
            if stage is not None:
                stage.update_gallery(snapshot)

    def load_known_faces(self, data_dir=None):
        # Identity worker owns model initialization and registered embeddings.
        return

    def emit_event(
        self, event_type, confidence=0.9, identity_status="UNKNOWN", identity_name=None, identity_person_id=None
    ):
        throttle_key = f"{event_type}_{identity_name}"
        now = time.monotonic()
        if now - self.last_sent_time.get(throttle_key, 0) < 5.0:
            return False
        self.last_sent_time[throttle_key] = now

        if not self._event_frame_sequence:
            return False
        detection = self._latest_detection
        event = VisionEvent(
            event_type=event_type,
            confidence=float(confidence),
            frame_sequence=self._event_frame_sequence,
            source_time_s=self._event_source_time_s,
            identity_state=identity_status,
            identity_name=identity_name,
            identity_person_id=identity_person_id,
            person_bbox=detection.bbox if detection else None,
            face_bbox=detection.face_bbox if detection else None,
            metadata={
                "camera_id": self.config.camera_id,
                "camera_location": self.config.camera_location,
                "source_epoch": getattr(self, "_event_source_epoch", self.config.source_epoch),
            },
        )
        self._pending_generated_events.append(event)
        if self.callbacks.on_event:
            self.callbacks.on_event(event)
        return True

    def _record_fall_diagnostic(self, source_time_s, **values):
        source_epoch = getattr(self, "_event_source_epoch", getattr(self.config, "source_epoch", 0))
        diagnostic = {
            "source_time_s": float(source_time_s),
            "source_epoch": int(source_epoch),
            **values,
        }
        if not hasattr(self, "_pending_fall_diagnostics"):
            self._pending_fall_diagnostics = []
        self._pending_fall_diagnostics.append(diagnostic)
        if getattr(self, "log_level", "info") == "debug":
            print(f"[Fall Debug] {diagnostic}")

    def process_person(
        self, frame, x1, y1, x2, y2, track_id, frame_sequence=None, source_time_s=None, overlay_frame=None
    ):
        overlay_frame = frame if overlay_frame is None else overlay_frame
        stage = self.identity_stage
        if not self.identity_enabled or stage is None:
            cv2.rectangle(overlay_frame, (x1, y1), (x2, y2), (255, 255, 0), 2)
            self._latest_detection = VisionDetection(
                "person",
                bbox=self._frame_transform.bbox_to_source((x1, y1, x2, y2)),
                identity_state="DISABLED",
                identity_status="DISABLED",
            )
            return
        crop_frame = frame[y1:y2, x1:x2]
        with self._control_lock:
            stage = self.identity_stage
            if not self.identity_enabled or stage is None:
                return
            processed_before = stage.frames_processed
            previous_state = stage.result.state
            stage.submit(
                crop_frame.copy(), (x1, y1, x2, y2), source_time_s=source_time_s, frame_sequence=frame_sequence
            )
            result = stage.poll()
        if result.state != previous_state and self.log_level in {"debug", "info"}:
            detail = f" | {result.name} | similarity={result.confidence:.2f}" if result.name else ""
            print(f"[Identity] {previous_state.value} -> {result.state.value}{detail}")
        if stage.frames_processed != processed_before:
            self.current_identity_ms = result.inference_ms
            self._profile_identity.append(
                (
                    time.monotonic(),
                    result.inference_ms,
                    result.state.value,
                    result.inference_started_wall_time_s,
                    result.inference_finished_wall_time_s,
                )
            )
            if result.timestamp != self._last_identity_event_timestamp:
                if result.state == IdentityState.LOCKED_KNOWN:
                    self.emit_event("PERSON_RECOGNIZED", result.confidence, "KNOWN", result.name, result.person_id)
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
        exact_face_bbox = None
        if result.face_bbox is not None and result.face_bbox_frame_sequence == frame_sequence:
            fx1, fy1, fx2, fy2 = result.face_bbox
            exact_face_bbox = self._frame_transform.bbox_to_source((x1 + fx1, y1 + fy1, x1 + fx2, y1 + fy2))
        self._latest_detection = VisionDetection(
            "person",
            bbox=self._frame_transform.bbox_to_source((x1, y1, x2, y2)),
            identity_state=result.state.value,
            identity_status=("KNOWN" if result.state == IdentityState.LOCKED_KNOWN else "UNKNOWN"),
            identity_name=result.name,
            identity_person_id=result.person_id,
            identity_confidence=result.confidence,
            identity_face_verified=result.face_found,
            face_bbox=exact_face_bbox,
            association_id=result.association_id,
        )

    def detect_fall(self, current_source_time_s):
        if self.config.raw_classifier:
            return self._detect_fall_raw(current_source_time_s)
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
            def movement_check(current, anchor, torso_length):
                # Tính khoảng cách xê dịch của toàn bộ 25 khớp
                diff = np.linalg.norm(current - anchor, axis=1)

                # Màng lọc 1: Loại bỏ nhiễu tĩnh (< 15% torso)
                moved_joints = diff[diff > 0.15 * torso_length]
                avg_movement = float(np.mean(moved_joints)) if len(moved_joints) else 0.0
                # Màng lọc 2: Chốt hành động (Ít nhất 1 khớp xê dịch mạnh > 40% torso)
                moved = bool(len(moved_joints) >= 1 and avg_movement > 0.40 * torso_length)
                return moved, avg_movement, len(moved_joints)

            # DÒNG THỜI GIAN CUỐN CHIẾU
            if elapsed >= 2.0 and event["state"] == "FALL_DETECTED":
                previous_state = event["state"]
                event["anchor_kpts"] = current_kpts
                event["state"] = "WARNING_PENDING"
                event["next_check_source_time_s"] = event["started_source_time_s"] + 3.0
                self._record_fall_diagnostic(
                    current_source_time_s,
                    current_action=self.current_action,
                    top_predicted_class=event.get("top_predicted_class", "Fall"),
                    fall_class_probability=event.get("fall_class_probability", event["conf"]),
                    pending_state=event["state"],
                    state_transition=f"{previous_state}->WARNING_PENDING",
                    elapsed=elapsed,
                    movement_gate_result=None,
                    movement_amount=None,
                    torso_reference=float(torso_len),
                    cancellation_reason=None,
                    fall_confirmed_emitted=False,
                    emitted_confidence=None,
                )

            elif event["state"] == "WARNING_PENDING" and current_source_time_s >= event["next_check_source_time_s"]:
                moved, movement_amount, moved_joints = movement_check(current_kpts, event["anchor_kpts"], torso_len)
                if moved:
                    self.pending_event = None  # Khớp xê dịch mạnh -> Bẻ lái hủy
                    transition = "WARNING_PENDING->CLEAR"
                    cancellation_reason = "movement_gate"
                else:
                    event["state"] = "WARNING"
                    transition = "WARNING_PENDING->WARNING"
                    cancellation_reason = None
                    self.current_action = "Co the nga (Cho...)"
                    self.action_color = (0, 165, 255)  # Cam
                    event["anchor_kpts"] = current_kpts
                    event["next_check_source_time_s"] = event["started_source_time_s"] + 5.0
                self._record_fall_diagnostic(
                    current_source_time_s,
                    current_action=self.current_action,
                    top_predicted_class=event.get("top_predicted_class", "Fall"),
                    fall_class_probability=event.get("fall_class_probability", event["conf"]),
                    pending_state=(event["state"] if self.pending_event else "CLEAR"),
                    state_transition=transition,
                    elapsed=elapsed,
                    movement_gate_result=moved,
                    movement_amount=movement_amount,
                    moved_joints=moved_joints,
                    torso_reference=float(torso_len),
                    cancellation_reason=cancellation_reason,
                    fall_confirmed_emitted=False,
                    emitted_confidence=None,
                )

            elif event["state"] == "WARNING" and current_source_time_s >= event["next_check_source_time_s"]:
                moved, movement_amount, moved_joints = movement_check(current_kpts, event["anchor_kpts"], torso_len)
                if moved:
                    self.pending_event = None
                    transition = "WARNING->CLEAR"
                    cancellation_reason = "movement_gate"
                    emitted = False
                else:
                    event["state"] = "ALERT"
                    transition = "WARNING->ALERT"
                    cancellation_reason = None
                    self.current_action = f"Nga! ({event['conf']:.2f})"
                    self.action_color = (0, 0, 255)  # Đỏ

                    # Phát API cảnh báo (Gửi duy nhất 1 lần ở Giây thứ 5.0)
                    emitted = self.emit_event("FALL_CONFIRMED", event["conf"]) is not False

                    event["anchor_kpts"] = current_kpts
                    event["next_check_source_time_s"] = current_source_time_s + 2.0
                self._record_fall_diagnostic(
                    current_source_time_s,
                    current_action=self.current_action,
                    top_predicted_class=event.get("top_predicted_class", "Fall"),
                    fall_class_probability=event.get("fall_class_probability", event["conf"]),
                    pending_state=(event["state"] if self.pending_event else "CLEAR"),
                    state_transition=transition,
                    elapsed=elapsed,
                    movement_gate_result=moved,
                    movement_amount=movement_amount,
                    moved_joints=moved_joints,
                    torso_reference=float(torso_len),
                    cancellation_reason=cancellation_reason,
                    fall_confirmed_emitted=emitted,
                    emitted_confidence=(event["conf"] if emitted else None),
                )

            elif event["state"] == "ALERT" and current_source_time_s >= event["next_check_source_time_s"]:
                # Cuốn chiếu kiểm tra mỗi 2 giây
                moved, movement_amount, moved_joints = movement_check(current_kpts, event["anchor_kpts"], torso_len)
                if moved:
                    self.pending_event = None
                    transition = "ALERT->CLEAR"
                    cancellation_reason = "movement_gate"
                else:
                    event["anchor_kpts"] = current_kpts
                    event["next_check_source_time_s"] = current_source_time_s + 2.0
                    transition = "ALERT->ALERT"
                    cancellation_reason = None
                self._record_fall_diagnostic(
                    current_source_time_s,
                    current_action=self.current_action,
                    top_predicted_class=event.get("top_predicted_class", "Fall"),
                    fall_class_probability=event.get("fall_class_probability", event["conf"]),
                    pending_state=(event["state"] if self.pending_event else "CLEAR"),
                    state_transition=transition,
                    elapsed=elapsed,
                    movement_gate_result=moved,
                    movement_amount=movement_amount,
                    moved_joints=moved_joints,
                    torso_reference=float(torso_len),
                    cancellation_reason=cancellation_reason,
                    fall_confirmed_emitted=False,
                    emitted_confidence=None,
                )

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
                    self._record_sda_inference()
                    prob = functional.softmax(output, dim=1).squeeze()
                    pred_idx = torch.argmax(prob).item()
                    conf = float(prob[pred_idx])
                    fall_probability = float(prob[0])
                    action_names = {0: "Fall", 1: "Dung", 2: "Cui", 3: "Ngoi", 4: "Nam"}
                    top_predicted_class = action_names.get(pred_idx, f"class_{pred_idx}")
                    self._record_fall_diagnostic(
                        current_source_time_s,
                        current_action=self.current_action,
                        top_predicted_class=top_predicted_class,
                        fall_class_probability=fall_probability,
                        pending_state="FALL_DETECTED" if pred_idx == 0 else "CLEAR",
                        state_transition="CLEAR->FALL_DETECTED" if pred_idx == 0 else None,
                        elapsed=0.0,
                        movement_gate_result=None,
                        movement_amount=None,
                        torso_reference=None,
                        cancellation_reason=None,
                        fall_confirmed_emitted=False,
                        emitted_confidence=None,
                    )

                    if pred_idx == 0:  # AI Báo Ngã
                        # Cơ chế Lock-out: Bỏ sự kiện vào hàng chờ
                        self.pending_event = {
                            "started_source_time_s": current_source_time_s,
                            "state": "FALL_DETECTED",
                            "anchor_kpts": None,
                            "next_check_source_time_s": 0,
                            "conf": conf,
                            "top_predicted_class": top_predicted_class,
                            "fall_class_probability": fall_probability,
                        }
                        self.current_action = f"Phat hien nga ({conf:.2f}) - Kiem tra..."
                        self.action_color = (0, 255, 255)  # Vàng
                    else:
                        action_name = action_names.get(pred_idx, "Khong xac dinh")
                        self.current_action = f"{action_name} ({conf:.2f})"
                        self.action_color = (0, 255, 0)  # Xanh

                # TRẢ VỀ ĐÚNG VỊ TRÍ CŨ TRONG CODE GỐC: Chỉ cắt buffer SAU KHI AI đã chạy
                while self.pose_samples and (current_source_time_s - self.pose_samples[0].source_time_s > 1.0):
                    self.pose_samples.popleft()

        # 3. CHỐNG TRÀN RAM (Bảo vệ dự phòng cho hệ thống)
        while self.pose_samples and (current_source_time_s - self.pose_samples[0].source_time_s > 2.5):
            self.pose_samples.popleft()

    def _detect_fall_raw(self, current_source_time_s):
        """Legacy raw comparison semantics selected without duplicating orchestration."""
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
            self._record_sda_inference()
            prob = functional.softmax(output, dim=1).squeeze()
            pred_idx = torch.argmax(prob).item()
            conf = float(prob[pred_idx])
            if pred_idx == 1:
                self.current_action = f"Nga! ({conf:.2f})"
                self.action_color = (0, 0, 255)
                self.emit_event("FALL_CONFIRMED", conf)
            else:
                self.current_action = f"Khong nga ({conf:.2f})"
                self.action_color = (0, 255, 0)
        while self.pose_samples and current_source_time_s - self.pose_samples[0].source_time_s > 1.0:
            self.pose_samples.popleft()

    def run(self):
        try:
            self.start_source()
            self.run_vision()
        finally:
            self.shutdown()

    def start_source(self):
        if self.config.source_mode != "managed":
            raise RuntimeError("External sessions must use start_external_source().")
        if self.frame_source is not None:
            return
        self.frame_source = create_source(
            self.source_spec,
            self.source_fps_override,
            loop_video=self.config.loop_video,
            reconnect_delay=self.config.stream_reconnect_delay,
            on_frame=self._source_frame_callback,
            initial_epoch=self.config.source_epoch,
        )
        self.frame_source.start()

    def start_external_source(self, source_epoch: int | None = None):
        if self.config.source_mode != "external":
            raise RuntimeError("Managed sessions cannot accept external frames.")
        if self.frame_source is not None:
            raise RuntimeError("External source is already active.")
        epoch = self.config.source_epoch if source_epoch is None else int(source_epoch)
        self.frame_source = ExternalFrameSource(self._source_frame_callback, epoch)
        self.frame_source.start()

    def submit_external_frame(self, frame):
        source = self.frame_source
        if not isinstance(source, ExternalFrameSource):
            raise RuntimeError("External source is not active.")
        source.publish_frame(frame)

    def source_status(self) -> dict:
        source = self.frame_source
        if source is None:
            return self._last_source_status or {
                "running": False,
                "ended": False,
                "error": None,
                "capture_fps": 0.0,
                "source_epoch": self.config.source_epoch,
            }
        return {
            "running": source.is_running,
            "ended": bool(source.ended),
            "error": source.error,
            "capture_fps": source.capture_fps,
            "source_epoch": source.source_epoch,
        }

    def run_vision(self):
        if self.frame_source is None:
            raise RuntimeError("Source must be started before Vision processing.")
        source = self.frame_source
        self._vision_stop_requested = False
        self._scheduler_deadline_misses = 0
        self._capture_frames_dropped = 0
        metadata = source.metadata
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
            print("[*] OpenCV preview ready. Press q to exit.")
        else:
            print("[*] Preview disabled; Vision inference is running.")
        global latest_frame
        fps_window_started = time.perf_counter()
        fps_window_frames = 0
        sda_window_samples = []
        identity_window_samples = []

        while not self._vision_stop_requested:
            scheduler.wait()
            vision_started = time.perf_counter()
            snapshot = source.store.wait_newer(last_capture_sequence, scheduler.interval)
            if snapshot is None or snapshot.sequence == last_capture_sequence:
                if source.ended:
                    break
                continue
            capture_dropped += max(0, snapshot.sequence - last_capture_sequence - 1) if last_capture_sequence else 0
            last_capture_sequence = snapshot.sequence
            if self._active_source_epoch != snapshot.source_epoch:
                self._active_source_epoch = snapshot.source_epoch
                self._reset_temporal_state()
            if not self.inference_enabled:
                continue
            if self.action_model is None:
                try:
                    self.init_models()
                except Exception:
                    self.inference_enabled = False
                    raise
                continue
            elif self.identity_enabled and self.identity_stage is None:
                self._start_identity_stage()
            self._current_packet = snapshot
            self._pending_generated_events = []
            frame = snapshot.frame.copy()

            h, w = frame.shape[:2]
            self._frame_transform = FrameTransform(w, h, self.orig_w, self.orig_h)
            scale = min(self.orig_w / w, self.orig_h / h)
            new_w, new_h = int(w * scale), int(h * scale)
            frame = cv2.resize(frame, (new_w, new_h))

            pad_w = self.orig_w - new_w
            pad_h = self.orig_h - new_h
            frame = cv2.copyMakeBorder(
                frame,
                pad_h // 2,
                pad_h - pad_h // 2,
                pad_w // 2,
                pad_w - pad_w // 2,
                cv2.BORDER_CONSTANT,
                value=(0, 0, 0),
            )

            self.frame_count += 1
            self.current_identity_ms = None
            if self.identity_stage and not self._gallery_status_logged:
                gallery = self.identity_stage.poll_status()
                if gallery:
                    self.face_effective_providers = tuple(gallery.get("effective_providers", ()))
                    if gallery.get("startup_error"):
                        self.face_startup_error = gallery["startup_error"]
                        self.face_stage = StageSpec("Face", "UNAVAILABLE", "", "n/a", self.face_startup_error)
                    print("\n[Identity Gallery]")
                    print(f"Persons         : {gallery.get('persons', 0)}")
                    print(f"Images          : {gallery.get('images', 0)}")
                    print(f"Cached          : {gallery.get('cached', 0)}")
                    print(f"Recomputed      : {gallery.get('recomputed', 0)}")
                    print(f"Skipped         : {gallery.get('skipped', 0)}")
                    print(f"Load time       : {gallery.get('gallery_ms', 0):.0f} ms")
                    print(f"Identity ready  : {gallery.get('ready_ms', 0):.0f} ms")
                    execution = gallery.get("execution", {})
                    print(f"Identity priority: {execution.get('effective_priority', 'normal')}")
                    print(f"Identity affinity: {execution.get('effective_affinity') or 'unrestricted'}")
                    if execution.get("isolation_reason"):
                        print(f"Identity isolation: {execution['isolation_reason']}")
                    print(f"Face requested   : {', '.join(self.face_requested_providers) or 'none'}")
                    print(f"Face effective   : {', '.join(self.face_effective_providers) or 'none'}")
                    if self.face_startup_error:
                        print(f"Face error       : {self.face_startup_error}")
                    self._gallery_status_logged = True

            timestamp_ms = self.pose_timestamp_adapter.convert(snapshot.source_time_s, snapshot.source_epoch)

            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
            self._pose_submissions[timestamp_ms] = PoseSubmission(
                snapshot.source_time_s,
                snapshot.sequence,
                time.perf_counter(),
                frame.copy(),
                snapshot.source_frame_index,
                snapshot.wall_time_utc,
                snapshot.source_epoch,
                snapshot.frame,
            )
            while len(self._pose_submissions) > 8:
                self._pose_submissions.pop(next(iter(self._pose_submissions)))
            self.pose_model.detect_async(mp_image, timestamp_ms)

            pose_packet = self.pose_store.latest()
            new_pose_packet = bool(
                pose_packet
                and pose_packet.source_epoch == self._active_source_epoch
                and pose_packet.frame_sequence > self._last_pose_sequence
            )
            if new_pose_packet:
                self._last_pose_sequence = pose_packet.frame_sequence
                self._event_frame_sequence = pose_packet.frame_sequence
                self._event_source_time_s = pose_packet.source_time_s
                self._event_source_epoch = pose_packet.source_epoch
                self._latest_detection = None
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
                    self.process_person(
                        pose_packet.frame,
                        x1,
                        y1,
                        x2,
                        y2,
                        track_id=None,
                        frame_sequence=pose_packet.frame_sequence,
                        source_time_s=pose_packet.source_time_s,
                        overlay_frame=frame,
                    )

                self.pose_samples.append(PoseSample(pose_packet.source_time_s, kpts))

            elif new_pose_packet:
                if self.identity_stage:
                    identity_before = self.identity_stage.result
                    self.identity_stage.update_presence(None, pose_packet.source_time_s)
                    if identity_before.state != self.identity_stage.result.state and self.log_level in {
                        "debug",
                        "info",
                    }:
                        label = identity_before.name or identity_before.state.value
                        print(f"[Identity] {label} left scene -> reset")
                if self.pose_samples:
                    last_kpts = self.pose_samples[-1].keypoints.copy()
                else:
                    last_kpts = np.zeros((25, 3), dtype=np.float32)

                self.pose_samples.append(PoseSample(pose_packet.source_time_s, last_kpts))

                if self.pending_event is None:
                    self.current_action = "Khong nga (Lost)"
                    self.action_color = (0, 255, 0)

            self.current_sda_gcn_ms = None
            self._pending_fall_diagnostics = []
            if self.pose_samples:
                self.detect_fall(self.pose_samples[-1].source_time_s)
            if self.current_sda_gcn_ms is not None:
                sda_window_samples.append(self.current_sda_gcn_ms)
            if self.current_identity_ms is not None:
                identity_window_samples.append(self.current_identity_ms)

            cv2.putText(
                frame, f"Action: {self.current_action}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, self.action_color, 2
            )
            cv2.putText(
                frame,
                f"Buffer: {len(self.pose_samples)} frames / 2.0s",
                (20, 80),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
            )

            self.total_vision_ms = (time.perf_counter() - vision_started) * 1000.0
            self._profile_cycle.append((time.monotonic(), self.total_vision_ms))
            if new_pose_packet:
                fall_state = self.pending_event["state"] if self.pending_event else "CLEAR"
                fall_confidence = self.pending_event["conf"] if self.pending_event else None
                self.latest_result = VisionFrameResult(
                    camera_id=self.config.camera_id,
                    frame_sequence=pose_packet.frame_sequence,
                    source_frame_index=pose_packet.source_frame_index,
                    source_epoch=pose_packet.source_epoch,
                    source_time_s=pose_packet.source_time_s,
                    captured_wall_time=pose_packet.wall_time_utc,
                    current_action=self.current_action,
                    fall_state=fall_state,
                    fall_confidence=fall_confidence,
                    detections=((self._latest_detection,) if self._latest_detection else ()),
                    generated_events=tuple(self._pending_generated_events),
                    fall_diagnostics=tuple(self._pending_fall_diagnostics),
                    stage_metrics={
                        "pose_callback_latency_ms": self.pose_inference_ms,
                        "sda_gcn_inference_ms": self.current_sda_gcn_ms,
                        "sda_gcn_inference_started_monotonic_s": (
                            self.action_model.last_started_monotonic_s if self.current_sda_gcn_ms is not None else None
                        ),
                        "sda_gcn_inference_finished_monotonic_s": (
                            self.action_model.last_finished_monotonic_s if self.current_sda_gcn_ms is not None else None
                        ),
                        "sda_gcn_invocation_count": self.action_model.invocation_count,
                        "identity_inference_ms": self.current_identity_ms,
                        "identity_frames_submitted": (
                            self.identity_stage.frames_submitted if self.identity_stage else 0
                        ),
                        "identity_frames_processed": (
                            self.identity_stage.frames_processed if self.identity_stage else 0
                        ),
                        "identity_frames_dropped": (self.identity_stage.frames_dropped if self.identity_stage else 0),
                        "identity_inference_started_monotonic_s": (
                            self.identity_stage.result.inference_started_monotonic_s
                            if self.current_identity_ms is not None and self.identity_stage
                            else None
                        ),
                        "identity_inference_finished_monotonic_s": (
                            self.identity_stage.result.inference_finished_monotonic_s
                            if self.current_identity_ms is not None and self.identity_stage
                            else None
                        ),
                        "total_vision_ms": self.total_vision_ms,
                        "effective_fps": self.effective_fps,
                        "scheduler_deadline_misses": scheduler.deadline_miss_count,
                        "capture_frames_dropped": capture_dropped,
                    },
                )
                if self.callbacks.on_result:
                    self.callbacks.on_result(self.latest_result)
                if self.callbacks.on_result_frame:
                    callback_started = time.perf_counter()
                    self.callbacks.on_result_frame(pose_packet.source_frame, self.latest_result)
                    self._profile_result_callback.append(
                        (time.monotonic(), (time.perf_counter() - callback_started) * 1000.0)
                    )
            if self.callbacks.on_preview and self.latest_result:
                self.callbacks.on_preview(frame, self.latest_result)
            fps_window_frames += 1
            fps_elapsed = time.perf_counter() - fps_window_started
            self.effective_fps = fps_window_frames / fps_elapsed if fps_elapsed else 0.0
            if self.frame_count % 30 == 0:
                sda_average = f"{np.mean(sda_window_samples):.1f}" if sda_window_samples else "N/A"
                identity_average = f"{np.mean(identity_window_samples):.1f}" if identity_window_samples else "N/A"
                identity_label = "DISABLED"
                if self.identity_stage:
                    result = self.identity_stage.result
                    identity_label = result.state.value
                    if result.state == IdentityState.LOCKED_KNOWN:
                        identity_label += f":{result.name}({result.confidence:.2f})"
                if self.log_level in {"debug", "info"}:
                    source_progress = (
                        f" | Source={snapshot.source_time_s:.1f}/{metadata.duration_s:.1f}s"
                        if metadata.duration_s
                        else ""
                    )
                    print(
                        f"[Metrics] FPS={self.effective_fps:.1f}/{self.target_vision_fps:.0f}{source_progress} | "
                        f"Pose={self.pose_inference_ms:.0f}ms | Fall={sda_average}ms | "
                        f"ID={identity_label} | Drop={capture_dropped} | Miss={scheduler.deadline_miss_count}"
                    )
                if self.log_level == "debug":
                    print(
                        f"[Metrics Debug] capture_fps={source.capture_fps:.1f} "
                        f"source_frame_index={snapshot.source_frame_index} source_time_s={snapshot.source_time_s:.3f} "
                        f"playback_drift_ms={getattr(source, 'playback_drift_ms', 0.0):.1f} "
                        f"mediapipe_timestamp_ms={self.pose_timestamp_adapter.last_timestamp_ms} "
                        f"identity_ms={identity_average} identity_hz={self.identity_stage.effective_hz if self.identity_stage else 0.0:.2f} "
                        f"identity_submitted={self.identity_stage.frames_submitted if self.identity_stage else 0} "
                        f"identity_processed={self.identity_stage.frames_processed if self.identity_stage else 0} "
                        f"identity_dropped={self.identity_stage.frames_dropped if self.identity_stage else 0} "
                        f"identity_ready={self.identity_stage.ready if self.identity_stage else False}"
                    )
                fps_window_started = time.perf_counter()
                fps_window_frames = 0
                sda_window_samples.clear()
                identity_window_samples.clear()
            self._scheduler_deadline_misses = scheduler.deadline_miss_count
            self._capture_frames_dropped = capture_dropped

        if metadata.kind == SourceKind.VIDEO_FILE:
            final_packet = source.store.latest()
            print(
                f"[Source EOF] source_time={final_packet.source_time_s:.3f}s | "
                f"playback_wall={source.playback_elapsed_s:.3f}s"
            )

    def request_vision_stop(self):
        self._vision_stop_requested = True

    def shutdown_vision(self):
        self._vision_stop_requested = True
        if self.identity_stage:
            self._last_identity_queue = {
                "submitted": getattr(self.identity_stage, "frames_submitted", 0),
                "processed": getattr(self.identity_stage, "frames_processed", 0),
                "dropped": getattr(self.identity_stage, "frames_dropped", 0),
                "max_depth": 1,
            }
            self.identity_stage.stop()
            self.identity_stage = None
        if self.pose_model:
            self.pose_model.close()
            self.pose_model = None
        if getattr(self, "action_model", None):
            self.action_model.close()
            self.action_model = None

    def stop_source(self):
        source = self.frame_source
        if source is not None:
            source.stop()
            self._last_source_status = {
                "running": False,
                "ended": bool(source.ended),
                "error": source.error,
                "capture_fps": source.capture_fps,
                "source_epoch": source.source_epoch,
            }
            self.frame_source = None

    def shutdown(self):
        self.request_vision_stop()
        self.stop_source()
        self.shutdown_vision()

    def request_stop(self):
        self.request_vision_stop()
        source = self.frame_source
        if source is not None:
            source.request_stop()

    def performance_profile(self) -> dict:
        """Return bounded monotonic timing samples without persistent frame data."""
        return {
            "source_callback": list(self._profile_source_callback),
            "result_callback": list(self._profile_result_callback),
            "pose": list(self._profile_pose),
            "sda_gcn": list(self._profile_sda),
            "identity": list(self._profile_identity),
            "cycle": list(self._profile_cycle),
            "scheduler_deadline_misses": self._scheduler_deadline_misses,
            "capture_frames_dropped": self._capture_frames_dropped,
            "identity_queue": (
                {
                    "submitted": self.identity_stage.frames_submitted,
                    "processed": self.identity_stage.frames_processed,
                    "dropped": self.identity_stage.frames_dropped,
                    "max_depth": 1,
                }
                if self.identity_stage
                else dict(self._last_identity_queue)
            ),
        }

    def hardware_diagnostics(self) -> dict:
        return {
            "pose_backend": "MediaPipe CPU",
            "action_backend": None if self.action_model is None else self.action_model.stage.backend,
            "action_device": None if self.action_model is None else self.action_model.stage.device,
            "action_precision": None if self.action_model is None else self.action_model.stage.precision,
            "face_backend": None if self.face_stage is None else self.face_stage.backend,
            "face_provider": self.face_requested_providers[0] if self.face_requested_providers else None,
            "face_detector_size": self.face_effective_det_size,
            "face_requested_providers": list(self.face_requested_providers),
            "face_effective_providers": list(self.face_effective_providers),
            "face_startup_error": self.face_startup_error,
            "hardware_vendor": self.backend.vendor,
            "hardware_device_name": self.backend.device_name,
        }
