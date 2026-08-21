"""Per-stage inference adapters; no fall-detection policy lives here."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
import hashlib
import time
from typing import Any, Callable
import warnings

import numpy as np
import torch

from .hardware import BackendSpec, FaceProviderSpec


@dataclass(frozen=True)
class StageSpec:
    name: str
    backend: str
    device: str
    precision: str
    reason: str = ""

    @property
    def label(self) -> str:
        return f"{self.backend} {self.device}".strip()


def _checkpoint_state(path: Path) -> OrderedDict:
    # Always deserialize through CPU so CUDA-trained checkpoints are portable.
    try:
        weights = torch.load(str(path), map_location="cpu", weights_only=True)
    except TypeError:  # PyTorch before weights_only was introduced
        weights = torch.load(str(path), map_location="cpu")
    if isinstance(weights, dict) and "state_dict" in weights:
        weights = weights["state_dict"]
    return OrderedDict((key.split("module.")[-1], value) for key, value in weights.items())


class ActionInference:
    INPUT_SHAPE = (1, 3, 64, 25, 1)

    def __init__(self, model: torch.nn.Module, weights_path: str | Path, spec: BackendSpec, cache_dir: str | Path):
        self.requested_spec = spec
        self.model = model.cpu()
        weights_path = Path(weights_path)
        self.model.load_state_dict(_checkpoint_state(weights_path), strict=False)
        self.model.eval()
        self.compiled_model = None
        self.input_port = None
        self.last_inference_ms = 0.0
        self.last_started_monotonic_s = None
        self.last_finished_monotonic_s = None
        self.last_started_wall_time_s = None
        self.last_finished_wall_time_s = None
        self.invocation_count = 0
        initialized_at = time.perf_counter()
        fingerprint = hashlib.sha256(weights_path.read_bytes())
        for name, value in self.model.state_dict().items():
            fingerprint.update(f"{name}:{tuple(value.shape)}".encode())
        self.stage = self._initialize(spec, Path(cache_dir), fingerprint.hexdigest()[:16])
        self.model_initialize_ms = (time.perf_counter() - initialized_at) * 1000.0
        warmed_at = time.perf_counter()
        self(np.zeros(self.INPUT_SHAPE, dtype=np.float32))
        self.model_warmup_ms = (time.perf_counter() - warmed_at) * 1000.0
        self.last_inference_ms = 0.0
        self.invocation_count = 0

    def _initialize(self, spec: BackendSpec, cache_dir: Path, fingerprint: str) -> StageSpec:
        if spec.backend == "openvino":
            try:
                from openvino import Core, convert_model, save_model
                cache_dir.mkdir(parents=True, exist_ok=True)
                xml_path = cache_dir / f"sda_gcn_1x3x64x25x1_{fingerprint}.xml"
                if not xml_path.exists():
                    example = torch.zeros(self.INPUT_SHAPE, dtype=torch.float32)
                    ov_model = convert_model(self.model, example_input=example)
                    save_model(ov_model, xml_path, compress_to_fp16=True)
                core = Core()
                core.set_property({"CACHE_DIR": str(cache_dir / "compiled")})
                self.compiled_model = core.compile_model(str(xml_path), "GPU", {"INFERENCE_PRECISION_HINT": "f16"})
                self.input_port = self.compiled_model.input(0)
                self.model = None
                return StageSpec("SDA-GCN", "OpenVINO", "GPU", "fp16")
            except Exception as exc:
                raise RuntimeError(f"SDA-GCN OpenVINO GPU initialization failed: {exc}") from exc

        device: Any = spec.device
        if spec.backend == "torch_directml":
            import torch_directml
            device = torch_directml.device(int(str(spec.device).split(":", 1)[1]))
        self.device = torch.device(device) if isinstance(device, str) and spec.backend != "torch_directml" else device
        self.model = self.model.to(self.device)
        return StageSpec("SDA-GCN", spec.display_backend, str(spec.device), spec.precision)

    def __call__(self, data: np.ndarray | torch.Tensor) -> torch.Tensor:
        started = time.perf_counter()
        self.last_started_monotonic_s = started
        self.last_started_wall_time_s = time.time()
        if self.compiled_model is not None:
            array = data.detach().cpu().numpy() if isinstance(data, torch.Tensor) else np.asarray(data)
            result = self.compiled_model({self.input_port: array.astype(np.float32, copy=False)})
            output = torch.from_numpy(np.asarray(result[self.compiled_model.output(0)]))
        else:
            tensor = data if isinstance(data, torch.Tensor) else torch.from_numpy(np.asarray(data))
            dtype = torch.float16 if self.stage.precision == "fp16" else torch.float32
            tensor = tensor.to(device=self.device, dtype=dtype)
            try:
                with torch.inference_mode():
                    output = self.model(tensor).float().cpu()
            except Exception as exc:
                raise RuntimeError(f"SDA-GCN DirectML inference failed: {exc}") from exc
        self.last_finished_monotonic_s = time.perf_counter()
        self.last_finished_wall_time_s = time.time()
        self.last_inference_ms = (self.last_finished_monotonic_s - started) * 1000.0
        self.invocation_count += 1
        return output

    def close(self) -> None:
        """Release native accelerator objects deterministically on Windows."""
        self.input_port = None
        self.compiled_model = None
        self.model = None


def face_stage_spec(spec: FaceProviderSpec) -> StageSpec:
    backend = "ONNX Runtime" if spec.backend.startswith("ONNX Runtime") else spec.backend
    return StageSpec("Face", backend, spec.device, spec.precision, spec.reason)


def print_diagnostics(spec: BackendSpec, pose: StageSpec, action: StageSpec, face: StageSpec) -> None:
    print("\n[Vision Runtime]")
    print(f"Mode            : {spec.mode.upper()}")
    print(f"Vendor          : {spec.vendor}")
    print(f"Backend         : {spec.display_backend}")
    print(f"Device          : {spec.device}")
    print(f"DeviceName      : {spec.device_name}")
    print(f"Precision       : {spec.precision.upper()}")
    print(f"Pose backend    : {pose.label} ({pose.precision.upper()})")
    print(f"SDA-GCN backend : {action.label} ({action.precision.upper()})")
    if face.backend == "DISABLED":
        print("Face backend    : DISABLED\n")
    else:
        print(f"Face backend    : {face.label} ({face.precision.upper()})\n")
