"""Central capability probing and backend selection.

Selection is based on a backend being importable and usable. OS adapter names are
only used to distinguish an AMD DirectML candidate; they never establish that a
compute provider works.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import platform
import subprocess
from typing import Callable, Optional, Sequence
import warnings


class BackendResolutionError(RuntimeError):
    """Raised when a manually requested accelerator is unavailable."""


class FaceAccelerationError(RuntimeError):
    """Raised when GPU-first Identity cannot obtain a matching ORT provider."""


@dataclass(frozen=True)
class HardwareCapabilities:
    torch_cuda: bool = False
    torch_hip: bool = False
    torch_device_name: str = ""
    directml_usable: bool = False
    directml_device_index: int = 0
    directml_device_name: str = ""
    openvino_gpu: bool = False
    openvino_gpu_name: str = ""
    adapter_names: tuple[str, ...] = field(default_factory=tuple)
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def has_amd_adapter(self) -> bool:
        return any("amd" in name.lower() or "radeon" in name.lower() for name in self.adapter_names)


@dataclass(frozen=True)
class BackendSpec:
    backend: str
    device: object
    vendor: str
    precision: str
    provider: str
    reason: str
    device_name: str
    mode: str = "auto"

    @property
    def display_backend(self) -> str:
        return {
            "torch_cuda": "PyTorch CUDA",
            "torch_rocm": "PyTorch ROCm",
            "torch_directml": "PyTorch DirectML",
            "openvino": "OpenVINO",
            "cpu": "PyTorch CPU",
        }[self.backend]


@dataclass(frozen=True)
class FaceProviderSpec:
    backend: str
    providers: tuple[str, ...]
    device: str
    precision: str
    reason: str


def _has_vendor(caps: HardwareCapabilities, vendor: str) -> bool:
    return any(vendor in name.lower() for name in caps.adapter_names)


def _windows_adapter_names() -> tuple[str, ...]:
    if platform.system() != "Windows":
        return ()
    try:
        command = [
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=4, check=False)
        return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())
    except (OSError, subprocess.SubprocessError):
        return ()


def probe_capabilities() -> HardwareCapabilities:
    notes: list[str] = []
    cuda_available = False
    hip_available = False
    torch_name = ""
    try:
        import torch
        cuda_available = bool(torch.cuda.is_available())
        hip_available = bool(getattr(torch.version, "hip", None))
        if cuda_available:
            torch_name = torch.cuda.get_device_name(0)
    except (ImportError, RuntimeError) as exc:
        notes.append(f"PyTorch accelerator probe failed: {exc}")

    ov_gpu = False
    ov_name = ""
    if importlib.util.find_spec("openvino") is not None:
        try:
            from openvino import Core
            core = Core()
            gpu_devices = [name for name in core.available_devices if name.split(".", 1)[0] == "GPU"]
            if gpu_devices:
                # Compiling the actual model remains a per-stage check.
                ov_gpu = True
                ov_name = str(core.get_property(gpu_devices[0], "FULL_DEVICE_NAME"))
        except Exception as exc:  # provider failures have backend-specific types
            notes.append(f"OpenVINO GPU probe failed: {exc}")

    adapters = _windows_adapter_names()
    dml_usable = False
    dml_index = 0
    dml_name = ""
    if platform.system() == "Windows" and importlib.util.find_spec("torch_directml") is not None:
        try:
            import torch
            import torch_directml
            count = int(torch_directml.device_count())
            for index in range(count):
                name = str(torch_directml.device_name(index))
                if "amd" not in name.lower() and "radeon" not in name.lower():
                    continue
                device = torch_directml.device(index)
                # Exercise an operation, rather than treating import success as capability.
                (torch.ones(1).to(device) + 1).cpu()
                dml_usable, dml_index, dml_name = True, index, name
                break
        except Exception as exc:
            notes.append(f"DirectML probe failed: {exc}")

    return HardwareCapabilities(
        torch_cuda=cuda_available,
        torch_hip=hip_available,
        torch_device_name=torch_name,
        directml_usable=dml_usable,
        directml_device_index=dml_index,
        directml_device_name=dml_name,
        openvino_gpu=ov_gpu,
        openvino_gpu_name=ov_name,
        adapter_names=adapters,
        warnings=tuple(notes),
    )


def resolve_action_backend(
    requested: str = "auto",
    capabilities: Optional[HardwareCapabilities] = None,
) -> BackendSpec:
    requested = requested.lower()
    if requested not in {"auto", "cuda", "amd", "intel", "cpu"}:
        raise BackendResolutionError(f"Unknown device mode: {requested}")
    caps = capabilities or probe_capabilities()
    for note in caps.warnings:
        warnings.warn(note, RuntimeWarning, stacklevel=2)

    def nvidia() -> Optional[BackendSpec]:
        if caps.torch_cuda and not caps.torch_hip:
            return BackendSpec("torch_cuda", "cuda:0", "NVIDIA", "fp32", "CUDA", "NVIDIA CUDA is usable", caps.torch_device_name or "CUDA GPU", requested)
        return None

    def amd() -> Optional[BackendSpec]:
        if caps.torch_cuda and caps.torch_hip:
            return BackendSpec("torch_rocm", "cuda:0", "AMD", "fp32", "ROCm", "PyTorch ROCm is usable", caps.torch_device_name or "AMD GPU", requested)
        if caps.has_amd_adapter and caps.directml_usable:
            name = caps.directml_device_name or next(name for name in caps.adapter_names if "amd" in name.lower() or "radeon" in name.lower())
            return BackendSpec("torch_directml", f"directml:{caps.directml_device_index}", "AMD", "fp32", "DirectML", "AMD adapter and DirectML operation are usable", name, requested)
        return None

    def intel() -> Optional[BackendSpec]:
        if caps.openvino_gpu:
            return BackendSpec("openvino", "GPU", "Intel", "fp16", "OpenVINO GPU", "OpenVINO exposes a usable GPU device", caps.openvino_gpu_name or "GPU", requested)
        return None

    if requested == "cuda":
        result = nvidia()
        if result is None:
            raise BackendResolutionError("Requested CUDA backend but NVIDIA CUDA is unavailable.")
        return result
    if requested == "amd":
        result = amd()
        if result is None:
            raise BackendResolutionError("Requested AMD backend but neither PyTorch ROCm nor AMD DirectML is usable.")
        return result
    if requested == "intel":
        result = intel()
        if result is None:
            raise BackendResolutionError("Requested Intel backend but OpenVINO GPU is unavailable.")
        return result
    if requested == "cpu":
        return BackendSpec("cpu", "cpu", "CPU", "fp32", "CPU", "CPU was explicitly requested", "CPU", requested)

    result = nvidia() or amd() or intel()
    if result is not None:
        return result
    if caps.has_amd_adapter and not caps.directml_usable:
        warnings.warn("AMD GPU detected, but DirectML is unavailable; falling back to CPU.", RuntimeWarning, stacklevel=2)
    if any("intel" in name.lower() for name in caps.adapter_names) and not caps.openvino_gpu:
        warnings.warn("Intel GPU detected, but OpenVINO GPU is unavailable; falling back to CPU.", RuntimeWarning, stacklevel=2)
    return BackendSpec("cpu", "cpu", "CPU", "fp32", "CPU", "No supported accelerator backend is usable", "CPU", requested)


def resolve_backend(
    requested: str = "auto",
    capabilities: Optional[HardwareCapabilities] = None,
) -> BackendSpec:
    """Backward-compatible alias for the Action-stage resolver."""
    return resolve_action_backend(requested, capabilities)


def resolve_face_providers(
    requested: str,
    capabilities: HardwareCapabilities,
    available_onnx_providers: Sequence[str],
    system: str | None = None,
) -> FaceProviderSpec:
    """Resolve InsightFace independently from the Action compute runtime."""
    requested = requested.lower()
    if requested not in {"auto", "cuda", "amd", "intel", "directml", "cpu"}:
        raise BackendResolutionError(f"Unknown device mode: {requested}")
    available = set(available_onnx_providers)
    system = system or platform.system()
    cpu = "CPUExecutionProvider"

    if requested == "cpu":
        if cpu not in available:
            raise FaceAccelerationError("CPUExecutionProvider is unavailable for explicit CPU Identity.")
        return FaceProviderSpec("ONNX Runtime CPU", (cpu,), "CPU", "fp32", "CPU was explicitly requested")

    nvidia = capabilities.torch_cuda and not capabilities.torch_hip
    amd_linux = capabilities.torch_cuda and capabilities.torch_hip and system != "Windows"
    intel = capabilities.openvino_gpu or _has_vendor(capabilities, "intel")
    amd_windows = system == "Windows" and capabilities.has_amd_adapter

    if requested == "cuda" or (requested == "auto" and nvidia):
        if "CUDAExecutionProvider" not in available:
            raise FaceAccelerationError("NVIDIA GPU is usable but CUDAExecutionProvider is unavailable for Identity.")
        chain = ("CUDAExecutionProvider",) + ((cpu,) if cpu in available else ())
        return FaceProviderSpec("ONNX Runtime CUDA", chain, "CUDA", "fp32", "CUDAExecutionProvider is available")

    if (
        requested in {"intel", "amd", "directml"} and system == "Windows"
        or requested == "auto" and (intel or amd_windows)
    ):
        if "DmlExecutionProvider" not in available:
            vendor = "Intel" if intel and requested != "amd" else "AMD"
            raise FaceAccelerationError(f"{vendor} GPU is present but DmlExecutionProvider is unavailable for Identity.")
        chain = ("DmlExecutionProvider",) + ((cpu,) if cpu in available else ())
        return FaceProviderSpec("ONNX Runtime DirectML", chain, "DirectML", "fp32", "DmlExecutionProvider is available")

    if requested == "amd" or (requested == "auto" and amd_linux):
        raise FaceAccelerationError(
            "AMD Linux GPU Identity has no supported ONNX Runtime GPU provider in this application profile."
        )

    if requested in {"cuda", "amd", "intel", "directml"}:
        raise FaceAccelerationError(f"Requested {requested} Identity accelerator is unavailable.")
    if cpu not in available:
        raise FaceAccelerationError("No supported GPU exists and CPUExecutionProvider is unavailable.")
    return FaceProviderSpec("ONNX Runtime CPU", (cpu,), "CPU", "fp32", "No supported GPU accelerator is present")
