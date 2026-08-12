import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.alerts import router as alerts_router
from src.api.camera_stream import router as camera_stream_router
from src.api.cameras import router as cameras_router
from src.api.history import router as history_router
from src.api.overview import router as overview_router
from src.api.persons import router as persons_router
from src.api.routes import router as api_router
from src.api.settings import router as settings_router
from src.api.vision import router as vision_router
from src.config import get_settings
from src.database import initialize_database
from src.runtime import LocalRuntime
from src.services.event_service import vision_event_sink
from src.services.face_identity_service import face_gallery
from src.services.vision_event_dispatcher import ThreadsafeVisionEventDispatcher


import subprocess

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    initialize_database()
    face_gallery.reload()
    vision_event_sink.start()
    consumer = asyncio.create_task(vision_event_sink.consume(), name="vision-event-consumer")
    dispatcher = ThreadsafeVisionEventDispatcher(vision_event_sink)
    dispatcher.start(asyncio.get_running_loop())
    mock_event_frame_ids = {
        int(value.strip())
        for value in settings.mock_vision_event_frame_ids.split(",")
        if value.strip()
    }
    runtime = LocalRuntime(event_dispatcher=dispatcher, mock_event_frame_ids=mock_event_frame_ids)
    app.state.local_runtime = runtime
    app.state.vision_event_dispatcher = dispatcher
    runtime.start()
    runtime.restore_persisted_state()
    
    import sys
    print("Starting GuardianCam AI (realtime.py) automatically...")
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../SDA-GCN"))
    realtime_process = subprocess.Popen([sys.executable, "realtime.py"], cwd=base_dir)
    
    try:
        yield
    finally:
        print("Stopping GuardianCam AI...")
        realtime_process.terminate()
        try:
            realtime_process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            realtime_process.kill()
            
        runtime.stop()
        dispatcher.stop()
        consumer.cancel()
        with suppress(asyncio.CancelledError):
            await consumer
        vision_event_sink.stop()


app = FastAPI(
    title="GuardianCam Local Hub",
    description="Local Vision event ingestion, HITL and dashboard API",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SNAPSHOT_DIR = "snapshots"
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
app.mount("/snapshots", StaticFiles(directory=SNAPSHOT_DIR), name="snapshots")

app.include_router(api_router, prefix="/api/v1")
app.include_router(alerts_router, prefix="/api/v1")
app.include_router(cameras_router, prefix="/api/v1")
app.include_router(camera_stream_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1")
app.include_router(overview_router, prefix="/api/v1")
app.include_router(persons_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(vision_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}
