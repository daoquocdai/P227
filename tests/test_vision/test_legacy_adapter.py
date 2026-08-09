import inspect
import re
from types import SimpleNamespace
from typing import ClassVar

import cv2
import numpy as np
import pytest
import torch

from src.models.frame import FramePacket
from src.vision.adapters.legacy import (
    LegacyVisionEngine,
    LegacyVisionInitializationError,
)
from src.vision.session import VisionSession


class FakeTensorField:
    def __init__(self, values):
        self._values = torch.tensor(values, dtype=torch.float32)

    def cpu(self):
        return self

    def numpy(self):
        return self._values.numpy()

    def __getitem__(self, index):
        return self._values[index]


class FakeBoxes:
    def __init__(self, present=True):
        boxes = [[100, 100, 400, 700]] if present else []
        self.xyxy = FakeTensorField(boxes)
        self.conf = FakeTensorField([0.91] if present else [])
        self.id = FakeTensorField([7] if present else [])

    def __len__(self):
        return len(self.xyxy._values)


class FakeYolo:
    instances: ClassVar[list] = []

    def __init__(self, _path, verbose=False):
        self.verbose = verbose
        self.track_calls = 0
        self.device = None
        self.person_present = True
        self.__class__.instances.append(self)

    def to(self, device):
        self.device = device
        return self

    def track(self, _frame, *, persist, classes, verbose):
        assert persist is True
        assert classes == 0
        assert verbose is False
        self.track_calls += 1
        return [SimpleNamespace(boxes=FakeBoxes(self.person_present))]


class FakePose:
    instances: ClassVar[list] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.keypoints = np.full((25, 3), 0.1, dtype=np.float32)
        self.raise_error = False
        self.__class__.instances.append(self)

    def close(self):
        self.closed = True


class FakeActionModel:
    def __init__(self, classes=None, invalid_shape=None):
        self.classes = list(classes or [0])
        self.invalid_shape = invalid_shape
        self.calls = []

    def __call__(self, tensor):
        self.calls.append(tensor.detach().cpu().clone())
        if self.invalid_shape is not None:
            return torch.zeros(self.invalid_shape, dtype=torch.float32)
        predicted = self.classes.pop(0) if self.classes else 0
        return torch.tensor([[0.0, 4.0] if predicted == 1 else [4.0, 0.0]], dtype=torch.float32)


class FakeClock:
    def __init__(self, value=0.0):
        self.value = value

    def __call__(self):
        return self.value


def identity(value):
    return value.astype(np.float32, copy=True)


def make_dependencies(preprocessing_calls=None):
    calls = preprocessing_calls if preprocessing_calls is not None else []

    def record(name):
        def transform(value):
            calls.append((name, value.shape))
            return identity(value)

        return transform

    def extract(_crop, pose, *_coordinates):
        if pose.raise_error:
            raise RuntimeError("pose failed")
        return pose.keypoints.copy()

    pose_namespace = SimpleNamespace(Pose=FakePose)
    return SimpleNamespace(
        cv2=cv2,
        torch=torch,
        YOLO=FakeYolo,
        mp=SimpleNamespace(solutions=SimpleNamespace(pose=pose_namespace)),
        extract_from_crop=extract,
        clean_out_of_bounds_data=record("clean"),
        normalize_skeleton_dynamic=record("dynamic"),
        normalize_pose=record("pose"),
        interpolate_missing=record("interpolate"),
        apply_kalman_filter=record("kalman"),
        ntu_pairs=((0, 1), (20, 20)),
    )


def make_engine(tmp_path, *, classes=None, clock=None, invalid_shape=None, preprocessing_calls=None):
    FakeYolo.instances.clear()
    FakePose.instances.clear()
    fake_clock = clock or FakeClock()
    engine = LegacyVisionEngine(
        yolo_path=tmp_path / "yolo.pt",
        config_path=tmp_path / "config.yaml",
        checkpoint_path=tmp_path / "checkpoint.pt",
        identity_enabled=False,
        clock=fake_clock,
        incident_factory=iter(["incident-1", "incident-2", "incident-3"]).__next__,
    )
    engine.start()
    engine._dependencies = make_dependencies(preprocessing_calls)
    engine._device = torch.device("cpu")
    engine._action_model = FakeActionModel(classes, invalid_shape)
    engine._initialized = True
    return engine, fake_clock


def packet(camera_id, frame_id, *, source_timestamp=None, source_epoch=0, discontinuity=False):
    return FramePacket(
        camera_id=camera_id,
        frame_id=frame_id,
        captured_at=frame_id / 30.0,
        frame=np.zeros((48, 64, 3), dtype=np.uint8),
        source_timestamp=source_timestamp,
        source_epoch=source_epoch,
        discontinuity=discontinuity,
    )


def process_range(engine, session, start, end):
    results = []
    for frame_id in range(start, end + 1):
        results.append(engine.process(packet(session.camera_id, frame_id), session))
    return results


def test_adapter_has_no_capture_ui_async_or_event_sink_ownership():
    source = inspect.getsource(LegacyVisionEngine)
    for forbidden in ("VideoCapture", "imshow", "waitKey", "destroyAllWindows", "asyncio", "VisionEventSink"):
        assert forbidden not in source


def test_skipped_packet_returns_result_without_initializing_or_running_yolo(tmp_path):
    engine, _ = make_engine(tmp_path)
    session = VisionSession("cam01")
    first = engine.process(packet("cam01", 1), session)
    second = engine.process(packet("cam01", 2), session)

    assert first.metadata["sampled"] is True
    assert second.metadata["sampled"] is False
    assert second.frame_id == 2
    assert second.metadata["internal_frame_count"] == 2
    assert FakeYolo.instances[0].track_calls == 1


def test_frame_count_buffer_yolo_and_pose_are_per_camera(tmp_path):
    engine, _ = make_engine(tmp_path)
    first = VisionSession("cam01")
    second = VisionSession("cam02")

    engine.process(packet("cam01", 1), first)
    engine.process(packet("cam02", 1), second)
    engine.process(packet("cam01", 2), first)

    assert first.state["legacy_frame_count"] == 2
    assert second.state["legacy_frame_count"] == 1
    assert len(first.state["legacy_kpts_buffer"]) == 1
    assert len(second.state["legacy_kpts_buffer"]) == 1
    assert engine._contexts["cam01"].yolo is not engine._contexts["cam02"].yolo
    assert engine._contexts["cam01"].pose is not engine._contexts["cam02"].pose


def test_shared_initialization_runs_once_for_two_cameras(tmp_path):
    engine = LegacyVisionEngine(tmp_path / "y", tmp_path / "c", tmp_path / "w")
    engine.start()
    calls = []

    def initialize():
        calls.append(True)
        engine._dependencies = make_dependencies()
        engine._device = torch.device("cpu")
        engine._action_model = FakeActionModel()

    engine._initialize_shared = initialize
    engine.process(packet("cam01", 1), VisionSession("cam01"))
    engine.process(packet("cam02", 1), VisionSession("cam02"))

    assert len(calls) == 1
    assert engine._action_model is not None


def test_window_64_preprocessing_order_stride_and_bone_shape(tmp_path):
    preprocessing_calls = []
    engine, _ = make_engine(tmp_path, classes=[0], preprocessing_calls=preprocessing_calls)
    session = VisionSession("cam01")

    results = process_range(engine, session, 1, 127)
    model_result = results[-1]

    assert len(engine._action_model.calls) == 1
    assert tuple(engine._action_model.calls[0].shape) == (1, 3, 64, 25, 1)
    assert [name for name, _shape in preprocessing_calls] == ["clean", "dynamic", "pose", "interpolate", "kalman"]
    assert all(shape == (64, 25, 3) for _name, shape in preprocessing_calls)
    assert model_result.metadata["window_frame_ids"] == list(range(1, 128, 2))
    assert model_result.metadata["model_window_index"] == 1
    assert model_result.metadata["raw_class"] == 0
    assert len(session.state["legacy_kpts_buffer"]) == 32
    assert list(session.state["legacy_sampled_frame_ids"]) == list(range(65, 128, 2))


def test_binary_logits_shape_is_validated(tmp_path):
    engine, _ = make_engine(tmp_path, invalid_shape=(1, 120))
    session = VisionSession("cam01")

    with pytest.raises(RuntimeError, match=r"must return shape \(1, 2\)"):
        process_range(engine, session, 1, 127)


def test_normal_prediction_has_no_event(tmp_path):
    engine, _ = make_engine(tmp_path, classes=[0])
    result = process_range(engine, VisionSession("cam01"), 1, 127)[-1]

    assert result.metadata["raw_class"] == 0
    assert result.metadata["fall_state"] == "normal"
    assert result.events == []


def test_pending_resets_on_later_normal_window(tmp_path):
    engine, clock = make_engine(tmp_path, classes=[1, 0])
    session = VisionSession("cam01")
    process_range(engine, session, 1, 127)
    assert session.state["legacy_fall_state"] == "pending"

    clock.value = 0.5
    process_range(engine, session, 128, 191)

    assert session.state["legacy_fall_state"] == "normal"
    assert session.state["legacy_incident_id"] is None


def test_pending_resets_on_movement(tmp_path):
    engine, _ = make_engine(tmp_path, classes=[1])
    session = VisionSession("cam01")
    process_range(engine, session, 1, 127)
    engine._contexts["cam01"].pose.keypoints = np.full((25, 3), 0.8, dtype=np.float32)

    engine.process(packet("cam01", 128), session)
    engine.process(packet("cam01", 129), session)

    assert session.state["legacy_fall_state"] == "normal"
    assert session.state["legacy_incident_id"] is None


def test_confirmation_emits_exactly_one_stable_event_then_new_episode_after_recovery(tmp_path):
    engine, _ = make_engine(tmp_path, classes=[1, 1])
    session = VisionSession("cam01")
    pending = process_range(engine, session, 1, 127)[-1]
    assert pending.metadata["fall_state"] == "pending"
    assert pending.events == []
    assert session.state["legacy_incident_id"] == "incident-1"

    skipped = engine.process(packet("cam01", 128, source_timestamp=6.3), session)
    engine.process(packet("cam01", 129), session)
    repeated = engine.process(packet("cam01", 130), session)
    repeated = engine.process(packet("cam01", 131), session)

    assert len(skipped.events) == 1
    event = skipped.events[0]
    assert event.type == "fall_confirmed"
    assert event.metadata["incident_id"] == "incident-1"
    assert event.metadata["event_id"] == "incident-1:fall_confirmed"
    assert repeated.events == []

    engine._contexts["cam01"].pose.keypoints = np.full((25, 3), 0.8, dtype=np.float32)
    engine.process(packet("cam01", 132), session)
    engine.process(packet("cam01", 133), session)
    assert session.state.get("legacy_incident_id") is None

    process_range(engine, session, 134, 191)
    assert session.state["legacy_incident_id"] == "incident-2"


def test_fall_transition_depends_on_source_time_not_processing_clock(tmp_path):
    transitions = []
    for processing_clock in (FakeClock(), FakeClock()):
        processing_clock.value = 0.0 if not transitions else 10_000.0
        engine, _ = make_engine(tmp_path, classes=[1], clock=processing_clock)
        session = VisionSession(f"cam-{len(transitions)}")
        pending = process_range(engine, session, 1, 127)[-1]
        processing_clock.value += 50_000.0
        before = engine.process(packet(session.camera_id, 128, source_timestamp=6.0), session)
        confirmed = engine.process(packet(session.camera_id, 129, source_timestamp=6.3), session)
        transitions.append(
            (
                pending.metadata["fall_state"],
                before.metadata["fall_state"],
                confirmed.metadata["fall_state"],
                [event.type for event in confirmed.events],
            )
        )

    assert transitions == [
        ("pending", "pending", "confirmed", ["fall_confirmed"]),
        ("pending", "pending", "confirmed", ["fall_confirmed"]),
    ]


def test_source_discontinuity_clears_window_and_pending_incident(tmp_path):
    engine, _ = make_engine(tmp_path, classes=[1])
    session = VisionSession("cam01")
    pending = process_range(engine, session, 1, 127)[-1]
    assert pending.metadata["fall_state"] == "pending"

    reset = engine.process(
        packet("cam01", 128, source_timestamp=0.0, source_epoch=1, discontinuity=True),
        session,
    )

    assert reset.events == []
    assert reset.metadata["source_epoch"] == 1
    assert reset.metadata["source_discontinuity"] is True
    assert reset.metadata["fall_state"] == "waiting"
    assert reset.metadata["buffer_length"] == 1
    assert session.state.get("legacy_incident_id") is None


def test_no_person_resets_pending_and_has_no_detection(tmp_path):
    engine, _ = make_engine(tmp_path, classes=[1])
    session = VisionSession("cam01")
    process_range(engine, session, 1, 127)
    engine._contexts["cam01"].yolo.person_present = False

    engine.process(packet("cam01", 128), session)
    result = engine.process(packet("cam01", 129), session)

    assert result.detections == []
    assert result.metadata["fall_state"] == "normal"


def test_pose_missing_appends_zero_without_treating_person_as_missing(tmp_path):
    engine, _ = make_engine(tmp_path)
    session = VisionSession("cam01")
    engine.process(packet("cam01", 1), session)
    engine._contexts["cam01"].pose.keypoints = np.zeros((25, 3), dtype=np.float32)
    engine.process(packet("cam01", 2), session)
    result = engine.process(packet("cam01", 3), session)

    assert len(result.detections) == 1
    assert result.metadata["pose_found"] is False
    assert np.count_nonzero(session.state["legacy_kpts_buffer"][-1]) == 0


def test_pose_exception_is_controlled_and_other_camera_context_remains_usable(tmp_path):
    engine, _ = make_engine(tmp_path)
    first = VisionSession("cam01")
    second = VisionSession("cam02")
    engine.process(packet("cam01", 1), first)
    engine._contexts["cam01"].pose.raise_error = True
    engine.process(packet("cam01", 2), first)

    with pytest.raises(RuntimeError, match="pose failed"):
        engine.process(packet("cam01", 3), first)
    result = engine.process(packet("cam02", 1), second)
    assert result.camera_id == "cam02"


def test_identity_disabled_does_not_emit_or_add_identity_metadata(tmp_path):
    engine, _ = make_engine(tmp_path)
    result = engine.process(packet("cam01", 1), VisionSession("cam01"))

    assert result.detections[0].metadata == {}
    assert result.events == []
    assert engine._face_app is None


@pytest.mark.parametrize("missing_name", ["yolo.pt", "config.yaml", "checkpoint.pt"])
def test_missing_required_resource_has_clear_lazy_initialization_error(tmp_path, missing_name):
    paths = {}
    for name in ("yolo.pt", "config.yaml", "checkpoint.pt"):
        path = tmp_path / name
        if name != missing_name:
            path.write_bytes(b"placeholder")
        paths[name] = path
    engine = LegacyVisionEngine(paths["yolo.pt"], paths["config.yaml"], paths["checkpoint.pt"])
    engine.start()
    session = VisionSession("cam01")

    with pytest.raises(LegacyVisionInitializationError, match=re.escape(str(paths[missing_name].resolve()))):
        engine.process(packet("cam01", 1), session)
    with pytest.raises(LegacyVisionInitializationError, match=re.escape(str(paths[missing_name].resolve()))):
        engine.process(packet("cam01", 2), session)


def test_new_session_replaces_and_closes_old_camera_context(tmp_path):
    engine, _ = make_engine(tmp_path)
    engine.process(packet("cam01", 1), VisionSession("cam01"))
    old_pose = engine._contexts["cam01"].pose

    engine.process(packet("cam01", 2), VisionSession("cam01"))

    assert old_pose.closed is True
    assert engine._contexts["cam01"].pose is not old_pose


def test_stop_closes_all_pose_contexts(tmp_path):
    engine, _ = make_engine(tmp_path)
    engine.process(packet("cam01", 1), VisionSession("cam01"))
    engine.process(packet("cam02", 1), VisionSession("cam02"))
    poses = [context.pose for context in engine._contexts.values()]

    engine.stop()

    assert all(pose.closed for pose in poses)
    assert engine._contexts == {}
