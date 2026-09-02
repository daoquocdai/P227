from __future__ import annotations

from src.agents.state import AgentState


def evaluate_triage_severity(
    incident_type: str,
    ai_confidence: float = 0.0,
    posture: str = "unknown",
    immobility_duration_ms: int = 0,
    occurrence_count: int = 1,
    location: str = "chưa xác định",
    is_known_person: bool = False,
) -> dict[str, str]:
    """Phân loại mức độ sự cố theo dữ liệu thực tế: LOW, MEDIUM, HIGH, CRITICAL."""

    # 1. Sự cố té ngã (Fall)
    if incident_type in ("fall", "FALL_DETECTED"):
        if (posture == "lying" and immobility_duration_ms > 3000) or (posture == "unknown" and ai_confidence == 0.0):
            threat = "CRITICAL"
            verdict = "CONFIRMED_ALERT"
            action = "REQUIRE_HITL"
            reason = f"Phát hiện sự cố ngã tại {location}. Mức độ NGUY CẤP. Đang chờ xác nhận."


        elif posture == "lying" or ai_confidence >= 0.85:
            threat = "HIGH"
            verdict = "CONFIRMED_ALERT"
            action = "REQUIRE_HITL"
            reason = f"Phát hiện té ngã mức độ CAO tại {location}: Tư thế {posture} (Độ tin cậy AI: {ai_confidence:.2f})."
        elif posture in ("sitting", "transitioning") or ai_confidence >= 0.6:
            threat = "MEDIUM"
            verdict = "CONFIRMED_ALERT"
            action = "TRIGGER_ALERT"
            reason = f"Nghi ngờ té ngã mức độ TRUNG BÌNH tại {location}: Tư thế {posture} (Độ tin cậy AI: {ai_confidence:.2f})."
        else:
            threat = "LOW"
            verdict = "UNCERTAIN"
            action = "LOG_ONLY"
            reason = f"Cảnh báo ngã mức độ THẤP tại {location}: AI confidence thấp ({ai_confidence:.2f}), cần theo dõi thêm."

    # 2. Phát hiện người lạ (Unknown Person)
    elif incident_type in ("unknown_person", "UNKNOWN_PERSON"):
        if is_known_person:
            threat = "LOW"
            verdict = "DUPLICATE"
            action = "LOG_ONLY"
            reason = f"Đã xác nhận danh tính người thân tại {location}. Không cần cảnh báo."
        elif occurrence_count >= 5:
            threat = "HIGH"
            verdict = "CONFIRMED_ALERT"
            action = "REQUIRE_HITL"
            reason = f"Phát hiện người lạ xuất hiện liên tục ({occurrence_count} lần) tại {location}."
        elif occurrence_count >= 2:
            threat = "MEDIUM"
            verdict = "CONFIRMED_ALERT"
            action = "TRIGGER_ALERT"
            reason = f"Phát hiện người lạ lặp lại ({occurrence_count} lần) tại {location}."
        else:
            threat = "WARNING"
            verdict = "CONFIRMED_ALERT"
            action = "TRIGGER_ALERT"
            reason = f"Có người lạ xuất hiện tại {location}. Đề nghị kiểm tra."

    # 3. Mặc định
    else:
        threat = "UNKNOWN"
        verdict = "UNCERTAIN"
        action = "WAIT"
        reason = "Chưa rõ sự kiện, tiếp tục theo dõi."

    return {
        "threat_level": threat,
        "severity": threat.lower() if threat != "UNKNOWN" else "low",
        "verdict": verdict,
        "action": action,
        "reasoning": reason,
    }



async def reasoning_node(state: AgentState) -> dict:
    """Node suy luận và phân loại mức độ sự cố cho LangGraph / Alert Agent."""
    incident_type = state.get("event") or state.get("incident_type") or "unknown"
    location = state.get("location") or "chưa xác định"
    ai_confidence = float(state.get("metadata", {}).get("ai_confidence", 0.0) or 0.0)
    posture = str(state.get("metadata", {}).get("posture", "unknown"))
    immobility_duration_ms = int(state.get("metadata", {}).get("immobility_duration_ms", 0) or 0)
    occurrence_count = int(state.get("metadata", {}).get("occurrence_count", 1) or 1)

    result = evaluate_triage_severity(
        incident_type=incident_type,
        ai_confidence=ai_confidence,
        posture=posture,
        immobility_duration_ms=immobility_duration_ms,
        occurrence_count=occurrence_count,
        location=location,
    )
    return result

