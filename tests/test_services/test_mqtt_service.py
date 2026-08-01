import json
import pytest
from unittest.mock import Mock
from src.services.mqtt_service import add_new_alert, process_mqtt_message, ALERTS_DB

@pytest.fixture(autouse=True)
def reset_db():
    ALERTS_DB.clear()

def test_add_new_alert():
    """Kiểm tra hàm khởi tạo record cảnh báo."""
    alert = add_new_alert("INTRUDER", "Phát hiện người lạ", "snapshot.jpg")
    
    assert alert["id"] == 1
    assert alert["event_type"] == "INTRUDER"
    assert "snapshots/snapshot.jpg" in alert["snapshot_url"]
    assert alert["feedback"] is None
    assert len(ALERTS_DB) == 1

def test_process_mqtt_message_valid_json():
    """Kiểm tra hàm bóc tách dữ liệu JSON từ MQTT."""
    mock_msg = Mock()
    payload = {
        "event_type": "FALL_DETECTED",
        "description": "Ngã tại phòng bếp",
        "snapshot_filename": "bep.jpg"
    }
    mock_msg.payload = json.dumps(payload).encode('utf-8')
    
    process_mqtt_message(None, None, mock_msg)
    
    assert len(ALERTS_DB) == 1
    assert ALERTS_DB[0]["event_type"] == "FALL_DETECTED"
    assert ALERTS_DB[0]["description"] == "Ngã tại phòng bếp"

def test_process_mqtt_message_invalid_json():
    """Kiểm tra bộ bắt lỗi Exception khi MQTT gửi payload sai định dạng."""
    mock_msg = Mock()
    mock_msg.payload = b"Invalid Format Data"
    
    # Đảm bảo hàm không văng lỗi sập chương trình nhờ khối try-except
    process_mqtt_message(None, None, mock_msg)
    assert len(ALERTS_DB) == 0