from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch
import yaml

from src.config import Settings
from src.runtime import build_vision_engine
from src.vision.adapters.mock import MockVisionEngine
from src.vision.model.SDAGCN import Model
from src.vision.pipeline import CanonicalVisionPipeline
from src.vision.session import VisionSession
from tests.test_vision.test_pipeline import FakeActionModel, FakeClock, make_dependencies, packet

FALL_CLASS_ID = CanonicalVisionPipeline.FALL_CLASS_ID


class FiveClassModel(FakeActionModel):
    def __call__(self, tensor):
        self.calls.append(tensor.detach().cpu().clone())
        predicted = self.classes.pop(0) if self.classes else 0
        logits = torch.zeros((1, 5), dtype=torch.float32)
        logits[0, predicted] = 4.0
        return logits


def make_pipeline(tmp_path, predicted_class: int) -> CanonicalVisionPipeline:
    clock = FakeClock()
    engine = CanonicalVisionPipeline(
        tmp_path / "yolo.pt",
        tmp_path / "config.yaml",
        tmp_path / "checkpoint.pt",
        identity_enabled=False,
        clock=clock,
    )
    engine._dependencies = make_dependencies()
    engine._device = torch.device("cpu")
    engine._action_model = FiveClassModel([predicted_class])
    engine._initialized = True
    engine.test_clock = clock
    return engine


@pytest.mark.parametrize(
    ("selection", "expected_type"),
    [
        ("mock", MockVisionEngine),
        ("canonical", CanonicalVisionPipeline),
    ],
)
def test_engine_selection(selection, expected_type):
    settings = Settings(vision_engine=selection, vision_identity_enabled=False)
    assert isinstance(build_vision_engine(settings), expected_type)


def test_canonical_model_contract_and_joint_input():
    values = np.arange(1 * 3 * 64 * 25 * 1, dtype=np.float32).reshape(3, 64, 25, 1)
    assert CanonicalVisionPipeline.EXPECTED_MODEL["num_class"] == 5
    assert CanonicalVisionPipeline.EXPECTED_BONE_MODALITY is False
    assert CanonicalVisionPipeline.OUTPUT_CLASSES == 5
    assert FALL_CLASS_ID == 1
    assert CanonicalVisionPipeline._model_input(values, SimpleNamespace()) is values


def test_canonical_checkpoint_strict_load_and_forward_contract():
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
def test_non_fall_classes_do_not_create_fall_event(tmp_path, predicted_class):
    engine = make_pipeline(tmp_path, predicted_class)
    session = VisionSession("cam-v2")
    results = []
    for frame_id in range(1, 128):
        engine.test_clock.value = frame_id / 30
        results.append(engine.process(packet("cam-v2", frame_id, source_timestamp=frame_id / 30), session))

    observed = next(item for item in results if item.metadata["raw_class"] is not None)
    assert observed.metadata["raw_class"] == predicted_class
    assert session.state.get("vision_pending_fall", False) is False
    assert all(not result.events for result in results)


def test_class_one_enters_temporal_fall_state(tmp_path):
    engine = make_pipeline(tmp_path, FALL_CLASS_ID)
    session = VisionSession("cam-v2")
    results = []
    for frame_id in range(1, 128):
        engine.test_clock.value = frame_id / 30
        results.append(engine.process(packet("cam-v2", frame_id, source_timestamp=frame_id / 30), session))

    observed = next(item for item in results if item.metadata["raw_class"] is not None)
    assert observed.metadata["raw_class"] == FALL_CLASS_ID
    assert session.state["vision_pending_fall"] is True
    assert all(not result.events for result in results)

    engine.process(packet("cam-v2", 128, source_timestamp=6.3), session)
    confirmed = engine.process(packet("cam-v2", 129, source_timestamp=6.4), session)
    assert [event.type for event in confirmed.events] == ["fall_confirmed"]
