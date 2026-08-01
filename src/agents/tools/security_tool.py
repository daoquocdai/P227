from langchain_core.tools import tool
import datetime

@tool
def trigger_siren(location: str) -> str:
    """Bật còi báo động vật lý tại vị trí chỉ định.
    
    Chỉ dùng công cụ này khi mức độ đe dọa (threat_level) là CRITICAL (ví dụ: ngã bất động lâu, có trộm đột nhập).
    
    Args:
        location: Vị trí cần bật còi (VD: 'Phòng khách', 'Sân trước')
        
    Returns:
        Trạng thái thực thi lệnh.
    """
    # TODO: Tương lai có thể nhúng code MQTT publish tới phần cứng còi báo động tại đây
    print(f"[🚨 ACTION] Đang kích hoạt còi báo động tại: {location}")
    return f"Đã kích hoạt thành công còi báo động tại {location}."


@tool
def send_notification(message: str, urgency: str = "HIGH") -> str:
    """Gửi tin nhắn cảnh báo tới điện thoại (Dashboard/Telegram) của người dùng.
    
    Dùng để thông báo cho người nhà khi có sự kiện cần chú ý hoặc chờ xác nhận (HITL).
    
    Args:
        message: Nội dung cảnh báo (VD: 'Phát hiện ngã tại phòng khách')
        urgency: Mức độ ('HIGH', 'MEDIUM', 'LOW')
        
    Returns:
        Trạng thái gửi tin nhắn.
    """
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[📱 NOTIFY - {urgency}] {timestamp}: {message}")
    return f"Đã gửi cảnh báo mức {urgency} tới người dùng."


@tool
def require_human_validation(event_id: str, image_url: str) -> str:
    """Đẩy sự kiện lên Dashboard chờ con người xác nhận (Human-in-the-loop).
    
    Dùng khi AI nhận diện sự kiện có độ tin cậy chưa cao hoặc cần quyết định từ người nhà.
    
    Args:
        event_id: Mã sự kiện
        image_url: Link ảnh snapshot bằng chứng
    """
    print(f"[👀 HITL] Đang treo sự kiện {event_id} chờ người dùng xác nhận qua ảnh: {image_url}")
    return "Đã chuyển trạng thái sự kiện sang Chờ Xác Nhận (HITL)."