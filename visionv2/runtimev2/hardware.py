"""Hardware-only execution glue for the immutable VisionV2 oracle."""

from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import tempfile
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
from einops import rearrange, repeat

RUNTIME_ROOT = Path(__file__).resolve().parent
ORACLE_ROOT = RUNTIME_ROOT.parent / "P-227-thi"
CACHE_ROOT = RUNTIME_ROOT / ".cache"


@dataclass(frozen=True)
class RuntimeSelection:
    requested: str
    profile: str
    torch_device: torch.device
    detector_runtime: str
    action_runtime: str
    face_providers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "requested": self.requested,
            "profile": self.profile,
            "torch_device": str(self.torch_device),
            "detector": self.detector_runtime,
            "sda_gcn": self.action_runtime,
            "pose": "cpu",
            "face_providers": list(self.face_providers),
        }


def _intel_gpu_available() -> bool:
    try:
        from openvino import Core

        return any(value == "GPU" or value.startswith("GPU.") for value in Core().available_devices)
    except Exception:
        return False


def _available_face_providers() -> set[str]:
    try:
        import onnxruntime as ort

        return set(ort.get_available_providers())
    except ImportError:
        return {"CPUExecutionProvider"}


def select_runtime(requested: str) -> RuntimeSelection:
    requested = requested.strip().lower()
    if requested not in {"auto", "cuda", "intel", "cpu"}:
        raise ValueError("device must be auto, cuda, intel, or cpu")

    cuda = bool(torch.cuda.is_available())
    intel = _intel_gpu_available()
    if requested == "cuda":
        if not cuda:
            raise RuntimeError("CUDA was requested but torch.cuda.is_available() is false")
        profile = "cuda"
    elif requested == "intel":
        if not intel:
            raise RuntimeError("Intel was requested but OpenVINO exposes no Intel GPU")
        profile = "intel"
    elif requested == "cpu":
        profile = "cpu"
    else:
        profile = "cuda" if cuda else "intel" if intel else "cpu"

    available = _available_face_providers()
    if profile == "cuda" and "CUDAExecutionProvider" in available:
        face = ("CUDAExecutionProvider", "CPUExecutionProvider")
    elif profile == "intel" and "DmlExecutionProvider" in available:
        face = ("DmlExecutionProvider", "CPUExecutionProvider")
    else:
        face = ("CPUExecutionProvider",)

    torch_device = torch.device("cuda" if profile == "cuda" else "cpu")
    return RuntimeSelection(
        requested=requested,
        profile=profile,
        torch_device=torch_device,
        detector_runtime="openvino:GPU" if profile == "intel" else f"pytorch:{torch_device}",
        action_runtime="openvino:GPU:FP32" if profile == "intel" else f"pytorch:{torch_device}",
        face_providers=face,
    )


def apply_device_safety_shim(model_module: Any) -> None:
    """Replace only the oracle's negative-device-index tensor creation."""

    def get_graph_feature(self, x, k, idx=None):
        n, channels, vertices = x.size()
        if idx is None:
            idx = self.knn(x, k=k)
        device = x.device
        idx_base = torch.arange(0, n, device=device).view(-1, 1, 1) * vertices
        idx = (idx + idx_base).view(-1)
        values = rearrange(x, "n c v -> n v c")
        feature = rearrange(values, "n v c -> (n v) c")[idx, :]
        feature = feature.view(n, vertices, k, channels)
        values = repeat(values, "n v c -> n v k c", k=k)
        feature = torch.cat((feature - values, values), dim=3)
        return rearrange(feature, "n v k c -> n c v k")

    model_module.EdgeConv.get_graph_feature = get_graph_feature


class OpenVINOActionModel:
    def __init__(self, compiled_model: Any) -> None:
        self.compiled_model = compiled_model

    def __call__(self, tensor: torch.Tensor) -> torch.Tensor:
        values = tensor.detach().cpu().numpy()
        output = next(iter(self.compiled_model(values).values()))
        return torch.from_numpy(output)

    def eval(self) -> OpenVINOActionModel:
        return self


def load_action_model(config: dict[str, Any], weights_path: Path, selection: RuntimeSelection) -> Any:
    module_name, separator, class_name = str(config["model"]).rpartition(".")
    if not separator:
        raise ImportError(f"Invalid oracle model path: {config['model']}")
    model_module = importlib.import_module(module_name)
    apply_device_safety_shim(model_module)
    model_class = getattr(model_module, class_name)
    action_model = model_class(**config.get("model_args", {})).to(selection.torch_device)
    weights = torch.load(weights_path, map_location=selection.torch_device, weights_only=False)
    weights = OrderedDict((key.split("module.")[-1], value) for key, value in weights.items())
    action_model.load_state_dict(weights, strict=False)
    action_model.eval()
    if selection.profile != "intel":
        return action_model

    import openvino as ov

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(weights_path.read_bytes()).hexdigest()[:12]
    model_path = CACHE_ROOT / f"sdagcn-{digest}.xml"
    if not model_path.is_file():
        example = torch.zeros((1, 3, 64, 25, 1), dtype=torch.float32)
        converted = ov.convert_model(action_model, example_input=example)
        ov.save_model(converted, model_path, compress_to_fp16=False)
    compiled = ov.Core().compile_model(
        str(model_path),
        "GPU",
        {"PERFORMANCE_HINT": "LATENCY", "INFERENCE_PRECISION_HINT": "f32"},
    )
    print(f"[*] SDA-GCN OpenVINO execution devices: {compiled.get_property('EXECUTION_DEVICES')}")
    return OpenVINOActionModel(compiled).eval()


def detector_source(weight_path: Path, selection: RuntimeSelection, yolo_class: Any) -> Path:
    if selection.profile != "intel":
        return weight_path
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(weight_path.read_bytes()).hexdigest()[:12]
    artifact = CACHE_ROOT / f"{weight_path.stem}-{digest}_openvino_model"
    if any(artifact.glob("*.xml")):
        return artifact

    with tempfile.TemporaryDirectory(prefix="yolo-export-", dir=CACHE_ROOT) as temp:
        staged_weight = Path(temp) / weight_path.name
        try:
            os.link(weight_path, staged_weight)
        except OSError:
            shutil.copy2(weight_path, staged_weight)
        exported = Path(
            yolo_class(str(staged_weight), verbose=False).export(
                format="openvino",
                imgsz=640,
                dynamic=False,
                batch=1,
            )
        )
        if artifact.exists():
            raise RuntimeError(f"Incomplete detector cache exists: {artifact}")
        shutil.move(str(exported), str(artifact))
    return artifact
