from src.agents.tools.security_tool import require_human_validation, send_notification, trigger_siren


def test_trigger_siren():
    """Kiểm tra công cụ bật còi báo động[cite: 5]."""
    result = trigger_siren.invoke({"location": "Phòng khách"})
    assert result == "Đã kích hoạt thành công còi báo động tại Phòng khách."


def test_send_notification():
    """Kiểm tra công cụ gửi tin nhắn cảnh báo[cite: 5]."""
    result = send_notification.invoke({"message": "Test alert", "urgency": "MEDIUM"})
    assert result == "Đã gửi cảnh báo mức MEDIUM tới người dùng."


def test_require_human_validation():
    """Kiểm tra công cụ đẩy sự kiện lên HITL[cite: 5]."""
    result = require_human_validation.invoke({"event_id": "EVT-123", "image_url": "http://img.jpg"})
    assert result == "Đã chuyển trạng thái sự kiện sang Chờ Xác Nhận (HITL)."
