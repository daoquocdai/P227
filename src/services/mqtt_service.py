import json
import os
from datetime import datetime
from src.config import get_settings

settings = get_settings()

# Biến tạm lưu danh sách cảnh báo trong RAM (hoặc thay bằng DB trong src/models/)
ALERTS_DB = []

# Đảm bảo thư mục lưu snapshot tồn tại ở thư mục gốc
SNAPSHOT_DIR = "snapshots"
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

def add_new_alert(event_type: str, description: str, filename: str):
    new_id = len(ALERTS_DB) + 1
    alert_item = {
        "id": new_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event_type": event_type,  # "FALL_DETECTION" hoặc "INTRUDER"
        "description": description,  # Mô tả tiếng Việt (VD: "Phát hiện người lạ lúc 2h sáng")
        "snapshot_url": f"{settings.api_base_url}/snapshots/{filename}",
        "feedback": None
    }
    ALERTS_DB.append(alert_item)
    return alert_item

def process_mqtt_message(client, userdata, msg):
    try:
        payload = json.loads(msg.payload.decode('utf-8'))
        event_type = payload.get("event_type")
        description = payload.get("description")
        filename = payload.get("snapshot_filename")
        
        print(f"[MQTT] Nhận sự kiện từ AI Edge: {description}")
        add_new_alert(event_type, description, filename)
    except Exception as e:
        print(f"[MQTT Error] Lỗi xử lý message: {e}")