import json
import time
from datetime import datetime
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

# Cấu hình kết nối tới MQTT Broker đang chạy trên Docker
MQTT_HOST = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "guardiancam/events"

def on_connect(client, userdata, flags, reason_code, properties=None):
    if reason_code == 0:
        print("[Mock YOLO] 🟢 Kết nối thành công tới MQTT Broker!")
    else:
        print(f"[Mock YOLO] 🔴 Kết nối thất bại, mã lỗi: {reason_code}")

def main():
    # Khởi tạo MQTT Client (Phiên bản v2)
    client = mqtt.Client(CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect

    try:
        client.connect(MQTT_HOST, MQTT_PORT, 60)
        client.loop_start()
        time.sleep(1) # Đợi 1 giây để kết nối ổn định

        # Gói tin giả lập sự kiện ngã
        payload = {
            "event_type": "FALL_DETECTED",
            "camera_location": "Phòng khách",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "confidence": 0.95,
            "snapshot_filename": "room_fall_test.jpg"
        }

        # Bắn gói tin lên MQTT
        client.publish(MQTT_TOPIC, json.dumps(payload))
        print(f"🚀 Đã bắn sự kiện lên topic '{MQTT_TOPIC}':")
        print(json.dumps(payload, indent=2, ensure_ascii=False))

        time.sleep(1)
        client.loop_stop()
        client.disconnect()
        print("[Mock YOLO] Đã ngắt kết nối an toàn.")

    except Exception as e:
        print(f"[Mock YOLO Error] Lỗi: {e}")

if __name__ == "__main__":
    main()