import pytest

from src.agents.nodes.reasoning import AgentState, reasoning_node


@pytest.mark.asyncio
async def test_reasoning_node_fall_detected():
    """Kiểm tra logic suy luận khi phát hiện ngã."""
    state: AgentState = {"event": "FALL_DETECTED", "location": "Phòng khách"}
    result = await reasoning_node(state)

    assert result["threat_level"] == "CRITICAL"
    assert result["action"] == "REQUIRE_HITL"
    assert "Phát hiện sự cố ngã tại Phòng khách" in result["reasoning"]

@pytest.mark.asyncio
async def test_reasoning_node_unknown_person():
    """Kiểm tra logic suy luận khi phát hiện người lạ."""
    state: AgentState = {"event": "UNKNOWN_PERSON", "location": "Sân trước"}
    result = await reasoning_node(state)

    assert result["threat_level"] == "WARNING"
    assert result["action"] == "TRIGGER_ALERT"
    assert "Có người lạ xuất hiện tại Sân trước" in result["reasoning"]

@pytest.mark.asyncio
async def test_reasoning_node_other_event():
    """Kiểm tra logic suy luận cho các sự kiện không xác định."""
    state: AgentState = {"event": "SOME_RANDOM_EVENT", "location": "Hành lang"}
    result = await reasoning_node(state)

    assert result["threat_level"] == "UNKNOWN"
    assert result["action"] == "WAIT"
    assert result["reasoning"] == "Chưa rõ sự kiện, tiếp tục theo dõi."
