def event_description(event_type: str, location: str, identity_name: str | None = None) -> str:
    normalized = event_type.upper()
    if "FALL" in normalized:
        person = identity_name or "một người"
        return f"Phát hiện {person} có dấu hiệu té ngã và chưa đứng dậy tại {location}."
    if "UNKNOWN" in normalized:
        return f"Phát hiện một người chưa có trong danh sách người thân tại {location}."
    if "INACTIVITY" in normalized:
        return f"Không ghi nhận hoạt động trong thời gian dài tại {location}."
    if "RECOGNIZED" in normalized:
        return f"Đã nhận diện {identity_name or 'một người thân'} tại {location}."
    return f"Camera ghi nhận một sự kiện cần kiểm tra tại {location}."
