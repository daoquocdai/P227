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
from src.vision.session import VisionSession

logger = logging.getLogger(__name__)

VISION_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INSIGHTFACE_ROOT = Path.home() / ".insightface"
WINDOW_SIZE = 64
STRIDE = 32
MOVEMENT_THRESHOLD = 0.2
FRAME_SIZE = 1024
FALL_LABEL = "FALL DETECTED!"
UNKNOWN_PERSON_COOLDOWN_SECONDS = 30.0


class LegacyVisionInitializationError(RuntimeError):
    """A required local Legacy Vision resource or model is invalid."""


@dataclass
class LegacyCameraContext:
    yolo: Any
    pose: Any
    session_token: object

    def close(self) -> None:
        close = getattr(self.pose, "close", None)
        if callable(close):
            close()


class LegacyVisionEngine(VisionEngine):
    """FramePacket adapter for the binary two-class pipeline in realtime.py.

    The engine is called sequentially by the current VisionWorker. FaceAnalysis
    is shared only under that boundary. YOLO tracking and MediaPipe Pose remain
    isolated per camera because both retain stream state.
    """

    EXPECTED_MODEL = {"num_class": 2, "num_person": 1, "num_point": 25, "in_channels": 3}
    EXPECTED_BONE_MODALITY = True
    OUTPUT_CLASSES = 2
    FALL_CLASS_ID = 1

    def __init__(
        self,
        yolo_path: str | Path = VISION_ROOT / "yolov8n.pt",
        config_path: str | Path = VISION_ROOT / "work_dir" / "fall_detection" / "ntu25-bone" / "config.yaml",
        checkpoint_path: str | Path = VISION_ROOT / "work_dir" / "fall_detection" / "ntu25-bone" / "runs-best_val.pt",
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
        self.known_faces_dir = self._resolve_path(known_faces_dir)
        self.insightface_root = self._resolve_path(insightface_root)
        self.identity_enabled = identity_enabled
        self.identity_provider = identity_provider.strip().lower()
        self.requested_device = self._normalize_device(device)
        self._face_gallery = face_gallery
        self._clock = clock
        self._incident_factory = incident_factory
        self._lock = threading.RLock()
        self._contexts: dict[str, LegacyCameraContext] = {}
        self._dependencies: SimpleNamespace | None = None
        self._device: Any = None
        self._action_model: Any = None
        self._face_app: Any = None
        self._known_faces: dict[str, np.ndarray] = {}
        self._initialized = False
        self._initialization_error: LegacyVisionInitializationError | None = None
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

    @staticmethod
    def _normalize_device(value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"auto", "cpu", "cuda"}:
            return normalized
        if normalized.startswith("cuda:") and normalized[5:].isdigit():
            return normalized
        raise ValueError("device must be auto, cpu, cuda, or cuda:N")

    def device_diagnostics(self) -> dict[str, Any]:
        diagnostics = dict(self._device_diagnostics)
        diagnostics["stages"] = dict(self._device_diagnostics["stages"])
        if diagnostics["actual_device"] is None and self._device is not None:
            diagnostics["actual_device"] = str(self._device)
        return diagnostics

    def start(self) -> None:
        # Heavy resources intentionally remain lazy so FastAPI startup is safe.
        self._started = True
        self._initialization_error = None

    def process(self, packet: FramePacket, session: VisionSession) -> VisionResult:
        started = time.perf_counter()
        state = session.state
        self._prepare_source_epoch(state, packet)
        source_timestamp = self._source_timestamp(packet)
        frame_count = int(state.get("legacy_frame_count", 0)) + 1
        state["legacy_frame_count"] = frame_count
        source_gap = max(0, packet.frame_id - session.last_processed_frame_id - 1) if session.last_processed_frame_id >= 0 else 0
        events: list[VisionEvent] = []

        if self._initialization_error is not None:
            raise self._initialization_error
        if frame_count % 2 == 0:
            events = self._advance_fall_clock(state, source_timestamp, packet.frame_id)
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
            raise ValueError("Legacy Vision requires a BGR frame with shape (H, W, 3)")
        height, width = frame.shape[:2]
        if height <= 0 or width <= 0:
            raise ValueError("Legacy Vision received an empty frame")

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

        results = context.yolo.track(prepared, persist=True, classes=0, verbose=False)
        person_found = False
        pose_found = False
        detections: list[VisionDetection] = []
        keypoints = np.zeros((25, 3), dtype=np.float32)

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
                detection_metadata = self._identity_metadata(crop)
                if detection_metadata.get("identity_status") == "UNKNOWN":
                    last_unknown_at = state.get("legacy_last_unknown_event_source_time")
                    if last_unknown_at is None or source_timestamp - float(last_unknown_at) >= UNKNOWN_PERSON_COOLDOWN_SECONDS:
                        unknown_event_id = str(self._incident_factory())
                        events.append(
                            VisionEvent(
                                type="unknown_person",
                                confidence=max(
                                    0.0,
                                    min(1.0, 1.0 - float(detection_metadata.get("identity_similarity", 0.0))),
                                ),
                                metadata={
                                    "event_id": f"{unknown_event_id}:unknown_person",
                                    "track_id": track_id,
                                    "identity_status": "UNKNOWN",
                                    "identity_name": None,
                                    "snapshot_path": None,
                                },
                            )
                        )
                        state["legacy_last_unknown_event_source_time"] = source_timestamp
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
                pose_found = bool(np.any(keypoints))

                if state.get("legacy_pending_fall", False) or state.get("legacy_current_action") == FALL_LABEL:
                    last_raw = state.get("legacy_last_raw_kpts")
                    if last_raw is not None:
                        movement = float(np.mean(np.linalg.norm(keypoints - last_raw, axis=1)))
                        state["legacy_movement"] = movement
                        if movement > MOVEMENT_THRESHOLD:
                            self._reset_episode(state)
                    state["legacy_last_raw_kpts"] = keypoints

        kpts_buffer = self._buffer(state, "legacy_kpts_buffer", WINDOW_SIZE)
        frame_ids = self._buffer(state, "legacy_sampled_frame_ids", WINDOW_SIZE)
        timestamps = self._buffer(state, "legacy_sampled_timestamps", WINDOW_SIZE)
        source_timestamps = self._buffer(state, "legacy_sampled_source_timestamps", WINDOW_SIZE)
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

        if len(kpts_buffer) == WINDOW_SIZE:
            raw_array = np.asarray(kpts_buffer, dtype=np.float32)
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
            with deps.torch.inference_mode():
                output = self._action_model(data_tensor)
                expected_output = (1, self.OUTPUT_CLASSES)
                if tuple(output.shape) != expected_output:
                    raise RuntimeError(f"SDA-GCN must return shape {expected_output}, got {tuple(output.shape)}")
                if not bool(deps.torch.isfinite(output).all().item()):
                    raise RuntimeError("Binary SDA-GCN returned non-finite logits")
                probability_tensor = deps.torch.softmax(output, dim=1).squeeze(0)
                raw_class = int(deps.torch.argmax(probability_tensor).item())
                probabilities = [float(value) for value in probability_tensor.detach().cpu().tolist()]
                logits = [float(value) for value in output.squeeze(0).detach().cpu().tolist()]

            model_window_index = int(state.get("legacy_model_window_index", 0)) + 1
            state["legacy_model_window_index"] = model_window_index
            window_ids = list(frame_ids)
            window_timestamps = list(timestamps)
            window_source_timestamps = list(source_timestamps)
            state["legacy_last_raw_class"] = raw_class
            state["legacy_last_probabilities"] = probabilities

            if raw_class == self.FALL_CLASS_ID:
                if not state.get("legacy_pending_fall", False) and state.get("legacy_current_action") != FALL_LABEL:
                    state["legacy_pending_fall"] = True
                    state["legacy_fall_start_time"] = window_source_timestamps[-1]
                    state["legacy_last_raw_kpts"] = raw_array[-1]
                    state["legacy_incident_id"] = str(self._incident_factory())
                    state["legacy_confirmed_event_emitted"] = False
                    state["legacy_fall_state"] = "pending"
                    state["legacy_pending_confidence"] = probabilities[1]
            else:
                self._reset_episode(state)

            for _ in range(STRIDE):
                kpts_buffer.popleft()
                frame_ids.popleft()
                timestamps.popleft()
                source_timestamps.popleft()

        events.extend(self._advance_fall_clock(state, source_timestamp, packet.frame_id))

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
            self._known_faces.clear()
            self._dependencies = None
            self._device = None
            self._initialized = False
            self._initialization_error = None
            self._started = False

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
                error = exc if isinstance(exc, LegacyVisionInitializationError) else LegacyVisionInitializationError(str(exc))
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
                raise LegacyVisionInitializationError(f"Missing {label}: {path}")

        deps = self._load_dependencies()
        with self.config_path.open("r", encoding="utf-8") as handle:
            config = deps.yaml.safe_load(handle)
        model_args = dict(config.get("model_args") or {})
        expected = self.EXPECTED_MODEL
        actual = {name: model_args.get(name) for name in expected}
        if actual != expected:
            raise LegacyVisionInitializationError(f"Expected SDA-GCN config {expected}, got {actual}")
        if config.get("test_feeder_args", {}).get("bone") is not self.EXPECTED_BONE_MODALITY:
            raise LegacyVisionInitializationError(
                f"SDA-GCN config bone modality must be {self.EXPECTED_BONE_MODALITY}"
            )
        model_args["graph"] = "src.vision.graph.ntu_rgb_d_hierarchy.Graph"

        device = self._select_torch_device(deps.torch)
        action_model = deps.Model(**model_args).to(device)
        try:
            weights = deps.torch.load(self.checkpoint_path, map_location=device, weights_only=True)
        except TypeError:
            weights = deps.torch.load(self.checkpoint_path, map_location=device)
        if not isinstance(weights, dict):
            raise LegacyVisionInitializationError("SDA-GCN checkpoint must contain a state_dict mapping")
        weights = OrderedDict((key.split("module.")[-1], value) for key, value in weights.items())
        try:
            action_model.load_state_dict(weights, strict=True)
        except Exception as exc:
            raise LegacyVisionInitializationError(f"Invalid SDA-GCN checkpoint: {exc}") from exc
        action_model.eval()

        face_app = None
        known_faces: dict[str, np.ndarray] = {}
        if self.identity_enabled:
            model_dir = self.insightface_root / "models" / "buffalo_l"
            required = {"1k3d68.onnx", "2d106det.onnx", "det_10g.onnx", "genderage.onnx", "w600k_r50.onnx"}
            present = {path.name for path in model_dir.glob("*.onnx")} if model_dir.is_dir() else set()
            missing = sorted(required - present)
            if missing:
                raise LegacyVisionInitializationError(
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
        self._action_model = action_model
        self._face_app = face_app
        self._known_faces = known_faces

    def _identity_execution(self, torch_device: Any) -> tuple[list[str], int]:
        if self.identity_provider not in {"auto", "cpu", "directml"}:
            raise LegacyVisionInitializationError(
                "Identity provider must be auto, cpu, or directml"
            )
        try:
            import onnxruntime as ort
        except ImportError as exc:
            raise LegacyVisionInitializationError(f"Missing ONNX Runtime: {exc}") from exc
        available = set(ort.get_available_providers())
        if self.identity_provider in {"auto", "directml"} and "DmlExecutionProvider" in available:
            return ["DmlExecutionProvider", "CPUExecutionProvider"], 0
        if self.identity_provider == "directml":
            raise LegacyVisionInitializationError("DirectML was requested but is unavailable")
        use_cuda = getattr(torch_device, "type", str(torch_device).split(":", 1)[0]) == "cuda"
        if use_cuda and "CUDAExecutionProvider" in available:
            return ["CUDAExecutionProvider", "CPUExecutionProvider"], 0
        return ["CPUExecutionProvider"], -1

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
        requested = self.requested_device
        if requested == "auto":
            selected = "cuda:0" if cuda_available and cuda_count > 0 else "cpu"
        elif requested == "cpu":
            selected = "cpu"
        else:
            index = 0 if requested == "cuda" else int(requested.split(":", 1)[1])
            if not cuda_available:
                raise LegacyVisionInitializationError(
                    f"Requested Vision device {requested!r}, but CUDA is unavailable "
                    f"(torch={torch.__version__}, torch.version.cuda={torch.version.cuda!r})"
                )
            if index >= cuda_count:
                raise LegacyVisionInitializationError(
                    f"Requested Vision device {requested!r}, but only {cuda_count} CUDA device(s) are available"
                )
            selected = f"cuda:{index}"

        device = torch.device(selected)
        device_name = torch.cuda.get_device_name(device) if device.type == "cuda" else "CPU"
        self._device_diagnostics.update(
            {
                "actual_device": str(device),
                "cuda_available": cuda_available,
                "cuda_device_count": cuda_count,
                "device_name": device_name,
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
            from ultralytics import YOLO

            from src.vision.extractkpt.extractkpt import (
                clean_out_of_bounds_data,
                extract_from_crop,
                normalize_skeleton_dynamic,
            )
            from src.vision.feeders.bone_pairs import ntu_pairs
            from src.vision.fusion.interpolate import interpolate_missing
            from src.vision.fusion.kalman_filter import apply_kalman_filter
            from src.vision.fusion.normalize_pose import normalize_pose
            from src.vision.model.SDAGCN import Model
        except ImportError as exc:
            raise LegacyVisionInitializationError(f"Missing Legacy Vision dependency: {exc}") from exc
        face_analysis = None
        if self.identity_enabled:
            try:
                from insightface import app as insightface_app

                face_analysis = insightface_app.FaceAnalysis
            except ImportError as exc:
                raise LegacyVisionInitializationError(f"Missing Legacy Vision identity dependency: {exc}") from exc

        return SimpleNamespace(
            cv2=cv2,
            mp=mp,
            torch=torch,
            yaml=yaml,
            FaceAnalysis=face_analysis,
            YOLO=YOLO,
            Model=Model,
            clean_out_of_bounds_data=clean_out_of_bounds_data,
            extract_from_crop=extract_from_crop,
            normalize_skeleton_dynamic=normalize_skeleton_dynamic,
            normalize_pose=normalize_pose,
            interpolate_missing=interpolate_missing,
            apply_kalman_filter=apply_kalman_filter,
            ntu_pairs=ntu_pairs,
        )

    @staticmethod
    def _model_input(data_numpy: np.ndarray, deps: SimpleNamespace) -> np.ndarray:
        bone_data = np.zeros_like(data_numpy)
        for v1, v2 in deps.ntu_pairs:
            bone_data[:, :, v1] = data_numpy[:, :, v1] - data_numpy[:, :, v2]
        return bone_data

    def _camera_context(self, camera_id: str, session: VisionSession) -> LegacyCameraContext:
        with self._lock:
            context = self._contexts.get(camera_id)
            token = session.state.setdefault("legacy_context_token", object())
            if context is not None and context.session_token is not token:
                context.close()
                self._contexts.pop(camera_id, None)
                context = None
            if context is None:
                assert self._dependencies is not None
                yolo = self._dependencies.YOLO(str(self.yolo_path), verbose=False)
                yolo.to(self._device)
                pose = self._dependencies.mp.solutions.pose.Pose(
                    min_detection_confidence=0.5,
                    min_tracking_confidence=0.5,
                )
                context = LegacyCameraContext(yolo=yolo, pose=pose, session_token=token)
                self._contexts[camera_id] = context
            return context

    def _identity_metadata(self, crop: np.ndarray) -> dict[str, Any]:
        if not self.identity_enabled:
            return {}
        assert self._face_app is not None
        faces = self._face_app.get(crop)
        best_name: str | None = None
        best_score = 0.0
        if not faces:
            return {
                "identity_status": "UNKNOWN",
                "identity_name": None,
                "identity_person_id": None,
                "identity_similarity": 0.0,
            }
        main_face = max(faces, key=lambda face: (face.bbox[2] - face.bbox[0]) * (face.bbox[3] - face.bbox[1]))
        known_faces = (
            self._face_gallery.snapshot()
            if self._face_gallery is not None
            else tuple(
                SimpleNamespace(person_id=None, name=name, embedding=embedding)
                for name, embedding in self._known_faces.items()
            )
        )
        best_person_id: str | None = None
        for known_face in known_faces:
            name = known_face.name
            known_embedding = known_face.embedding
            score = self._cosine_similarity(known_embedding, main_face.embedding)
            if score > best_score:
                best_score = score
                best_name = name
                best_person_id = known_face.person_id
        known = best_score > 0.45
        return {
            "identity_status": "KNOWN" if known else "UNKNOWN",
            "identity_name": best_name if known else None,
            "identity_person_id": best_person_id if known else None,
            "identity_similarity": best_score,
        }

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
        value = state.get(name)
        if value is None:
            value = deque(maxlen=maxlen)
            state[name] = value
        if not isinstance(value, deque) or value.maxlen != maxlen:
            raise TypeError(f"{name} must be deque(maxlen={maxlen})")
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
    def _reset_episode(state: dict[str, Any]) -> None:
        state["legacy_pending_fall"] = False
        state["legacy_current_action"] = "Normal"
        state["legacy_fall_state"] = "normal"
        state["legacy_incident_id"] = None
        state["legacy_confirmed_event_emitted"] = False
        state["legacy_pending_confidence"] = None

    @staticmethod
    def _reset_for_no_person(state: dict[str, Any]) -> None:
        was_pending = bool(state.get("legacy_pending_fall", False))
        was_confirmed = state.get("legacy_current_action") == FALL_LABEL
        state["legacy_pending_fall"] = False
        state["legacy_incident_id"] = None
        state["legacy_confirmed_event_emitted"] = False
        state["legacy_pending_confidence"] = None
        if was_confirmed:
            state["legacy_current_action"] = "Normal"
            state["legacy_fall_state"] = "normal"
        elif was_pending or state.get("legacy_current_action") == "Normal":
            state["legacy_fall_state"] = "normal"
        elif state.get("legacy_current_action") is None:
            state["legacy_fall_state"] = "waiting"

    @staticmethod
    def _source_timestamp(packet: FramePacket) -> float:
        return packet.captured_at if packet.source_timestamp is None else packet.source_timestamp

    @staticmethod
    def _prepare_source_epoch(state: dict[str, Any], packet: FramePacket) -> None:
        previous_epoch = state.get("legacy_source_epoch")
        if packet.discontinuity or (previous_epoch is not None and previous_epoch != packet.source_epoch):
            for key in [name for name in state if name.startswith("legacy_")]:
                state.pop(key, None)
        state["legacy_source_epoch"] = packet.source_epoch

    def _advance_fall_clock(
        self,
        state: dict[str, Any],
        source_timestamp: float,
        frame_id: int,
    ) -> list[VisionEvent]:
        events: list[VisionEvent] = []
        if not state.get("legacy_pending_fall", False):
            return events
        if source_timestamp - float(state["legacy_fall_start_time"]) < 2.0:
            state["legacy_current_action"] = "Normal"
            state["legacy_fall_state"] = "pending"
            return events

        state["legacy_current_action"] = FALL_LABEL
        state["legacy_fall_state"] = "confirmed"
        state["legacy_pending_fall"] = False
        if not state.get("legacy_confirmed_event_emitted", False):
            incident_id = str(state["legacy_incident_id"])
            events.append(
                VisionEvent(
                    type="fall_confirmed",
                    confidence=float(state.get("legacy_pending_confidence", 0.0)),
                    metadata={
                        "incident_id": incident_id,
                        "event_id": f"{incident_id}:fall_confirmed",
                        "snapshot_path": None,
                    },
                )
            )
            state["legacy_confirmed_event_emitted"] = True
            state["legacy_event_frame_id"] = frame_id
            state["legacy_event_source_time"] = source_timestamp
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
        buffer_value = state.get("legacy_kpts_buffer")
        metadata = {
            "engine": "legacy",
            "device": self.device_diagnostics(),
            "sampled": sampled,
            "buffer_length": 0 if buffer_value is None else len(buffer_value),
            "fall_state": state.get("legacy_fall_state", "waiting"),
            "pending_fall": bool(state.get("legacy_pending_fall", False)),
            "incident_id": state.get("legacy_incident_id"),
            "pose_found": pose_found,
            "raw_class": raw_class,
            "probabilities": probabilities,
            "logits": logits,
            "model_window_index": model_window_index,
            "internal_frame_count": state.get("legacy_frame_count", 0),
            "source_frame_gap": source_gap,
            "dropped_frames": session.dropped_frames,
            "sampled_frame_id": packet.frame_id if sampled else None,
            "sampled_captured_at": packet.captured_at if sampled else None,
            "sampled_source_timestamp": self._source_timestamp(packet) if sampled else None,
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
