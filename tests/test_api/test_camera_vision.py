import asyncio
import time

import cv2
import numpy as np
import pytest
from starlette.requests import Request

from src.api.camera_stream import stream_camera
from src.database import BUILTIN_VIDEO_CAMERA_ID
from src.main import app

CAMERA_ID = BUILTIN_VIDEO_CAMERA_ID


class FakeCapture:
    def isOpened(self):
        return True

    def read(self):
        time.sleep(0.005)
        return True, np.zeros((8, 8, 3), dtype=np.uint8)

    def get(self, prop):
        return 25.0 if prop == cv2.CAP_PROP_FPS else 0.0

    def set(self, prop, value):
        return True

    def release(self):
        pass


async def wait_for_status(client, expected):
    for _ in range(100):
        response = await client.get(f"/api/v1/cameras/{CAMERA_ID}/vision/status")
        if response.json()["status"] == expected:
            return response.json()
        await asyncio.sleep(0.01)
    raise AssertionError(f"Vision did not reach {expected}")


@pytest.mark.asyncio
async def test_vision_api_waiting_running_disable_without_stopping_camera(client, monkeypatch):
    runtime = app.state.local_runtime
    assert (await client.get(f"/api/v1/cameras/{CAMERA_ID}/vision/status")).json()["status"] == "disabled"

    waiting = await client.post(f"/api/v1/cameras/{CAMERA_ID}/vision/enable")
    assert waiting.status_code == 200
    assert waiting.json()["status"] == "waiting_for_source"

    monkeypatch.setattr(runtime.camera, "_open_capture", lambda source: FakeCapture())
    assert (await client.post(f"/api/v1/cameras/{CAMERA_ID}/start")).status_code == 202
    running = await wait_for_status(client, "running")
    assert running["processed_frames"] > 0
    assert running["last_result"]["camera_id"] == CAMERA_ID

    disabled = await client.post(f"/api/v1/cameras/{CAMERA_ID}/vision/disable")
    assert disabled.json()["status"] == "disabled"
    camera = (await client.get(f"/api/v1/cameras/{CAMERA_ID}")).json()
    assert camera["status"] == "online"
    assert camera["stream_ready"] is True
    assert runtime.frame_hub.has_camera(CAMERA_ID)
    request = Request({"type": "http", "method": "GET", "path": "/", "headers": [], "app": app})
    assert stream_camera(CAMERA_ID, request).media_type == "multipart/x-mixed-replace; boundary=frame"


@pytest.mark.asyncio
async def test_vision_api_rejects_unknown_camera(client):
    base = "/api/v1/cameras/does-not-exist/vision"
    assert (await client.post(f"{base}/enable")).status_code == 404
    assert (await client.post(f"{base}/disable")).status_code == 404
    assert (await client.get(f"{base}/status")).status_code == 404
