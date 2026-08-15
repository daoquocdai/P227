import logging
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import numpy as np

from src.models.frame import FramePacket
from src.models.vision import VisionDetection, VisionEvent, VisionResult
from src.vision.engine import VisionEngine
from src.vision.runtime import VisionRuntimeResolver
from src.vision.session import VisionSession

logger = logging.getLogger(__name__)

VISION_ROOT = Path(__file__).resolve().parent
DEFAULT_INSIGHTFACE_ROOT = Path.home() / ".insightface"
WINDOW_SIZE = 64
WINDOW_SECONDS = 2.0
WINDOW_RETAIN_SECONDS = 1.0
DECISION_DELAY_SECONDS = 3.0
MOVEMENT_CHECK_SECONDS = 2.0
MOVEMENT_THRESHOLD = 0.1
FRAME_SIZE = 1024
FALL_LABEL = "Nga!"
FACE_RECOGNITION_MAX_ATTEMPTS = 5
FACE_RECOGNITION_INTERVAL_SECONDS = 1.0


class VisionInitializationError(RuntimeError):
    """A required canonical Vision resource or model is invalid."""


@dataclass
class CameraContext:
    yolo: Any
    pose: Any
    session_token: object

    def close(self) -> None:
        close = getattr(self.pose, "close", None)
        if callable(close):
            close()


class RuntimeV2VisionPipeline(VisionEngine):
    """Production copy/adaptation of immutable runtimev2 Vision behavior.

    Ordered per-camera workers may call the engine concurrently. YOLO tracking
    and MediaPipe Pose remain isolated per camera because both retain stream
    state; shared infer requests and FaceAnalysis have narrow locks.
    """

    EXPECTED_MODEL = {"num_class": 5, "num_person": 1, "num_point": 25, "in_channels": 3}
    EXPECTED_BONE_MODALITY = False
    OUTPUT_CLASSES = 5
    FALL_CLASS_ID = 1

    def __init__(
        self,
        yolo_path: str | Path = VISION_ROOT / "yolov8n.pt",
        config_path: str | Path = VISION_ROOT / "work_dir" / "fall_detection" / "joint" / "config.yaml",
        checkpoint_path: str | Path = VISION_ROOT / "work_dir" / "fall_detection" / "joint" / "runs-best_val.pt",
        model_cache_dir: str | Path = Path("data/vision-cache"),
        known_faces_dir: str | Path = VISION_ROOT / "register face",
        identity_enabled: bool = False,
        identity_provider: str = "auto",
        insightface_root: str | Path = DEFAULT_INSIGHTFACE_ROOT,
        *,
        device: str = "auto",
        face_gallery: Any = None,
        clock: Callable[[], float] = time.time,
        incident_factory: Callable[[], Any] = uuid4,
    ) -> None:
        self.yolo_path = self._resolve_path(yolo_path)
        self.config_path = self._resolve_path(config_path)
        self.checkpoint_path = self._resolve_path(checkpoint_path)
        self.model_cache_dir = Path(model_cache_dir).expanduser().resolve()
        self.known_faces_dir = self._resolve_path(known_faces_dir)
        self.insightface_root = self._resolve_path(insightface_root)
        self.identity_enabled = identity_enabled
        self.identity_provider = identity_provider.strip().lower()
        self.requested_device = VisionRuntimeResolver.normalize_device(device)
        self._face_gallery = face_gallery
        self._clock = clock
        self._incident_factory = incident_factory
        self._lock = threading.RLock()
        self._face_lock = threading.Lock()
        self._contexts: dict[str, CameraContext] = {}
        self._dependencies: SimpleNamespace | None = None
        self._device: Any = None
        self._capability_plan: Any = None
        self._detector_model_path = self.yolo_path
        self._detector_device: str | None = None
        self._action_model: Any = None
        self._face_app: Any = None
        self._privacy_face_app: Any = None
        self._known_faces: dict[str, np.ndarray] = {}
        self._initialized = False
        self._initialization_error: VisionInitializationError | None = None
        self._started = False
        self._device_diagnostics: dict[str, Any] = {
            "requested_device": self.requested_device,
            "actual_device": None,
            "cuda_available": None,
            "cuda_device_count": None,
            "device_name": None,
            "torch_version": None,
            "torch_cuda_build": None,
            "stages": {
                "yolo": None,
                "pose": "cpu",
                "preprocessing": "cpu",
                "sda_gcn": None,
            },
        }

    @staticmethod
    def _resolve_path(value: str | Path) -> Path:
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = VISION_ROOT / path
        return path.resolve()

    def device_diagnostics(self) -> dict[str, Any]:
        diagnostics = dict(self._device_diagnostics)
        diagnostics["stages"] = dict(self._device_diagnostics["stages"])
        if diagnostics["actual_device"] is None and self._device is not None:
            diagnostics["actual_device"] = str(self._device)
        return diagnostics

    def start(self) -> None:
        self._started = True
        self._initialization_error = None
        self._ensure_initialized()

    def prepare_camera(self, camera_id: str, session: VisionSession) -> None:
        self._ensure_initialized()
        self._camera_context(camera_id, session)

    def release_camera(self, camera_id: str) -> None:
        with self._lock:
            context = self._contexts.pop(camera_id, None)
        if context is not None:
            context.close()

    def process(self, packet: FramePacket, session: VisionSession) -> VisionResult:
        started = time.perf_counter()
        state = session.state
        self._prepare_source_epoch(state, packet)
        state.pop("vision_privacy_pose_frame_id", None)
        state.pop("vision_privacy_head_shoulders", None)
        source_timestamp = self._source_timestamp(packet)
        frame_count = (
            packet.source_frame_index + 1
            if packet.source_frame_index is not None
            else int(state.get("vision_frame_count", 0)) + 1
        )
        state["vision_frame_count"] = frame_count
        source_gap = max(0, packet.frame_id - session.last_processed_frame_id - 1) if session.last_processed_frame_id >= 0 else 0
        events: list[VisionEvent] = []

        if self._initialization_error is not None:
            raise self._initialization_error
        if frame_count % 2 == 0:
            return self._result(
                packet,
                session,
                started,
                sampled=False,
                pose_found=False,
                source_gap=source_gap,
                events=events,
            )

        self._ensure_initialized()
        context = self._camera_context(packet.camera_id, session)
        deps = self._dependencies
        assert deps is not None

        frame = packet.frame
        if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("canonical Vision requires a BGR frame with shape (H, W, 3)")
        height, width = frame.shape[:2]
        if height <= 0 or width <= 0:
            raise ValueError("canonical Vision received an empty frame")

        frame_preprocess_started = time.perf_counter()
        scale = FRAME_SIZE / max(height, width)
        new_w, new_h = int(width * scale), int(height * scale)
        prepared = deps.cv2.resize(frame, (new_w, new_h))
        pad_w, pad_h = FRAME_SIZE - new_w, FRAME_SIZE - new_h
        prepared = deps.cv2.copyMakeBorder(
            prepared,
            pad_h // 2,
            pad_h - pad_h // 2,
            pad_w // 2,
            pad_w - pad_w // 2,
            deps.cv2.BORDER_CONSTANT,
            value=(0, 0, 0),
        )
        self._record_stage_metric(state, "frame_preprocess", frame_preprocess_started)
        state["vision_geometry"] = {
            "source_width": width,
            "source_height": height,
            "vision_width": FRAME_SIZE,
            "vision_height": FRAME_SIZE,
            "scale": scale,
            "pad_x": pad_w // 2,
            "pad_y": pad_h // 2,
        }

        track_options = {"persist": True, "classes": 0, "verbose": False}
        if self._detector_device is not None:
            track_options["device"] = self._detector_device
        detector_started = time.perf_counter()
        results = context.yolo.track(prepared, **track_options)
        self._record_stage_metric(state, "detector", detector_started)
        person_found = False
        pose_found = False
        detections: list[VisionDetection] = []
        keypoints = np.zeros((25, 3), dtype=np.float32)

        detector_postprocess_started = time.perf_counter()
        boxes_obj = results[0].boxes if results else None
        if boxes_obj is not None and len(boxes_obj) > 0:
            boxes = boxes_obj.xyxy.cpu().numpy()
            best_idx = int(np.argmax((boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])))
            x1, y1, x2, y2 = map(int, boxes[best_idx])
            x1, y1 = max(0, x1 - 30), max(0, y1 - 30)
            x2, y2 = min(FRAME_SIZE, x2 + 30), min(FRAME_SIZE, y2 + 30)
            crop_w, crop_h = x2 - x1, y2 - y1

            if crop_w >= 20 and crop_h >= 20:
                person_found = True
                crop = prepared[y1:y2, x1:x2]
                confidence = self._box_value(boxes_obj, "conf", best_idx, 0.0)
                track_id = self._box_int_value(boxes_obj, "id", best_idx)
                self._record_stage_metric(
                    state, "detector_postprocess", detector_postprocess_started
                )
                face_started = time.perf_counter()
                detection_metadata = self._identity_metadata(
                    crop, track_id, state, source_timestamp, packet.frame_id
                )
                self._record_stage_metric(state, "face", face_started)
                detections.append(
                    VisionDetection(
                        label="person",
                        confidence=confidence,
                        bbox_xyxy=(x1, y1, x2, y2),
                        track_id=track_id,
                        metadata=detection_metadata,
                    )
                )
                crop_rgb = deps.cv2.cvtColor(crop, deps.cv2.COLOR_BGR2RGB)
                pose_started = time.perf_counter()
                keypoints = deps.extract_from_crop(
                    crop_rgb,
                    context.pose,
                    x1,
                    y1,
                    crop_w,
                    crop_h,
                    FRAME_SIZE,
                    FRAME_SIZE,
                )
                self._record_stage_metric(state, "pose", pose_started)
                pose_found = bool(np.any(keypoints))
                if pose_found:
                    state["vision_privacy_pose_frame_id"] = packet.frame_id
                    state["vision_privacy_head_shoulders"] = {
                        "head": keypoints[3, :2].tolist(),
                        "left_shoulder": keypoints[4, :2].tolist(),
                        "right_shoulder": keypoints[8, :2].tolist(),
                    }

                self._observe_movement(state, keypoints, source_timestamp)
        else:
            self._record_stage_metric(state, "detector_postprocess", detector_postprocess_started)

        kpts_buffer = self._buffer(state, "vision_kpts_buffer", WINDOW_SIZE)
        frame_ids = self._buffer(state, "vision_sampled_frame_ids", WINDOW_SIZE)
        timestamps = self._buffer(state, "vision_sampled_timestamps", WINDOW_SIZE)
        source_timestamps = self._buffer(state, "vision_sampled_source_timestamps", WINDOW_SIZE)
        if not person_found:
            self._reset_for_no_person(state)

        kpts_buffer.append(keypoints)
        frame_ids.append(packet.frame_id)
        timestamps.append(packet.captured_at)
        source_timestamps.append(source_timestamp)

        raw_class: int | None = None
        probabilities: list[float] | None = None
        logits: list[float] | None = None
        window_ids: list[int] | None = None
        window_timestamps: list[float] | None = None
        window_source_timestamps: list[float] | None = None
        model_window_index: int | None = None

        if source_timestamps and source_timestamp - source_timestamps[0] >= WINDOW_SECONDS:
            fall_started = time.perf_counter()
            fall_preprocess_started = time.perf_counter()
            raw_array = self._resample_frames(np.asarray(kpts_buffer, dtype=np.float32), WINDOW_SIZE, deps)
            cleaned = deps.clean_out_of_bounds_data(raw_array)
            normalized = deps.normalize_skeleton_dynamic(cleaned)
            transformed = normalized - normalized[:, 0:1, :]
            transformed = deps.normalize_pose(transformed)
            transformed = deps.interpolate_missing(transformed)
            transformed = deps.apply_kalman_filter(transformed)
            data_numpy = transformed.transpose(2, 0, 1)
            data_numpy = data_numpy[:, :, :, np.newaxis]
            model_data = self._model_input(data_numpy, deps)
            data_tensor = deps.torch.FloatTensor(model_data).unsqueeze(0).to(self._device)
            if tuple(data_tensor.shape) != (1, 3, WINDOW_SIZE, 25, 1):
                raise RuntimeError(f"Invalid SDA-GCN input shape: {tuple(data_tensor.shape)}")
            self._record_stage_metric(state, "fall_preprocess", fall_preprocess_started)
            fall_inference_started = time.perf_counter()
            with deps.torch.inference_mode():
                output = self._action_model(data_tensor)
                self._record_stage_metric(state, "fall_inference", fall_inference_started)
                fall_postprocess_started = time.perf_counter()
                expected_output = (1, self.OUTPUT_CLASSES)
                if tuple(output.shape) != expected_output:
                    raise RuntimeError(f"SDA-GCN must return shape {expected_output}, got {tuple(output.shape)}")
                if not bool(deps.torch.isfinite(output).all().item()):
                    raise RuntimeError("SDA-GCN returned non-finite logits")
                probability_tensor = deps.torch.softmax(output, dim=1).squeeze(0)
                raw_class = int(deps.torch.argmax(probability_tensor).item())
                probabilities = [float(value) for value in probability_tensor.detach().cpu().tolist()]
                logits = [float(value) for value in output.squeeze(0).detach().cpu().tolist()]
                self._record_stage_metric(state, "fall_postprocess", fall_postprocess_started)
            self._record_stage_metric(state, "fall", fall_started)

            model_window_index = int(state.get("vision_model_window_index", 0)) + 1
            state["vision_model_window_index"] = model_window_index
            window_ids = list(frame_ids)
            window_timestamps = list(timestamps)
            window_source_timestamps = list(source_timestamps)
            state["vision_last_raw_class"] = raw_class
            state["vision_last_probabilities"] = probabilities

            decisions = state.setdefault("vision_pending_decisions", [])
            decisions.append(
                {
                    "created_at": source_timestamp,
                    "is_fall": raw_class == self.FALL_CLASS_ID,
                    "confidence": probabilities[self.FALL_CLASS_ID],
                    "cancelled": False,
                    "last_raw_kpts": raw_array[-1] if raw_class == self.FALL_CLASS_ID else None,
                    "incident_id": None,
                }
            )
            state["vision_pending_fall"] = any(item["is_fall"] for item in decisions)
            if state["vision_pending_fall"] and state.get("vision_current_action") != FALL_LABEL:
                state["vision_fall_state"] = "pending"

            while source_timestamps and source_timestamp - source_timestamps[0] > WINDOW_RETAIN_SECONDS:
                kpts_buffer.popleft()
                frame_ids.popleft()
                timestamps.popleft()
                source_timestamps.popleft()

        events.extend(self._advance_decisions(state, source_timestamp, packet.frame_id))

        return self._result(
            packet,
            session,
            started,
            sampled=True,
            pose_found=pose_found,
            source_gap=source_gap,
            detections=detections,
            events=events,
            raw_class=raw_class,
            probabilities=probabilities,
            logits=logits,
            model_window_index=model_window_index,
            window_ids=window_ids,
            window_timestamps=window_timestamps,
            window_source_timestamps=window_source_timestamps,
        )

    def stop(self) -> None:
        with self._lock:
            for context in self._contexts.values():
                context.close()
            self._contexts.clear()
            self._action_model = None
            self._face_app = None
            self._privacy_face_app = None
            self._known_faces.clear()
            self._dependencies = None
            self._device = None
            self._initialized = False
            self._initialization_error = None
            self._started = False

    def set_identity_enabled(self, enabled: bool) -> None:
        """Toggle optional InsightFace work without rebuilding detector/fall models."""
        enabled = bool(enabled)
        with self._lock:
            if enabled and self._initialized and self._face_app is None:
                from insightface.app import FaceAnalysis

                providers, face_ctx_id = self._identity_execution(self._device)
                face_app = FaceAnalysis(
                    name="buffalo_l", root=str(self.insightface_root), providers=providers
                )
                face_app.prepare(ctx_id=face_ctx_id, det_size=(640, 640))
                self._face_app = face_app
            self.identity_enabled = enabled

    def detect_faces_for_privacy(self, frame: np.ndarray) -> list[tuple[int, int, int, int]]:
        """Detect face boxes only, without recognition or identity state changes."""
        face_app = self._privacy_detector()
        with self._face_lock:
            bboxes, _ = face_app.det_model.detect(frame, max_num=0, metric="default")
        return [tuple(int(value) for value in bbox[:4]) for bbox in bboxes]

    def _privacy_detector(self):
        self._ensure_initialized()
        with self._lock:
            face_app = self._privacy_face_app
            if face_app is None:
                from insightface.app import FaceAnalysis

                face_app = FaceAnalysis(
                    name="buffalo_l",
                    root=str(self.insightface_root),
                    # DirectML's SCRFD detector can terminate the process with
                    # an access violation in this one-shot path. Privacy evidence
                    # must fail closed, so isolate it on the stable CPU provider.
                    providers=["CPUExecutionProvider"],
                    allowed_modules=["detection"],
                )
                face_app.prepare(ctx_id=-1, det_size=(640, 640))
                self._privacy_face_app = face_app
        return face_app

    def _ensure_initialized(self) -> None:
        if self._initialized:
            return
        if self._initialization_error is not None:
            raise self._initialization_error
        with self._lock:
            if self._initialized:
                return
            try:
                self._initialize_shared()
            except Exception as exc:
                error = exc if isinstance(exc, VisionInitializationError) else VisionInitializationError(str(exc))
                self._initialization_error = error
                raise error from exc
            self._initialized = True

    def _initialize_shared(self) -> None:
        for label, path in (
            ("YOLO weight", self.yolo_path),
            ("SDA-GCN config", self.config_path),
            ("SDA-GCN checkpoint", self.checkpoint_path),
        ):
            if not path.is_file():
                raise VisionInitializationError(f"Missing {label}: {path}")

        deps = self._load_dependencies()
        with self.config_path.open("r", encoding="utf-8") as handle:
            config = deps.yaml.safe_load(handle)
        model_args = dict(config.get("model_args") or {})
        expected = self.EXPECTED_MODEL
        actual = {name: model_args.get(name) for name in expected}
        if actual != expected:
            raise VisionInitializationError(f"Expected SDA-GCN config {expected}, got {actual}")
        if config.get("test_feeder_args", {}).get("bone") is not self.EXPECTED_BONE_MODALITY:
            raise VisionInitializationError(
                f"SDA-GCN config bone modality must be {self.EXPECTED_BONE_MODALITY}"
            )
        model_args["graph"] = "src.vision.graph.ntu_rgb_d_hierarchy.Graph"

        try:
            capability_plan = VisionRuntimeResolver.resolve_capability_plan(
                deps.torch,
                self.requested_device,
                openvino_devices=VisionRuntimeResolver.available_openvino_devices(),
                ort_providers=VisionRuntimeResolver.available_ort_providers(),
                identity_provider=self.identity_provider,
            )
        except (RuntimeError, ValueError) as exc:
            raise VisionInitializationError(str(exc)) from exc
        self._capability_plan = capability_plan
        self._device_diagnostics["profile"] = capability_plan.profile
        device = self._select_torch_device(deps.torch)
        detector_path, detector_device, detector_diagnostics = VisionRuntimeResolver.resolve_detector(
            deps.YOLO,
            self.yolo_path,
            self.model_cache_dir,
            self.requested_device,
            device,
        )
        action_model = deps.Model(**model_args).to(device)
        try:
            weights = deps.torch.load(self.checkpoint_path, map_location=device, weights_only=True)
        except TypeError:
            weights = deps.torch.load(self.checkpoint_path, map_location=device)
        if not isinstance(weights, dict):
            raise VisionInitializationError("SDA-GCN checkpoint must contain a state_dict mapping")
        weights = OrderedDict((key.split("module.")[-1], value) for key, value in weights.items())
        try:
            action_model.load_state_dict(weights, strict=False)
        except Exception as exc:
            raise VisionInitializationError(f"Invalid SDA-GCN checkpoint: {exc}") from exc
        action_model.eval()
        action_model, action_diagnostics = VisionRuntimeResolver.resolve_action_model(
            action_model,
            self.checkpoint_path,
            self.config_path,
            self.model_cache_dir,
            self.requested_device,
            deps.torch,
        )

        face_app = None
        known_faces: dict[str, np.ndarray] = {}
        if self.identity_enabled:
            model_dir = self.insightface_root / "models" / "buffalo_l"
            required = {"1k3d68.onnx", "2d106det.onnx", "det_10g.onnx", "genderage.onnx", "w600k_r50.onnx"}
            present = {path.name for path in model_dir.glob("*.onnx")} if model_dir.is_dir() else set()
            missing = sorted(required - present)
            if missing:
                raise VisionInitializationError(
                    f"Missing local InsightFace buffalo_l resources in {model_dir}: {', '.join(missing)}"
                )
            providers, face_ctx_id = self._identity_execution(device)
            face_app = deps.FaceAnalysis(
                name="buffalo_l",
                providers=providers,
                root=str(self.insightface_root),
            )
            face_app.prepare(ctx_id=face_ctx_id, det_size=(640, 640))
            self._device_diagnostics["stages"]["identity"] = providers[0]
            if self._face_gallery is None:
                known_faces = self._load_known_faces(face_app, deps.cv2)

        self._dependencies = deps
        self._device = device
        self._detector_model_path = detector_path
        self._detector_device = detector_device
        self._device_diagnostics["stages"]["yolo"] = detector_diagnostics
        self._device_diagnostics["stages"]["sda_gcn"] = action_diagnostics
        accelerated_stages = {
            name
            for name, diagnostics in (("detector", detector_diagnostics), ("fall", action_diagnostics))
            if diagnostics["runtime"] == "openvino"
        }
        if accelerated_stages:
            self._device_diagnostics.update(
                {
                    "actual_device": "mixed",
                    "device_name": "Intel GPU + CPU",
                    "runtime": "hybrid-openvino-pytorch",
                    "accelerated": True,
                    "fallback_reason": None,
                }
            )
        self._action_model = action_model
        self._face_app = face_app
        self._known_faces = known_faces

    def _identity_execution(self, torch_device: Any) -> tuple[list[str], int]:
        del torch_device
        try:
            if self._capability_plan is not None:
                providers = self._capability_plan.identity_providers
                context_id = self._capability_plan.identity_context_id
            else:
                providers, context_id = VisionRuntimeResolver.resolve_identity_execution(
                    VisionRuntimeResolver.available_ort_providers(),
                    self.identity_provider,
                )
        except (RuntimeError, ValueError) as exc:
            raise VisionInitializationError(str(exc)) from exc
        return list(providers), context_id

    def _select_torch_device(self, torch: Any) -> Any:
        cuda_available = bool(torch.cuda.is_available())
        cuda_count = int(torch.cuda.device_count()) if cuda_available else 0
        self._device_diagnostics.update(
            {
                "cuda_available": cuda_available,
                "cuda_device_count": cuda_count,
                "torch_version": str(torch.__version__),
                "torch_cuda_build": torch.version.cuda,
            }
        )
        try:
            device, plan = VisionRuntimeResolver.resolve_pytorch(torch, self.requested_device)
        except RuntimeError as exc:
            raise VisionInitializationError(str(exc)) from exc
        self._device_diagnostics.update(
            {
                "actual_device": str(device),
                "cuda_available": cuda_available,
                "cuda_device_count": cuda_count,
                "device_name": plan.device_name,
                "runtime": plan.runtime,
                "accelerated": plan.accelerated,
                "fallback_reason": plan.fallback_reason,
                "torch_version": str(torch.__version__),
                "torch_cuda_build": torch.version.cuda,
                "stages": {
                    "yolo": str(device),
                    "pose": "cpu",
                    "preprocessing": "cpu",
                    "sda_gcn": str(device),
                },
            }
        )
        return device

    def _load_dependencies(self) -> SimpleNamespace:
        try:
            import cv2
            import mediapipe as mp
            import torch
            import yaml
            from scipy.interpolate import interp1d
            from ultralytics import YOLO

            from src.vision.extractkpt.extractkpt import (
                clean_out_of_bounds_data,
                extract_from_crop,
                normalize_skeleton_dynamic,
            )
            from src.vision.fusion.interpolate import interpolate_missing
            from src.vision.fusion.kalman_filter import apply_kalman_filter
            from src.vision.fusion.normalize_pose import normalize_pose
            from src.vision.model.SDAGCN import Model
        except ImportError as exc:
            raise VisionInitializationError(f"Missing canonical Vision dependency: {exc}") from exc
        face_analysis = None
        if self.identity_enabled:
            try:
                from insightface import app as insightface_app

                face_analysis = insightface_app.FaceAnalysis
            except ImportError as exc:
                raise VisionInitializationError(f"Missing canonical Vision identity dependency: {exc}") from exc

        return SimpleNamespace(
            cv2=cv2,
            mp=mp,
            torch=torch,
            yaml=yaml,
            FaceAnalysis=face_analysis,
            YOLO=YOLO,
            Model=Model,
            interp1d=interp1d,
            clean_out_of_bounds_data=clean_out_of_bounds_data,
            extract_from_crop=extract_from_crop,
            normalize_skeleton_dynamic=normalize_skeleton_dynamic,
            normalize_pose=normalize_pose,
            interpolate_missing=interpolate_missing,
            apply_kalman_filter=apply_kalman_filter,
        )

    @staticmethod
    def _model_input(data_numpy: np.ndarray, deps: SimpleNamespace) -> np.ndarray:
        del deps
        return data_numpy

    @staticmethod
    def _resample_frames(kpts_array: np.ndarray, target_frames: int, deps: SimpleNamespace) -> np.ndarray:
        frame_count, vertices, channels = kpts_array.shape
        if frame_count == target_frames:
            return kpts_array
        if frame_count == 0:
            return np.zeros((target_frames, vertices, channels), dtype=np.float32)
        if frame_count == 1:
            return np.repeat(kpts_array, target_frames, axis=0)
        old_axis = np.linspace(0, 1, frame_count)
        new_axis = np.linspace(0, 1, target_frames)
        flattened = kpts_array.reshape(frame_count, -1)
        interpolator = deps.interp1d(old_axis, flattened, axis=0, kind="linear", fill_value="extrapolate")
        return interpolator(new_axis).reshape(target_frames, vertices, channels)

    def _camera_context(self, camera_id: str, session: VisionSession) -> CameraContext:
        with self._lock:
            context = self._contexts.get(camera_id)
            token = session.state.setdefault("vision_context_token", object())
            if context is not None and context.session_token is not token:
                context.close()
                self._contexts.pop(camera_id, None)
                context = None
            if context is None:
                assert self._dependencies is not None
                yolo = self._dependencies.YOLO(
                    str(self._detector_model_path),
                    task="detect",
                    verbose=False,
                )
                if self._detector_device is None:
                    yolo.to(self._device)
                pose = self._dependencies.mp.solutions.pose.Pose(
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
                context = CameraContext(yolo=yolo, pose=pose, session_token=token)
                self._contexts[camera_id] = context
            return context

    def _identity_metadata(
        self,
        crop: np.ndarray,
        track_id: int | None,
        state: dict[str, Any],
        source_timestamp: float,
        frame_id: int,
    ) -> dict[str, Any]:
        if not state.get("vision_identity_enabled", self.identity_enabled):
            return {}
        assert self._face_app is not None
        cache = state.setdefault("vision_face_cache", {})
        entry = cache.get(track_id) if track_id is not None else None
        if entry is not None:
            if entry["status"] in {"RECOGNIZED", "LOCKED_UNKNOWN"}:
                return dict(entry["metadata"])
            if (
                int(entry["attempts"]) >= FACE_RECOGNITION_MAX_ATTEMPTS
                or source_timestamp - float(entry["last_attempt_at"]) < FACE_RECOGNITION_INTERVAL_SECONDS
            ):
                return dict(entry["metadata"])
        if entry is None and track_id is not None:
            entry = self._new_identity_cache_entry()
            cache[track_id] = entry
        try:
            with self._face_lock:
                identity_inference_started = time.perf_counter()
                faces = self._face_app.get(crop)
                self._record_stage_metric(state, "identity_inference", identity_inference_started)
        except Exception as exc:  # Face failure must not stop fall detection.
            logger.warning("Face recognition failed camera track=%s: %s", track_id, exc)
            return {
                "identity_status": "UNKNOWN",
                "identity_name": None,
                "identity_person_id": None,
                "identity_similarity": 0.0,
                "identity_error": str(exc),
            }
        if entry is not None:
            entry["last_attempt_at"] = source_timestamp
        if not faces:
            metadata = self._pending_identity_metadata()
            if entry is not None:
                entry["metadata"] = metadata
            return metadata
        if entry is not None:
            # Confirmation counts qualifying identity observations, not failed
            # face-detector scans. A missed face remains retryable on the same
            # track instead of permanently poisoning its five-attempt budget.
            entry["attempts"] += 1
        main_face = max(faces, key=lambda face: (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1]))
        best_name, best_person_id, best_score = self._closest_known_identity(
            main_face.embedding
        )
        known = best_score > 0.45
        metadata = {
            "identity_status": "KNOWN" if known else "UNKNOWN",
            "identity_name": best_name if known else None,
            "identity_person_id": best_person_id if known else None,
            "identity_similarity": best_score,
            "identity_state": "RECOGNIZED" if known else "PENDING",
            "identity_face_detected": True,
            "identity_face_bbox_xyxy": [
                int(main_face.bbox[0]),
                int(main_face.bbox[1]),
                int(main_face.bbox[2]),
                int(main_face.bbox[3]),
            ],
            "identity_face_bbox_frame_id": frame_id,
        }
        if entry is not None:
            entry["metadata"] = metadata
            if known:
                entry["status"] = "RECOGNIZED"
            elif entry["attempts"] >= FACE_RECOGNITION_MAX_ATTEMPTS:
                entry["status"] = "LOCKED_UNKNOWN"
                metadata["identity_state"] = "LOCKED_UNKNOWN"
        if len(cache) > 100:
            for cached_track_id in list(cache)[:-50]:
                cache.pop(cached_track_id, None)
        return metadata

    @classmethod
    def _new_identity_cache_entry(cls) -> dict[str, Any]:
        return {
            "status": "PENDING",
            "attempts": 0,
            "last_attempt_at": float("-inf"),
            "metadata": cls._pending_identity_metadata(),
        }

    @staticmethod
    def _pending_identity_metadata() -> dict[str, Any]:
        return {
            "identity_status": "UNKNOWN",
            "identity_name": None,
            "identity_person_id": None,
            "identity_similarity": 0.0,
            "identity_state": "PENDING",
            "identity_face_detected": False,
        }

    def _closest_known_identity(
        self, embedding: np.ndarray
    ) -> tuple[str | None, str | None, float]:
        known_faces = (
            self._face_gallery.snapshot()
            if self._face_gallery is not None
            else tuple(
                SimpleNamespace(person_id=None, name=name, embedding=embedding)
                for name, embedding in self._known_faces.items()
            )
        )
        best_name: str | None = None
        best_person_id: str | None = None
        best_score = 0.0
        for known_face in known_faces:
            score = self._cosine_similarity(known_face.embedding, embedding)
            if score > best_score:
                best_score = score
                best_name = known_face.name
                best_person_id = known_face.person_id
        return best_name, best_person_id, best_score

    def _load_known_faces(self, face_app: Any, cv2: Any) -> dict[str, np.ndarray]:
        known_faces: dict[str, np.ndarray] = {}
        if not self.known_faces_dir.is_dir():
            return known_faces
        for item in self.known_faces_dir.iterdir():
            if item.is_dir():
                embeddings = []
                for image_path in item.iterdir():
                    if image_path.name.endswith((".jpg", ".png", ".jpeg")):
                        image = cv2.imread(str(image_path))
                        if image is None:
                            continue
                        faces = face_app.get(image)
                        if faces:
                            embeddings.append(faces[0].embedding)
                if embeddings:
                    known_faces[item.name] = np.mean(embeddings, axis=0)
            elif item.name.endswith((".jpg", ".png", ".jpeg")):
                image = cv2.imread(str(item))
                if image is None:
                    continue
                faces = face_app.get(image)
                if faces:
                    known_faces[item.stem] = faces[0].embedding
        return known_faces

    @staticmethod
    def _cosine_similarity(first: np.ndarray, second: np.ndarray) -> float:
        return float(np.dot(first, second) / (np.linalg.norm(first) * np.linalg.norm(second)))

    @staticmethod
    def _buffer(state: dict[str, Any], name: str, maxlen: int) -> deque:
        del maxlen
        value = state.get(name)
        if value is None:
            value = deque()
            state[name] = value
        if not isinstance(value, deque) or value.maxlen is not None:
            raise TypeError(f"{name} must be an unbounded deque")
        return value

    @staticmethod
    def _box_value(boxes: Any, name: str, index: int, default: float) -> float:
        values = getattr(boxes, name, None)
        if values is None:
            return default
        return float(values[index].detach().cpu().item())

    @staticmethod
    def _box_int_value(boxes: Any, name: str, index: int) -> int | None:
        values = getattr(boxes, name, None)
        if values is None:
            return None
        return int(values[index].detach().cpu().item())

    @staticmethod
    def _record_stage_metric(state: dict[str, Any], stage: str, started: float) -> None:
        elapsed_ms = (time.perf_counter() - started) * 1000
        metrics = state.setdefault("vision_stage_metrics", {})
        current = metrics.setdefault(
            stage,
            {
                "count": 0,
                "total_ms": 0.0,
                "last_ms": 0.0,
                "max_ms": 0.0,
                "samples_ms": deque(maxlen=2048),
                "sample_times": deque(maxlen=2048),
            },
        )
        current["count"] += 1
        current["total_ms"] += elapsed_ms
        current["last_ms"] = elapsed_ms
        current["max_ms"] = max(current["max_ms"], elapsed_ms)
        current["samples_ms"].append(elapsed_ms)
        current["sample_times"].append(time.monotonic())

    @staticmethod
    def _reset_for_no_person(state: dict[str, Any]) -> None:
        for decision in state.setdefault("vision_pending_decisions", []):
            decision["cancelled"] = True
        state["vision_pending_fall"] = False
        if state.get("vision_current_action") == FALL_LABEL:
            state["vision_incident_id"] = None
            state["vision_current_action"] = "Khong nga"
            state["vision_fall_state"] = "normal"
        else:
            state["vision_fall_state"] = "normal"

    @staticmethod
    def _source_timestamp(packet: FramePacket) -> float:
        return packet.captured_at if packet.source_timestamp is None else packet.source_timestamp

    @staticmethod
    def _prepare_source_epoch(state: dict[str, Any], packet: FramePacket) -> None:
        previous_epoch = state.get("vision_source_epoch")
        if packet.discontinuity or (previous_epoch is not None and previous_epoch != packet.source_epoch):
            retained = {
                "vision_context_token",
                "vision_frame_count",
                "vision_stage_metrics",
                # Feature flags and their invalidation generation belong to
                # the camera control plane, not to a source epoch. The
                # feature-specific retry/cache state is intentionally reset.
                "vision_identity_enabled",
                "vision_identity_generation",
            }
            for key in [
                name for name in state if name.startswith("vision_") and name not in retained
            ]:
                state.pop(key, None)
        state["vision_source_epoch"] = packet.source_epoch

    @staticmethod
    def _observe_movement(state: dict[str, Any], keypoints: np.ndarray, source_timestamp: float) -> None:
        if state.get("vision_current_action") == FALL_LABEL:
            previous = state.get("vision_last_raw_kpts")
            if previous is not None:
                movement = float(np.mean(np.linalg.norm(keypoints - previous, axis=1)))
                state["vision_movement"] = movement
                if movement > MOVEMENT_THRESHOLD:
                    state["vision_current_action"] = "Khong nga"
                    state["vision_fall_state"] = "normal"
                    state["vision_incident_id"] = None
                    for decision in state.setdefault("vision_pending_decisions", []):
                        decision["cancelled"] = True
            state["vision_last_raw_kpts"] = keypoints

        decisions = state.setdefault("vision_pending_decisions", [])
        for decision in decisions:
            if decision["cancelled"]:
                continue
            elapsed = source_timestamp - float(decision["created_at"])
            previous = decision.get("last_raw_kpts")
            if elapsed < MOVEMENT_CHECK_SECONDS:
                decision["last_raw_kpts"] = keypoints
            elif elapsed < DECISION_DELAY_SECONDS and decision["is_fall"] and previous is not None:
                movement = float(np.mean(np.linalg.norm(keypoints - previous, axis=1)))
                if movement > MOVEMENT_THRESHOLD:
                    decision["cancelled"] = True
                decision["last_raw_kpts"] = keypoints

    def _advance_decisions(
        self,
        state: dict[str, Any],
        source_timestamp: float,
        frame_id: int,
    ) -> list[VisionEvent]:
        events: list[VisionEvent] = []
        was_pending = bool(state.get("vision_pending_fall", False))
        active = []
        for decision in state.setdefault("vision_pending_decisions", []):
            if decision["cancelled"]:
                continue
            if source_timestamp - float(decision["created_at"]) < DECISION_DELAY_SECONDS:
                active.append(decision)
                continue
            if decision["is_fall"]:
                if state.get("vision_current_action") != FALL_LABEL:
                    incident_id = str(self._incident_factory())
                    state["vision_current_action"] = FALL_LABEL
                    state["vision_fall_state"] = "confirmed"
                    state["vision_incident_id"] = incident_id
                    state["vision_last_raw_kpts"] = decision.get("last_raw_kpts")
                    events.append(
                        VisionEvent(
                            type="fall_confirmed",
                            confidence=float(decision["confidence"]),
                            metadata={
                                "incident_id": incident_id,
                                "event_id": f"{incident_id}:fall_confirmed",
                                "snapshot_path": None,
                            },
                        )
                    )
                    state["vision_event_frame_id"] = frame_id
                    state["vision_event_source_time"] = source_timestamp
            else:
                state["vision_current_action"] = "Khong nga"
                state["vision_fall_state"] = "normal"
                state["vision_incident_id"] = None
        state["vision_pending_decisions"] = active
        state["vision_pending_fall"] = any(item["is_fall"] for item in active)
        if state["vision_pending_fall"] and state.get("vision_current_action") != FALL_LABEL:
            state["vision_fall_state"] = "pending"
        elif was_pending and state.get("vision_current_action") != FALL_LABEL:
            state["vision_current_action"] = "Khong nga"
            state["vision_fall_state"] = "normal"
        elif state.get("vision_current_action") == "Khong nga":
            state["vision_fall_state"] = "normal"
        return events

    def _result(
        self,
        packet: FramePacket,
        session: VisionSession,
        started: float,
        *,
        sampled: bool,
        pose_found: bool,
        source_gap: int,
        detections: list[VisionDetection] | None = None,
        events: list[VisionEvent] | None = None,
        raw_class: int | None = None,
        probabilities: list[float] | None = None,
        logits: list[float] | None = None,
        model_window_index: int | None = None,
        window_ids: list[int] | None = None,
        window_timestamps: list[float] | None = None,
        window_source_timestamps: list[float] | None = None,
    ) -> VisionResult:
        state = session.state
        buffer_value = state.get("vision_kpts_buffer")
        metadata = {
            "engine": "runtimev2-derived",
            "device": self.device_diagnostics(),
            "sampled": sampled,
            "buffer_length": 0 if buffer_value is None else len(buffer_value),
            "fall_state": state.get("vision_fall_state", "waiting"),
            "current_action": state.get("vision_current_action", "Waiting for frames..."),
            "geometry": state.get("vision_geometry", {}),
            "pending_fall": bool(state.get("vision_pending_fall", False)),
            "incident_id": state.get("vision_incident_id"),
            "pose_found": pose_found,
            "privacy_pose_frame_id": state.get("vision_privacy_pose_frame_id"),
            "privacy_head_shoulders": state.get("vision_privacy_head_shoulders"),
            "raw_class": raw_class,
            "probabilities": probabilities,
            "logits": logits,
            "model_window_index": model_window_index,
            "internal_frame_count": state.get("vision_frame_count", 0),
            "source_frame_gap": source_gap,
            "dropped_frames": session.dropped_frames,
            "sampled_frame_id": packet.frame_id if sampled else None,
            "sampled_captured_at": packet.captured_at if sampled else None,
            "sampled_source_timestamp": self._source_timestamp(packet) if sampled else None,
            "observation_time": self._source_timestamp(packet),
            "source_epoch": packet.source_epoch,
            "source_time_kind": packet.source_time_kind,
            "source_discontinuity": packet.discontinuity,
            "window_frame_ids": window_ids,
            "window_captured_at": window_timestamps,
            "window_source_timestamps": window_source_timestamps,
            "window_source_time_span": (
                None
                if not window_source_timestamps
                else window_source_timestamps[-1] - window_source_timestamps[0]
            ),
            "pose_count_before_resample": None if window_ids is None else len(window_ids),
            "performance": {
                stage: {
                    "count": values["count"],
                    "last_ms": values["last_ms"],
                    "mean_ms": values["total_ms"] / values["count"],
                    "max_ms": values["max_ms"],
                }
                for stage, values in state.get("vision_stage_metrics", {}).items()
            },
        }
        return VisionResult(
            camera_id=packet.camera_id,
            frame_id=packet.frame_id,
            captured_at=packet.captured_at,
            processed_at=self._clock(),
            processing_ms=(time.perf_counter() - started) * 1000,
            detections=detections or [],
            events=events or [],
            metadata=metadata,
        )


# Compatibility name for external test/tool imports. Production constructs
# RuntimeV2VisionPipeline explicitly.
CanonicalVisionPipeline = RuntimeV2VisionPipeline


