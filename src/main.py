from contextlib import asynccontextmanager
import os
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

from src.api.routes import router as api_router
from src.api.alerts import router as alerts_router
from src.config import get_settings
from src.services.mqtt_service import process_mqtt_message

# Khởi tạo MQTT Client chạy ngầm
mqtt_client = mqtt.Client(CallbackAPIVersion.VERSION2)

# Định nghĩa hàm on_connect
def on_mqtt_connect(client, userdata, flags, rc, properties=None):
    print(f"[MQTT] Đã kết nối Broker, mã: {rc}")
    client.subscribe("guardiancam/events")

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    print(f"Starting {settings.app_name} in {settings.app_env} mode")
    
    mqtt_client.on_connect = on_mqtt_connect
    mqtt_client.on_message = process_mqtt_message
    
    try:
        mqtt_client.connect(settings.mqtt_host, settings.mqtt_port, 60)
        mqtt_client.loop_start()
        print("[MQTT] Đã khởi động MQTT background listener thành công.")
    except Exception as e:
        print(f"[MQTT Warning] Không thể kết nối MQTT Broker: {e}")
        
    yield
    
    # --- Dọn dẹp khi tắt ứng dụng ---
    print("Shutting down...")
    mqtt_client.loop_stop()
    mqtt_client.disconnect()


app = FastAPI(
    title="AI20K Agent & GuardianCam",
    description="AI Agent built with LangGraph & On-device Security Hub",
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

# Gắn thư mục snapshots cục bộ để Front-End hiển thị ảnh cảnh báo
SNAPSHOT_DIR = "snapshots"
os.makedirs(SNAPSHOT_DIR, exist_ok=True)
app.mount("/snapshots", StaticFiles(directory=SNAPSHOT_DIR), name="snapshots")

# Đăng ký các router (giữ nguyên router cũ của bạn + gắn thêm alerts_router)
app.include_router(api_router, prefix="/api/v1")
app.include_router(alerts_router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}