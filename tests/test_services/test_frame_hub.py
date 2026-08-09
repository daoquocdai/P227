import numpy as np

from src.models.frame import FramePacket
from src.services.frame_hub import FrameHub


def packet(camera_id: str, frame_id: int) -> FramePacket:
    return FramePacket(camera_id, frame_id, float(frame_id), np.full((2, 2, 3), frame_id, dtype=np.uint8))


def test_latest_frames_are_independent_per_camera():
    hub = FrameHub()
    hub.publish(packet("cam01", 1))
    hub.publish(packet("cam02", 7))
    hub.publish(packet("cam01", 2))

    assert hub.get_latest("cam01").frame_id == 2
    assert hub.get_latest("cam02").frame_id == 7
    assert set(hub.list_camera_ids()) == {"cam01", "cam02"}


def test_remove_only_cleans_requested_camera():
    hub = FrameHub()
    hub.publish(packet("cam01", 1))
    hub.publish(packet("cam02", 1))

    hub.remove("cam01")

    assert hub.get_latest("cam01") is None
    assert hub.get_latest("cam02") is not None
