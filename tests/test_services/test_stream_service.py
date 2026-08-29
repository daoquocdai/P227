from types import SimpleNamespace

import numpy as np
import pytest

from src.services.stream_service import StreamService
from src.api.camera_stream import stream_camera


@pytest.mark.asyncio
async def test_mjpeg_async_encodes_raw_frame_without_calling_vision_renderer(monkeypatch):
    frame = np.full((4, 5, 3), 17, dtype=np.uint8)
    packet = SimpleNamespace(frame_id=1, frame=frame)

    class Hub:
        def wait_for_next(self, *_args):
            return packet

    class VisionMustNotRun:
        def latest_result(self, _camera_id):
            raise AssertionError("Vision must not participate in media streaming")

    service = StreamService(Hub(), vision=VisionMustNotRun())
    encoded_frames = []

    def encode(candidate):
        encoded_frames.append(candidate)
        return b"raw-jpeg"

    monkeypatch.setattr(service, "_encode_jpeg", encode)

    async def connected():
        return False

    stream = service.mjpeg_async(
        "cam",
        connected,
        show_boxes=False,
        show_identity=False,
        show_fall=False,
    )
    chunk = await anext(stream)
    await stream.aclose()

    assert len(encoded_frames) == 1 and encoded_frames[0] is frame
    assert b"raw-jpeg" in chunk


def test_legacy_stream_presentation_query_is_ignored(monkeypatch):
    calls = []

    class RawStream:
        def mjpeg_async(self, *args, **kwargs):
            calls.append((args, kwargs))

            async def body():
                if False:
                    yield b""

            return body()

    runtime = SimpleNamespace(
        camera=SimpleNamespace(get_status=lambda _camera_id: {"status": "online"}),
        frame_hub=SimpleNamespace(has_camera=lambda _camera_id: True),
        stream=RawStream(),
    )
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(local_runtime=runtime)),
        is_disconnected=lambda: False,
    )
    monkeypatch.setattr("src.api.camera_stream.camera_service.public_id", lambda camera_id: camera_id)

    response = stream_camera("cam", request, boxes=False, identity=False)

    assert response.media_type == "multipart/x-mixed-replace; boundary=frame"
    assert len(calls) == 1
    assert calls[0][1] == {}
