from typing import Dict, Any
from .contracts import VisionFrameResult, VisionDetection

def map_identity_to_role(det: VisionDetection, role_map: Dict[str, str] = None) -> str:
    """
    Ánh xạ tên nhận diện được thành chuỗi chuẩn cho AI.
    Dữ liệu role_map sẽ được truyền động từ Database Backend.
    """
    if det.identity_status == "UNKNOWN" or not det.identity_name:
        return "Người lạ (UNKNOWN)"
    
    # Nếu là người nhà có đăng ký vai trò
    if role_map and det.identity_name in role_map:
        return f"Người nhà ({role_map[det.identity_name]})"
    
    # Nếu chưa gán vai trò (kể cả có lưu mặt) -> Tính là Người lạ hết
    return "Người lạ (UNKNOWN)"

def generate_slm_prompt(frame_result: VisionFrameResult, role_map: Dict[str, str] = None) -> list[str]:
    """
    Trích xuất và ánh xạ toàn bộ dữ liệu từ 1 frame thành danh sách các Prompt (Text).
    Nếu trong frame có 3 người, hàm sẽ trả về list gồm 3 chuỗi prompt riêng biệt.
    
    Backend có thể duyệt qua list này, nếu thấy Prompt nào có hành động "Nga!" 
    thì mới gọi API của Qwen 0.5B để tiết kiệm chi phí.
    """
    prompts = []
    
    # Trích xuất thời gian HH:MM từ chuỗi wall_time_utc (vd: '2024-05-15T10:30:45Z')
    try:
        time_str = frame_result.captured_wall_time.split('T')[1][:5] if 'T' in frame_result.captured_wall_time else "00:00"
    except Exception:
        time_str = "00:00"
        
    # Kiểm tra xem trong khung hình có bất kỳ Người nhà nào không
    has_family = False
    if role_map:
        for d in frame_result.detections:
            if d.label == "person" and d.identity_name in role_map:
                has_family = True
                break
    
    family_str = "Có" if has_family else "Không"
    
    for det in frame_result.detections:
        # Chỉ xử lý các detection là người
        if det.label != "person":
            continue
            
        role_str = map_identity_to_role(det, role_map)
        action_str = frame_result.current_action or "Dung"
        yolo_str = det.yolo_interaction or "Không có"
        iou_val = det.iou_score or 0.0
        pos_str = det.last_position or "Giữa khung hình"
        track_str = det.tracking_status or "Đang trong khung hình"
        
        prompt_text = f"""Thời gian: {time_str}
Camera: {frame_result.camera_id}
Đối tượng: {role_str}
Người nhà đi cùng: {family_str}
Hành động: {action_str}
Tương tác YOLO: {yolo_str}
Chỉ số IoU: {iou_val:.2f}
Tọa độ cuối: {pos_str}
Trạng thái theo dõi: {track_str}"""
        
        prompts.append(prompt_text)
        
    return prompts
