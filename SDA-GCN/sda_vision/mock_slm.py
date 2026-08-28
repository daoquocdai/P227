from typing import Dict, Any, List
from .contracts import VisionFrameResult, VisionDetection
from .slm_mapper import map_identity_to_role

def simulate_slm_response(frame_result: VisionFrameResult, role_map: Dict[str, str] = None) -> List[Dict[str, Any]]:
    """
    Mock LLM: Hàm này giả lập suy luận của mô hình AI (SLM) bằng các quy tắc logic cứng (If-Else).
    Đầu ra là danh sách các Object JSON chứa level, need_alert, và message (Câu tiếng Việt).
    Sử dụng hàm này để test UI và quy trình lưu DB khi chưa train được mô hình Qwen.
    """
    responses = []
    
    # Trích xuất thời gian HH:MM
    try:
        time_str = frame_result.captured_wall_time.split('T')[1][:5] if 'T' in frame_result.captured_wall_time else "00:00"
    except Exception:
        time_str = "00:00"
        
    camera = frame_result.camera_id
    
    # Kiểm tra xem có người nhà trong khung hình không
    has_family = False
    if role_map:
        for d in frame_result.detections:
            if d.label == "person" and d.identity_name in role_map:
                has_family = True
                break
    family_present = "Có" if has_family else "Không"
    
    action_dict = {
        "Dung": "đứng",
        "Cui": "cúi người",
        "Ngoi": "ngồi",
        "Nam": "nằm",
        "Phat hien nga (0.85) - Kiem tra...": "có dấu hiệu mất thăng bằng",
        "Co the nga (Cho...)": "có thể ngã",
        "Nga!": "bị ngã"
    }

    for det in frame_result.detections:
        if det.label != "person":
            continue
            
        role_str = map_identity_to_role(det, role_map)
        action = frame_result.current_action or "Dung"
        yolo = det.yolo_interaction or "Không có"
        iou = det.iou_score or 0.0
        pos = det.last_position or "Giữa khung hình"
        track = det.tracking_status or "Đang trong khung hình"
        
        action_vn = action_dict.get(action, action.lower())
        r_name = role_str.split('(')[-1].strip(')') if "Người lạ" not in role_str else "Người lạ"
        
        level = "normal"
        need_alert = False
        msg = ""

        # 1. Trạng thái biến mất (Rời khỏi khung hình)
        if track == "Đã biến mất":
            level = "normal"
            need_alert = False
            msg = f"Ghi nhận: {r_name} đã di chuyển ra khỏi tầm nhìn ở {camera.lower()} hướng {pos.lower()} lúc {time_str}."
        
        # 2. Xử lý hành động Ngã (Ưu tiên cao nhất)
        elif "Nga!" in action:
            level = "critical"
            need_alert = True
            if iou < 0.2 or yolo == "Không có":
                msg = f"BÁO ĐỘNG KHẨN CẤP: Xác nhận {r_name} bị ngã gục ra sàn nhà tại {camera.lower()} lúc {time_str}! Yêu cầu kiểm tra ngay!"
            else:
                msg = f"BÁO ĐỘNG KHẨN CẤP: Xác nhận {r_name} bị ngã va đập mạnh vào {yolo.lower()} tại {camera.lower()} lúc {time_str}! Yêu cầu kiểm tra ngay lập tức!"
                
        elif "Phat hien nga" in action or "Co the nga" in action:
            level = "warning"
            need_alert = True
            msg = f"Cảnh báo: Có dấu hiệu {r_name} {action_vn} tại {camera.lower()} lúc {time_str}. Hệ thống đang theo dõi thêm..."

        # 3. Xử lý người lạ xâm nhập
        elif "Người lạ" in role_str:
            if family_present == "Có":
                level = "normal"
                need_alert = False
                msg = f"Ghi nhận: Khách đến nhà chơi đang {action_vn} tại {camera.lower()} lúc {time_str}, đi cùng người nhà nên an toàn."
            else:
                level = "danger"
                need_alert = True
                msg = f"BÁO ĐỘNG AN NINH: Xâm nhập trái phép! Phát hiện một người lạ mặt xuất hiện tại {camera.lower()} lúc {time_str}."

        # 4. Trạng thái sinh hoạt bình thường của người nhà
        else:
            level = "normal"
            need_alert = False
            if yolo != "Không có" and iou >= 0.4:
                if action in ["Ngoi", "Nam"]:
                    msg = f"Ghi nhận an toàn: {r_name} đang {action_vn} trên {yolo.lower()} tại {camera.lower()} lúc {time_str}."
                else:
                    msg = f"Ghi nhận an toàn: {r_name} đang {action_vn} gần {yolo.lower()} tại {camera.lower()} lúc {time_str}."
            else:
                msg = f"Ghi nhận an toàn: {r_name} đang {action_vn} tại {camera.lower()} lúc {time_str}."
                
        responses.append({
            "level": level,
            "need_alert": need_alert,
            "message": msg
        })
        
    return responses
