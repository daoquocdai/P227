from pathlib import Path
from types import SimpleNamespace

import pytest

from src.runtime import LocalRuntime

ROOT = Path(__file__).resolve().parents[2]


def sda_settings():
    return SimpleNamespace(
        vision_engine="sda",
        vision_identity_enabled=False,
        vision_device="cpu",
        vision_fps=15.0,
        log_level="ERROR",
        vision_identity_process_priority="normal",
        vision_identity_cpu_affinity=None,
    )


def test_default_local_runtime_constructs_only_sda_facades(monkeypatch):
    monkeypatch.setattr("src.runtime.get_settings", sda_settings)
    runtime = LocalRuntime()
    assert type(runtime.camera).__module__ == "src.integrations.sda_vision"
    assert type(runtime.vision).__module__ == "src.integrations.sda_vision"
    assert hasattr(runtime, "sda")


def test_sda_initialization_failure_never_falls_back_to_legacy(monkeypatch):
    monkeypatch.setattr("src.runtime.get_settings", sda_settings)

    def fail(*_args, **_kwargs):
        raise RuntimeError("SDA unavailable")

    monkeypatch.setattr("src.integrations.sda_vision.SdaSessionRegistry", fail)
    with pytest.raises(RuntimeError, match="SDA unavailable"):
        LocalRuntime()


def test_runtime_has_no_active_legacy_runtime_construction():
    source = (ROOT / "src/runtime.py").read_text(encoding="utf-8")
    assert "src.services.synchronous_vision_manager" not in source
    assert "legacy_vision" not in source
    assert "CanonicalVisionPipeline" not in source


def test_presentation_is_inference_free_and_does_not_import_vision_runtimes():
    sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "src/presentation").glob("*.py"))
    assert "src.vision" not in sources
    assert "sda_vision" not in sources
    for forbidden in ("FaceAnalysis", "PoseLandmarker", "ActionInference", "detect(", ".get(image"):
        assert forbidden not in sources


def test_production_integration_uses_only_sda_public_api():
    source = (ROOT / "src/integrations/sda_vision.py").read_text(encoding="utf-8")
    assert "from sda_vision import" in source
    assert "sda_vision.runtime" not in source
    assert "src.vision" not in source
