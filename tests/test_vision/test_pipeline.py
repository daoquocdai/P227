import inspect
import re
from types import SimpleNamespace
from typing import ClassVar

import cv2
import numpy as np
import pytest
import torch

from src.models.frame import FramePacket
from src.vision.pipeline import CanonicalVisionPipeline, VisionInitializationError
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

    def __init__(self, _path, task=None, verbose=False):
        self.verbose = verbose
        self.task = task
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
        logits = torch.zeros((1, 5), dtype=torch.float32)
        logits[0, predicted] = 4.0
        return logits


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

    def interp1d(old_axis, values, axis, kind, fill_value):
        assert axis == 0 and kind == "linear" and fill_value == "extrapolate"

        def interpolate(new_axis):
            return np.stack([np.interp(new_axis, old_axis, values[:, column]) for column in range(values.shape[1])], axis=1)

        return interpolate

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
        interp1d=interp1d,
    )


def make_engine(tmp_path, *, classes=None, clock=None, invalid_shape=None, preprocessing_calls=None):
    FakeYolo.instances.clear()
    FakePose.instances.clear()
    fake_clock = clock or FakeClock()
    engine = CanonicalVisionPipeline(
        yolo_path=tmp_path / "yolo.pt",
        config_path=tmp_path / "config.yaml",
        checkpoint_path=tmp_path / "checkpoint.pt",
        identity_enabled=False,
        clock=fake_clock,
        incident_factory=iter(["incident-1", "incident-2", "incident-3"]).__next__,
    )
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
        if isinstance(engine._clock, FakeClock):
            engine._clock.value = frame_id / 30.0
        results.append(engine.process(packet(session.camera_id, frame_id), session))
    return results


def test_adapter_has_no_capture_ui_async_or_event_sink_ownership():
    source = inspect.getsource(CanonicalVisionPipeline)
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

    assert first.state["vision_frame_count"] == 2
    assert second.state["vision_frame_count"] == 1
    assert len(first.state["vision_kpts_buffer"]) == 1
    assert len(second.state["vision_kpts_buffer"]) == 1
    assert engine._contexts["cam01"].yolo is not engine._contexts["cam02"].yolo
    assert engine._contexts["cam01"].pose is not engine._contexts["cam02"].pose


def test_shared_initialization_runs_once_for_two_cameras(tmp_path):
    engine = CanonicalVisionPipeline(tmp_path / "y", tmp_path / "c", tmp_path / "w")
    calls = []

    def initialize():
        calls.append(True)
        engine._dependencies = make_dependencies()
        engine._device = torch.device("cpu")
        engine._action_model = FakeActionModel()

    engine._initialize_shared = initialize
    engine.start()
    engine.process(packet("cam01", 1), VisionSession("cam01"))
    engine.process(packet("cam02", 1), VisionSession("cam02"))

    assert len(calls) == 1
    assert engine._action_model is not None


def test_time_window_is_resampled_to_64_joint_frames(tmp_path):
    preprocessing_calls = []
    engine, _ = make_engine(tmp_path, classes=[0], preprocessing_calls=preprocessing_calls)
    session = VisionSession("cam01")

    results = process_range(engine, session, 1, 127)
    model_results = [result for result in results if result.metadata["raw_class"] is not None]
    model_result = model_results[-1]

    assert len(engine._action_model.calls) == 3
    assert tuple(engine._action_model.calls[0].shape) == (1, 3, 64, 25, 1)
    assert [name for name, _shape in preprocessing_calls] == [
        "clean", "dynamic", "pose", "interpolate", "kalman",
    ] * 3
    assert all(shape == (64, 25, 3) for _name, shape in preprocessing_calls)
    assert model_result.metadata["window_source_time_span"] >= 2.0
    assert model_result.metadata["model_window_index"] == 3
    assert model_result.metadata["raw_class"] == 0
    assert len(session.state["vision_kpts_buffer"]) <= 32
    assert np.shares_memory(engine._action_model.calls[0].numpy(), engine._action_model.calls[1].numpy()) is False


def test_five_class_logits_shape_is_validated(tmp_path):
    engine, _ = make_engine(tmp_path, invalid_shape=(1, 120))
    session = VisionSession("cam01")

    with pytest.raises(RuntimeError, match=r"must return shape \(1, 5\)"):
        process_range(engine, session, 1, 127)


def test_normal_prediction_has_no_event(tmp_path):
    engine, _ = make_engine(tmp_path, classes=[0])
    results = process_range(engine, VisionSession("cam01"), 1, 127)
    result = next(result for result in reversed(results) if result.metadata["raw_class"] is not None)

    assert result.metadata["raw_class"] == 0
    assert result.metadata["fall_state"] == "waiting"
    assert result.events == []


def test_pending_resets_on_later_normal_window(tmp_path):
    engine, clock = make_engine(tmp_path, classes=[1, 0])
    session = VisionSession("cam01")
    process_range(engine, session, 1, 127)
    assert session.state["vision_fall_state"] == "pending"

    clock.value = 0.5
    process_range(engine, session, 128, 191)

    assert session.state["vision_fall_state"] == "normal"
    assert session.state.get("vision_incident_id") is None


def test_pending_resets_on_movement(tmp_path):
    engine, _ = make_engine(tmp_path, classes=[1])
    session = VisionSession("cam01")
    process_range(engine, session, 1, 127)
    engine._contexts["cam01"].pose.keypoints = np.full((25, 3), 0.8, dtype=np.float32)

    engine.process(packet("cam01", 128), session)
    engine.process(packet("cam01", 129), session)

    assert session.state["vision_fall_state"] == "normal"
    assert session.state.get("vision_incident_id") is None


def test_confirmation_emits_exactly_one_stable_event_then_new_episode_after_recovery(tmp_path):
    engine, _ = make_engine(tmp_path, classes=[1, 1])
    session = VisionSession("cam01")
    pending = process_range(engine, session, 1, 127)[-1]
    assert pending.metadata["fall_state"] == "pending"
    assert pending.events == []
    assert session.state.get("vision_incident_id") is None

    skipped = engine.process(packet("cam01", 128, source_timestamp=6.3), session)
    confirmed = engine.process(packet("cam01", 129, source_timestamp=6.4), session)
    repeated = engine.process(packet("cam01", 130, source_timestamp=6.5), session)
    repeated = engine.process(packet("cam01", 131, source_timestamp=6.6), session)

    assert skipped.events == []
    assert len(confirmed.events) == 1
    event = confirmed.events[0]
    assert event.type == "fall_confirmed"
    assert event.metadata["incident_id"] == "incident-1"
    assert event.metadata["event_id"] == "incident-1:fall_confirmed"
    assert repeated.events == []

    engine._contexts["cam01"].pose.keypoints = np.full((25, 3), 0.8, dtype=np.float32)
    engine.process(packet("cam01", 132, source_timestamp=6.7), session)
    engine.process(packet("cam01", 133, source_timestamp=6.8), session)
    assert session.state.get("vision_incident_id") is None

    engine._action_model.classes = [1] * 10
    second_events = []
    for frame_id in range(134, 301):
        engine._clock.value = 8.0 + (frame_id - 134) / 30.0
        result = engine.process(
            packet(
                "cam01",
                frame_id,
                source_timestamp=(frame_id - 134) / 30.0,
                source_epoch=1,
                discontinuity=frame_id == 134,
            ),
            session,
        )
        second_events.extend(result.events)
    assert [event.metadata["incident_id"] for event in second_events] == ["incident-2"]


def test_fall_transition_depends_on_source_time_not_processing_clock(tmp_path):
    clock = FakeClock()
    engine, _ = make_engine(tmp_path, classes=[1], clock=clock)
    session = VisionSession("cam")
    process_range(engine, session, 1, 127)
    clock.value = 50_000.0
    skipped = engine.process(packet("cam", 128, source_timestamp=6.3), session)
    clock.value = -50_000.0
    confirmed = engine.process(packet("cam", 129, source_timestamp=6.4), session)
    assert skipped.events == []
    assert [event.type for event in confirmed.events] == ["fall_confirmed"]


def test_source_discontinuity_resets_only_continuity_dependent_state(tmp_path):
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
    assert reset.metadata["buffer_length"] == 0
    assert session.state["vision_frame_count"] == 128
    assert "vision_context_token" in session.state
    assert session.state.get("vision_incident_id") is None


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
    assert np.count_nonzero(session.state["vision_kpts_buffer"][-1]) == 0


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


def test_unknown_identity_is_structured_metadata_not_an_extra_ai_event(tmp_path, monkeypatch):
    engine, _ = make_engine(tmp_path)
    engine.identity_enabled = True
    monkeypatch.setattr(
        engine,
        "_identity_metadata",
        lambda _crop, _track_id, _state, _source_timestamp, _frame_id: {
            "identity_status": "UNKNOWN",
            "identity_name": None,
            "identity_person_id": None,
            "identity_similarity": 0.1,
        },
    )
    session = VisionSession("cam01")

    first = engine.process(packet("cam01", 1, source_timestamp=0.0), session)
    engine.process(packet("cam01", 2, source_timestamp=0.5), session)
    suppressed = engine.process(packet("cam01", 3, source_timestamp=1.0), session)
    engine.process(packet("cam01", 4, source_timestamp=30.5), session)
    repeated = engine.process(packet("cam01", 5, source_timestamp=31.0), session)

    assert first.events == []
    assert suppressed.events == []
    assert repeated.events == []


@pytest.mark.parametrize("missing_name", ["yolo.pt", "config.yaml", "checkpoint.pt"])
def test_missing_required_resource_fails_during_startup(tmp_path, missing_name):
    paths = {}
    for name in ("yolo.pt", "config.yaml", "checkpoint.pt"):
        path = tmp_path / name
        if name != missing_name:
            path.write_bytes(b"placeholder")
        paths[name] = path
    engine = CanonicalVisionPipeline(paths["yolo.pt"], paths["config.yaml"], paths["checkpoint.pt"])
    with pytest.raises(VisionInitializationError, match=re.escape(str(paths[missing_name].resolve()))):
        engine.start()
    with pytest.raises(VisionInitializationError, match=re.escape(str(paths[missing_name].resolve()))):
        engine.start()


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


def test_release_camera_closes_only_requested_context(tmp_path):
    engine, _ = make_engine(tmp_path)
    engine.process(packet("cam01", 1), VisionSession("cam01"))
    engine.process(packet("cam02", 1), VisionSession("cam02"))
    released_pose = engine._contexts["cam01"].pose
    retained_pose = engine._contexts["cam02"].pose

    engine.release_camera("cam01")

    assert released_pose.closed is True
    assert retained_pose.closed is False
    assert set(engine._contexts) == {"cam02"}


def test_source_discontinuity_preserves_identity_control_plane_and_resets_retry_state():
    state = {
        "vision_source_epoch": 4,
        "vision_identity_enabled": True,
        "vision_identity_generation": 9,
        "vision_face_cache": {7: {"status": "PENDING"}},
        "vision_pending_decisions": [{"is_fall": True}],
    }
    next_packet = packet("cam01", 1, source_timestamp=0.0)
    next_packet.source_epoch = 5
    next_packet.discontinuity = True

    CanonicalVisionPipeline._prepare_source_epoch(state, next_packet)

    assert state["vision_identity_enabled"] is True
    assert state["vision_identity_generation"] == 9
    assert state["vision_source_epoch"] == 5
    assert "vision_face_cache" not in state
    assert "vision_pending_decisions" not in state

