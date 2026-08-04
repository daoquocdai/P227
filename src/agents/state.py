from __future__ import annotations

from typing import TypedDict


class AgentState(TypedDict, total=False):
    """State schema cho LangGraph Security Agent.

    Mỗi node đọc và ghi vào state này.
    total=False cho phép tất cả fields là optional.
    """
    # --- INPUT (Event đã xử lý từ Local Hub / API truyền vào) ---
    event: str          # VD: "FALL_DETECTED"
    location: str       # VD: "Phòng khách"
    time: str           # VD: "2026-08-01 22:30:00"

    # --- OUTPUT (Kết quả do Reasoning Node suy luận ra) ---
    threat_level: str   # VD: "CRITICAL", "WARNING"
    action: str         # VD: "REQUIRE_HITL"
    reasoning: str      # VD: "Ngã ở phòng khách, cần xác nhận gấp"

    # --- INTERNAL STATE (Dùng nội bộ nếu cần log lỗi hoặc tool) ---
    error: str
    metadata: dict
