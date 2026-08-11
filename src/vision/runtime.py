import hashlib
import logging
import shutil
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VisionRuntimePlan:
    implementation: str
    runtime: str
    requested_device: str
    actual_device: str
    device_name: str
    accelerated: bool
    fallback_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class VisionRuntimeResolver:
    """Resolve the canonical model runtime once and report every fallback."""

    _export_lock = threading.Lock()

    @staticmethod
    def normalize_device(value: str) -> str:
        normalized = value.strip().lower()
        if normalized in {"auto", "cpu", "cuda"}:
            return normalized
        if normalized.startswith("cuda:") and normalized[5:].isdigit():
            return normalized
        raise ValueError("device must be auto, cpu, cuda, or cuda:N")

    @classmethod
    def resolve_pytorch(cls, torch: Any, requested_device: str) -> tuple[Any, VisionRuntimePlan]:
        requested = cls.normalize_device(requested_device)
        cuda_available = bool(torch.cuda.is_available())
        cuda_count = int(torch.cuda.device_count()) if cuda_available else 0
        fallback_reason = None

        if requested == "auto":
            if cuda_available and cuda_count:
                selected = "cuda:0"
            else:
                selected = "cpu"
                fallback_reason = (
                    "No CUDA device is available; PyTorch stages use CPU. The detector resolves its "
                    "OpenVINO/Intel GPU runtime independently."
                )
        elif requested == "cpu":
            selected = "cpu"
        else:
            index = 0 if requested == "cuda" else int(requested.split(":", 1)[1])
            if not cuda_available:
                raise RuntimeError(
                    f"Requested Vision device {requested!r}, but CUDA is unavailable "
                    f"(torch={torch.__version__}, torch.version.cuda={torch.version.cuda!r})"
                )
            if index >= cuda_count:
                raise RuntimeError(
                    f"Requested Vision device {requested!r}, but only {cuda_count} CUDA device(s) are available"
                )
            selected = f"cuda:{index}"

        device = torch.device(selected)
        device_name = torch.cuda.get_device_name(device) if device.type == "cuda" else "CPU"
        plan = VisionRuntimePlan(
            implementation="canonical",
            runtime="pytorch",
            requested_device=requested,
            actual_device=str(device),
            device_name=device_name,
            accelerated=device.type == "cuda",
            fallback_reason=fallback_reason,
        )
        logger.info(
            "Vision implementation=%s runtime=%s device=%s (%s)",
            plan.implementation,
            plan.runtime,
            plan.actual_device,
            plan.device_name,
        )
        if fallback_reason:
            logger.info("Vision PyTorch stage selection: %s", fallback_reason)
        return device, plan

    @classmethod
    def resolve_detector(
        cls,
        yolo_class: Any,
        weight_path: Path,
        cache_dir: Path,
        requested_device: str,
        pytorch_device: Any | None = None,
    ) -> tuple[Path, str | None, dict[str, Any]]:
        """Prefer a fingerprinted OpenVINO artifact on Intel GPU for auto mode."""
        if requested_device == "auto" and str(pytorch_device).startswith("cuda"):
            return weight_path, str(pytorch_device), {
                "runtime": "pytorch",
                "device": str(pytorch_device),
                "fallback_reason": None,
            }
        if requested_device != "auto":
            return weight_path, None, {"runtime": "pytorch", "device": requested_device, "fallback_reason": None}
        try:
            from openvino import Core

            available = list(Core().available_devices)
            if not any(device == "GPU" or device.startswith("GPU.") for device in available):
                raise RuntimeError(f"OpenVINO exposes {available}, not an Intel GPU")
            fingerprint = hashlib.sha256(weight_path.read_bytes()).hexdigest()[:12]
            artifact = cache_dir / f"{weight_path.stem}-{fingerprint}_openvino_model"
            if not any(artifact.glob("*.xml")):
                with cls._export_lock:
                    if not any(artifact.glob("*.xml")):
                        cache_dir.mkdir(parents=True, exist_ok=True)
                        exported = Path(
                            yolo_class(str(weight_path), task="detect", verbose=False).export(
                                format="openvino",
                                imgsz=640,
                                dynamic=False,
                                batch=1,
                            )
                        )
                        if exported.resolve() != artifact.resolve():
                            if artifact.exists():
                                raise RuntimeError(f"Incomplete OpenVINO cache already exists: {artifact}")
                            shutil.move(str(exported), str(artifact))
            diagnostics = {
                "runtime": "openvino",
                "device": "intel:gpu",
                "available_devices": available,
                "artifact": str(artifact),
                "fallback_reason": None,
            }
            logger.info("Vision detector runtime=openvino device=Intel GPU artifact=%s", artifact)
            return artifact, "intel:gpu", diagnostics
        except Exception as exc:  # Explicitly reported fallback; fall detection remains available.
            reason = str(exc)
            logger.warning("Intel GPU acceleration unavailable for detector: %s; falling back to PyTorch", reason)
            return weight_path, None, {
                "runtime": "pytorch",
                "device": "cpu",
                "fallback_reason": reason,
            }

    @classmethod
    def resolve_action_model(
        cls,
        torch_model: Any,
        checkpoint_path: Path,
        config_path: Path,
        cache_dir: Path,
        requested_device: str,
        torch: Any,
    ) -> tuple[Any, dict[str, Any]]:
        """Compile SDA-GCN as FP32 OpenVINO on Intel GPU with startup parity validation."""
        try:
            model_device = str(next(torch_model.parameters()).device)
        except (AttributeError, StopIteration):
            model_device = "cpu"
        if requested_device == "auto" and model_device.startswith("cuda"):
            return torch_model, {"runtime": "pytorch", "device": model_device, "fallback_reason": None}
        if requested_device != "auto":
            return torch_model, {"runtime": "pytorch", "device": requested_device, "fallback_reason": None}
        try:
            import numpy as np
            import openvino as ov

            core = ov.Core()
            available = list(core.available_devices)
            if not any(device == "GPU" or device.startswith("GPU.") for device in available):
                raise RuntimeError(f"OpenVINO exposes {available}, not an Intel GPU")
            digest = hashlib.sha256(checkpoint_path.read_bytes() + config_path.read_bytes()).hexdigest()[:12]
            artifact_dir = cache_dir / f"sdagcn-{digest}_openvino_model"
            artifact = artifact_dir / "sdagcn.xml"
            example = torch.zeros((1, 3, 64, 25, 1), dtype=torch.float32)
            if not artifact.is_file():
                with cls._export_lock:
                    if not artifact.is_file():
                        artifact_dir.mkdir(parents=True, exist_ok=True)
                        converted = ov.convert_model(torch_model, example_input=example)
                        ov.save_model(converted, artifact, compress_to_fp16=False)
            compiled = core.compile_model(
                str(artifact),
                "GPU",
                {
                    "PERFORMANCE_HINT": "LATENCY",
                    "INFERENCE_PRECISION_HINT": "f32",
                    "CACHE_DIR": str(cache_dir / "openvino-blob-cache-f32"),
                },
            )
            rng = np.random.default_rng(227)
            parity_input = rng.standard_normal((1, 3, 64, 25, 1), dtype=np.float32)
            with torch.inference_mode():
                reference = torch_model(torch.from_numpy(parity_input)).detach().cpu().numpy()
            accelerated = next(iter(compiled(parity_input).values()))
            max_abs = float(np.max(np.abs(reference - accelerated)))
            if max_abs > 1e-3 or int(reference.argmax()) != int(accelerated.argmax()):
                raise RuntimeError(f"SDA-GCN OpenVINO parity failed (max_abs={max_abs:.6g})")
            logger.info(
                "Vision fall runtime=openvino device=Intel GPU precision=FP32 parity_max_abs=%.6g",
                max_abs,
            )
            return OpenVINOActionModel(compiled, torch), {
                "runtime": "openvino",
                "device": "GPU",
                "precision": "FP32",
                "artifact": str(artifact),
                "parity_max_abs": max_abs,
                "fallback_reason": None,
            }
        except Exception as exc:
            reason = str(exc)
            logger.warning("Intel GPU acceleration unavailable for SDA-GCN: %s; falling back to PyTorch CPU", reason)
            return torch_model, {"runtime": "pytorch", "device": "cpu", "fallback_reason": reason}


class OpenVINOActionModel:
    """Small adapter preserving the PyTorch model call contract used by the pipeline."""

    def __init__(self, compiled_model: Any, torch: Any) -> None:
        self._compiled_model = compiled_model
        self._torch = torch
        self._lock = threading.Lock()

    def __call__(self, tensor: Any) -> Any:
        values = tensor.detach().cpu().numpy()
        # A compiled model's convenience call reuses an internal infer request.
        # Serialize only this short stage so per-camera detector/pose work may
        # still overlap without triggering "Infer Request is busy".
        with self._lock:
            output = next(iter(self._compiled_model(values).values()))
        return self._torch.from_numpy(output)

    def eval(self) -> "OpenVINOActionModel":
        return self
