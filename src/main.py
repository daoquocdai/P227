import asyncio
import os
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.agents.alert_orchestrator import AlertAgentOrchestrator
from src.agents.qa_agent import SecurityQAAgent
from src.agents.summary_agent import IncidentSummaryAgent
from src.api.agent import router as agent_router
from src.api.alerts import router as alerts_router
from src.api.auth import router as auth_router
from src.api.camera_stream import router as camera_stream_router
from src.api.cameras import router as cameras_router
from src.api.history import router as history_router
from src.api.overview import router as overview_router
from src.api.persons import router as persons_router
from src.api.routes import router as api_router
from src.api.settings import router as settings_router
from src.api.statistics import router as statistics_router
from src.api.vision import router as vision_router
from src.config import get_settings
from src.database import initialize_database
from src.runtime import LocalRuntime
from src.services.event_service import event_service, vision_event_sink
from src.services.operational_metrics_collector import OperationalMetricsCollector
from src.services.vision_event_dispatcher import ThreadsafeVisionEventDispatcher


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    initialize_database()
    alert_agent = AlertAgentOrchestrator(settings)
    alert_agent.start()
    event_service.set_agent_enqueue(alert_agent.enqueue)
    app.state.alert_agent = alert_agent
    app.state.qa_agent = SecurityQAAgent(api_key=settings.openai_api_key, model=settings.alert_agent_model)
    app.state.summary_agent = IncidentSummaryAgent(api_key=settings.openai_api_key)
    vision_event_sink.start()
    consumer = asyncio.create_task(vision_event_sink.consume(), name="vision-event-consumer")
    dispatcher = ThreadsafeVisionEventDispatcher(vision_event_sink)
    dispatcher.start(asyncio.get_running_loop())
    runtime = LocalRuntime(event_dispatcher=dispatcher)
    app.state.local_runtime = runtime
    app.state.vision_event_dispatcher = dispatcher
    runtime.start()
    runtime.restore_persisted_state()
    metrics_collector = OperationalMetricsCollector(
        runtime,
        interval_seconds=settings.metrics_collection_interval_seconds,
        retention_days=settings.metrics_retention_days,
    )
    if settings.metrics_collection_enabled:
        metrics_collector.start()
    app.state.metrics_collector = metrics_collector
    try:
        yield
    finally:
        event_service.set_agent_enqueue(None)
        await alert_agent.stop()
        metrics_collector.stop()
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
app.include_router(agent_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")

app.include_router(alerts_router, prefix="/api/v1")
app.include_router(cameras_router, prefix="/api/v1")
app.include_router(camera_stream_router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1")
app.include_router(overview_router, prefix="/api/v1")
app.include_router(persons_router, prefix="/api/v1")
app.include_router(settings_router, prefix="/api/v1")
app.include_router(statistics_router, prefix="/api/v1")
app.include_router(vision_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}
