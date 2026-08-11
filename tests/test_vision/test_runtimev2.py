from types import SimpleNamespace

import pytest
import torch

from visionv2.runtimev2 import realtime
from visionv2.runtimev2.hardware import ORACLE_ROOT, apply_device_safety_shim, select_runtime


def test_help_does_not_initialize_inference(monkeypatch):
    monkeypatch.setattr(
        realtime,
        "run",
        lambda args: pytest.fail(f"--help initialized inference: {args}"),
    )

    with pytest.raises(SystemExit) as exit_info:
        realtime.main(["--help"])

    assert exit_info.value.code == 0


def test_runtimev2_references_oracle_assets_without_weights_copy():
    assert realtime.ORACLE_DIR == ORACLE_ROOT
    assert (ORACLE_ROOT / "yolov8n.pt").is_file()
    assert (
        ORACLE_ROOT / "work_dir" / "fall_detection" / "joint" / "runs-best_val.pt"
    ).is_file()
    assert not list(realtime.BASE_DIR.glob("*.pt"))


def test_device_safety_shim_uses_tensor_device(monkeypatch):
    class EdgeConv:
        def knn(self, values, k):
            del values
            return torch.tensor([[[0]]])

    module = SimpleNamespace(EdgeConv=EdgeConv)
    apply_device_safety_shim(module)
    layer = EdgeConv()

    result = layer.get_graph_feature(torch.ones((1, 1, 1)), 1)

    assert result.device.type == "cpu"
    assert result.shape == (1, 2, 1, 1)


def test_cpu_profile_is_hardware_only(monkeypatch):
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    monkeypatch.setattr(
        "visionv2.runtimev2.hardware._intel_gpu_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "visionv2.runtimev2.hardware._available_face_providers",
        lambda: {"CPUExecutionProvider"},
    )

    selection = select_runtime("auto")

    assert selection.profile == "cpu"
    assert selection.torch_device == torch.device("cpu")
    assert selection.face_providers == ("CPUExecutionProvider",)


def test_runtimev2_has_no_production_vision_imports():
    for path in realtime.BASE_DIR.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert "src.vision" not in source
        assert "VisionSampleBuffer" not in source
        assert "CanonicalVisionPipeline" not in source
