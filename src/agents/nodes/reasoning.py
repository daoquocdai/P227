from src.agents.state import AgentState

async def reasoning_node(state: AgentState) -> dict:
    """Đọc dữ liệu từ state và đưa ra quyết định an ninh."""
    event_type = state.get("event")
    location = state.get("location")
    
    # Logic suy luận (Rule-based test luồng trước)
    if event_type == "FALL_DETECTED":
        threat = "CRITICAL"
        action = "REQUIRE_HITL"
        reason = f"Phát hiện sự cố ngã tại {location}. Mức độ Đỏ. Đang chờ xác nhận."
    elif event_type == "UNKNOWN_PERSON":
        threat = "WARNING"
        action = "TRIGGER_ALERT"
        reason = f"Có người lạ xuất hiện tại {location}. Đề nghị kiểm tra."
    else:
        threat = "UNKNOWN"
        action = "WAIT"
        reason = "Chưa rõ sự kiện, tiếp tục theo dõi."
        
    # Trả về output để LangGraph ghi đè vào AgentState
    return {
        "threat_level": threat,
        "action": action,
        "reasoning": reason
    }