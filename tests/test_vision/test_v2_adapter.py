from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
import yaml

from src.config import Settings
from src.runtime import build_vision_engine
from src.vision.adapters.legacy import LegacyVisionEngine
from src.vision.adapters.mock import MockVisionEngine
from src.vision.adapters.v2 import FALL_CLASS_ID, V2VisionEngine
from src.vision.model.SDAGCN import Model
from src.vision.session import VisionSession
from tests.test_vision.test_legacy_adapter import FakeActionModel, make_dependencies, packet


class FiveClassModel(FakeActionModel):
    def __call__(self, tensor):
        self.calls.append(tensor.detach().cpu().clone())
        predicted = self.classes.pop(0) if self.classes else 0
        logits = torch.zeros((1, 5), dtype=torch.float32)
        logits[0, predicted] = 4.0
        return logits


def make_v2_engine(tmp_path, predicted_class: int) -> V2VisionEngine:
    engine = V2VisionEngine(
        tmp_path / "yolo.pt",
        tmp_path / "config.yaml",
        tmp_path / "checkpoint.pt",
        identity_enabled=False,
    )
    engine.start()
    engine._dependencies = make_dependencies()
    engine._device = torch.device("cpu")
    engine._action_model = FiveClassModel([predicted_class])
    engine._initialized = True
    return engine


@pytest.mark.parametrize(
    ("selection", "expected_type"),
    [
        ("mock", MockVisionEngine),
        ("legacy", LegacyVisionEngine),
        ("legacy_v1", LegacyVisionEngine),
        ("legacy_v2", V2VisionEngine),
    ],
)
def test_engine_selection(selection, expected_type):
    settings = Settings(vision_engine=selection, vision_legacy_identity_enabled=False)
    assert isinstance(build_vision_engine(settings), expected_type)


def test_v2_model_contract_and_joint_input():
    values = np.arange(1 * 3 * 64 * 25 * 1, dtype=np.float32).reshape(3, 64, 25, 1)
    assert V2VisionEngine.EXPECTED_MODEL["num_class"] == 5
    assert V2VisionEngine.EXPECTED_BONE_MODALITY is False
    assert V2VisionEngine.OUTPUT_CLASSES == 5
    assert FALL_CLASS_ID == 1
    assert V2VisionEngine._model_input(values, SimpleNamespace()) is values


def test_v2_checkpoint_strict_load_and_forward_contract():
    root = Path(__file__).resolve().parents[2] / "src" / "vision"
    config_path = root / "work_dir" / "fall_detection" / "joint" / "config.yaml"
    checkpoint_path = root / "work_dir" / "fall_detection" / "joint" / "runs-best_val.pt"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    model_args = dict(config["model_args"])
    model_args["graph"] = "src.vision.graph.ntu_rgb_d_hierarchy.Graph"
    model = Model(**model_args)
    weights = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    weights = OrderedDict((key.split("module.")[-1], value) for key, value in weights.items())
    model.load_state_dict(weights, strict=True)
    model.eval()

    model_input = torch.zeros((1, 3, 64, 25, 1), dtype=torch.float32)
    with torch.inference_mode():
        output = model(model_input)
    assert tuple(output.shape) == (1, 5)


@pytest.mark.parametrize("predicted_class", [0, 2, 3, 4])
def test_v2_non_fall_classes_collapse_to_non_fall(tmp_path, predicted_class):
    engine = make_v2_engine(tmp_path, predicted_class)
    session = VisionSession("cam-v2")
    result = None
    for frame_id in range(1, 128):
        result = engine.process(packet("cam-v2", frame_id, source_timestamp=frame_id / 30), session)

    assert result is not None
    assert result.metadata["raw_class_id"] == predicted_class
    assert result.metadata["model_version"] == "v2"
    assert session.state.get("legacy_pending_fall", False) is False
    assert result.events == []


def test_v2_class_one_enters_existing_temporal_fall_state(tmp_path):
    engine = make_v2_engine(tmp_path, FALL_CLASS_ID)
    session = VisionSession("cam-v2")
    result = None
    for frame_id in range(1, 128):
        result = engine.process(packet("cam-v2", frame_id, source_timestamp=frame_id / 30), session)

    assert result is not None
    assert result.metadata["raw_class_id"] == FALL_CLASS_ID
    assert result.metadata["pending_fall"] is True
    assert result.events == []

    confirmed = engine.process(packet("cam-v2", 128, source_timestamp=6.3), session)
    assert [event.type for event in confirmed.events] == ["fall_confirmed"]
