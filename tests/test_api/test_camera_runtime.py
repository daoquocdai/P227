import time

import cv2
import numpy as np
import pytest
from starlette.requests import Request

from src.api.camera_stream import stream_camera
from src.database import database_connection
from src.main import app
from src.models.frame import FramePacket

CAMERA_ID = "00000000-0000-0000-0000-000000000000"


class FakeCapture:
    def __init__(self):
        self.released = False

    def isOpened(self):  # noqa: N802 - mirrors OpenCV's API
        return True

    def read(self):
        time.sleep(0.005)
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def get(self, prop):
        return 25.0 if prop == cv2.CAP_PROP_FPS else 0.0

    def set(self, prop, value):
        return True

    def release(self):
        self.released = True


async def wait_online(client, camera_id: str):
    for _ in range(100):
        response = await client.get(f"/api/v1/cameras/{camera_id}")
        if response.json()["status"] == "online":
            return response.json()
        await __import__("asyncio").sleep(0.01)
    raise AssertionError("camera did not become online")


@pytest.mark.asyncio
async def test_camera_lifecycle_is_independent_from_vision(client, monkeypatch):
    runtime = app.state.local_runtime
    capture = FakeCapture()
    monkeypatch.setattr(runtime.camera, "_open_capture", lambda source: capture)

    started = await client.post(f"/api/v1/cameras/{CAMERA_ID}/start")
    assert started.status_code == 202
    with database_connection() as connection:
        assert connection.execute("SELECT is_active FROM cameras WHERE id = ?", (CAMERA_ID,)).fetchone()[0] == 1
    camera = await wait_online(client, CAMERA_ID)
    assert camera["stream_ready"] is True
    assert runtime.vision.get_status(CAMERA_ID)["status"] == "disabled"

    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "app": app})
    response = stream_camera(CAMERA_ID, request)
    assert response.media_type == "multipart/x-mixed-replace; boundary=frame"

    stopped = await client.post(f"/api/v1/cameras/{CAMERA_ID}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "offline"
    assert not runtime.frame_hub.has_camera(CAMERA_ID)
    with database_connection() as connection:
        assert connection.execute("SELECT is_active FROM cameras WHERE id = ?", (CAMERA_ID,)).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_latest_preview_is_single_jpeg_and_missing_is_404(client):
    runtime = app.state.local_runtime
    missing = await client.get(f"/api/v1/cameras/{CAMERA_ID}/preview")
    assert missing.status_code == 404

    runtime.frame_hub.publish(
        FramePacket(
            camera_id=CAMERA_ID,
            frame_id=42,
            captured_at=time.time(),
            frame=np.full((16, 16, 3), 127, dtype=np.uint8),
        )
    )
    preview = await client.get(f"/api/v1/cameras/{CAMERA_ID}/preview")
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/jpeg"
    assert preview.headers["cache-control"] == "no-store"
    assert preview.headers["x-frame-id"] == "42"
    assert preview.content.startswith(b"\xff\xd8")


@pytest.mark.asyncio
async def test_vision_desired_state_is_persisted(client):
    enabled = await client.post(f"/api/v1/cameras/{CAMERA_ID}/vision/enable")
    assert enabled.status_code == 200
    with database_connection() as connection:
        assert connection.execute("SELECT vision_enabled FROM cameras WHERE id = ?", (CAMERA_ID,)).fetchone()[0] == 1

    disabled = await client.post(f"/api/v1/cameras/{CAMERA_ID}/vision/disable")
    assert disabled.status_code == 200
    with database_connection() as connection:
        assert connection.execute("SELECT vision_enabled FROM cameras WHERE id = ?", (CAMERA_ID,)).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_missing_camera_lifecycle_and_stream_return_404(client):
    assert (await client.post("/api/v1/cameras/does-not-exist/start")).status_code == 404
    assert (await client.get("/api/v1/cameras/does-not-exist/stream")).status_code == 404


@pytest.mark.asyncio
async def test_stream_before_start_returns_conflict(client):
    response = await client.get(f"/api/v1/cameras/{CAMERA_ID}/stream")
    assert response.status_code == 409
