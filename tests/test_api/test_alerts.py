import pytest
from src.services.mqtt_service import ALERTS_DB, add_new_alert

@pytest.fixture(autouse=True)
def setup_teardown_db():
    """Reset Database tạm trước và sau mỗi bài test để tránh xung đột."""
    ALERTS_DB.clear()
    add_new_alert("FALL_DETECTED", "Test Ngã", "test1.jpg")
    yield
    ALERTS_DB.clear()

@pytest.mark.asyncio
async def test_get_alerts(client):
    """Kiểm tra API lấy danh sách cảnh báo (phải được sắp xếp giảm dần theo ID)."""
    # Thêm sự kiện thứ 2 để test việc sắp xếp reverse
    add_new_alert("INTRUDER", "Test Trộm", "test2.jpg")
    
    response = await client.get("/api/v1/alerts")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    # Đảm bảo phần tử đầu tiên là id 2 (reverse=True)
    assert data[0]["id"] == 2

@pytest.mark.asyncio
async def test_confirm_alert_success(client):
    """Kiểm tra API cập nhật feedback HITL thành công."""
    response = await client.post("/api/v1/alerts/confirm?alert_id=1&feedback=True Positive")
    assert response.status_code == 200
    assert response.json()["message"] == "Đã ghi nhận phản hồi 'True Positive' cho cảnh báo #1"

    # Kiểm tra db cập nhật đúng không
    assert ALERTS_DB[0]["feedback"] == "True Positive"

@pytest.mark.asyncio
async def test_confirm_alert_not_found(client):
    """Kiểm tra mã lỗi 404 khi gửi feedback cho alert_id không tồn tại."""
    response = await client.post("/api/v1/alerts/confirm?alert_id=999&feedback=False")
    assert response.status_code == 404
    assert response.json()["detail"] == "Không tìm thấy cảnh báo"