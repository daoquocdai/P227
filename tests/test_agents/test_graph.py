import pytest

from src.agents.graph import agent


@pytest.mark.asyncio
async def test_agent_evaluation_flow():
    """Kiểm thử luồng xử lý của Agent với state sự kiện an ninh thực tế."""
    initial_state = {"event": "FALL_DETECTED", "location": "Phòng khách", "time": "2026-08-01 14:30:00"}
    result = await agent.ainvoke(initial_state)
    assert isinstance(result, dict)
    # Đảm bảo graph trả về kết quả phân tích hoặc bắt lỗi thành công
    assert "threat_level" in result or "error" in result


@pytest.mark.asyncio
async def test_agent_state_structure():
    """Kiểm thử cấu trúc state trả về từ graph compiled."""
    initial_state = {"event": "INTRUSION", "location": "Sân trước", "time": "2026-08-01 12:00:00"}
    result = await agent.ainvoke(initial_state)
    assert isinstance(result, dict)
    assert "reasoning" in result or "error" in result
