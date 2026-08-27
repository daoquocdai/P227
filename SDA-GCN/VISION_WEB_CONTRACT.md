# Tài liệu Tích hợp SDA-GCN (Dành cho Web/Backend Developer)

Tài liệu này giải thích cấu trúc dữ liệu mà phân hệ AI Vision (`SDA-GCN`) sẽ liên tục trả về cho Backend. Nắm vững cấu trúc này sẽ giúp đội ngũ Backend và Web dễ dàng bóc tách dữ liệu để làm tính năng Lịch trình, Báo động và lưu Database.

## 1. Luồng hoạt động (Data Flow)

Mỗi khi Camera chụp được một khung hình (Frame), hệ thống AI sẽ phân tích qua 4 model:
1. **MediaPipe**: Bóc tách khung xương (Pose).
2. **GCN (Graph Convolutional Network)**: Phân tích khung xương để nhận diện hành động (Ngoi, Dung, Nga).
3. **Face Recognition**: Nhận diện xem người đó là người nhà (Known) hay người lạ (Unknown).
4. **YOLOv8**: Quét các đồ vật nội thất trong nhà (Ghế, Sofa, Giường...). Hàm YOLO chỉ chạy 10 phút/lần để tiết kiệm GPU.

Sau khi chạy xong, toàn bộ kết quả được gom chung vào object **`VisionFrameResult`** và gửi về cho Backend qua một hàm callback.

## 2. Cấu trúc Object `VisionFrameResult`

Đây là object cốt lõi mà Backend sẽ nhận được. Bạn có thể xem chi tiết trong file `sda_vision/contracts.py`.

```python
@dataclass(frozen=True, slots=True)
class VisionFrameResult:
    camera_id: str                          # ID của Camera (VD: 'cam-phong-khach')
    frame_sequence: int                     # Số thứ tự của khung hình
    source_frame_index: int | None          # Chỉ mục của khung hình gốc
    source_epoch: int                       # Epoch của nguồn phát
    source_time_s: float                    # Thời gian của khung hình tính bằng giây
    captured_wall_time: datetime | None     # Thời gian thực tế lúc chụp ảnh
    
    current_action: str                     # Hành động chung (VD: "Nga!", "Ngoi", "Binh thuong")
    fall_state: str                         # Trạng thái té ngã (Nếu có)
    fall_confidence: float | None           # Độ tự tin của thuật toán ngã (0.0 - 1.0)
    
    detections: tuple[VisionDetection, ...] # Danh sách tất cả mọi người xuất hiện trong ảnh (Xem mục 3)
    generated_events: tuple[VisionEvent, ...] # Các sự kiện AI được sinh ra tự động
    stage_metrics: dict[str, float | None]  # Thông số đo lường hiệu năng của từng bước xử lý (ms)
    fall_diagnostics: tuple[dict, ...]      # Thông tin chi tiết chẩn đoán ngã
```

## 3. Cấu trúc Object `VisionDetection` (Chi tiết từng người)

Bên trong mảng `detections` của `VisionFrameResult`, mỗi người sẽ là một object `VisionDetection`. Chú ý đặc biệt đến các trường dữ liệu sau để làm tính năng Lịch trình và Cảnh báo người lạ:

```python
@dataclass
class VisionDetection:
    label: str                       # Luôn là "person"
    bbox: tuple                      # Tọa độ bounding box (x1, y1, x2, y2)
    association_id: str              # ID Tracking độc nhất của người này (Dùng để theo dõi di chuyển)

    # --- Dữ liệu Khuôn mặt (Identity) ---
    identity_status: str             # Trạng thái: "known" (Người nhà) hoặc "unknown" (Người lạ)
    identity_name: str               # Tên người nhà (VD: "Ông Minh"). Nếu là người lạ sẽ là None.
    identity_confidence: float       # Độ tự tin của thuật toán nhận diện khuôn mặt

    # --- Dữ liệu SLM / Không gian (YOLO) ---
    yolo_interaction: str            # Tên đồ vật người này đang tương tác (VD: "Sofa", "Giuong", "Khong co")
    iou_score: float                 # Tỷ lệ đè lấp (Giao nhau) giữa người và đồ vật YOLO (0.0 - 1.0)
    last_position: str               # Vị trí trên khung hình (VD: "Sát mép trái", "Giữa khung hình")
```

## 4. Hướng dẫn ứng dụng cho Web/Backend

Dựa vào dữ liệu trên, Backend có thể làm các logic như sau:

### A. Chức năng Lịch trình sinh hoạt (SLM Mock)
Để không bị lưu log rác (lưu mỗi 15 frame/giây), Backend cần thực hiện **State Tracking** (Lưu lại trạng thái của khung hình trước).
Backend chỉ nên kích hoạt SLM để ghi log vào cơ sở dữ liệu khi:
- **Người mới xuất hiện hoặc biến mất**: Kiểm tra mảng `detections` thay đổi số lượng ID.
- **Tương tác với đồ vật**: Khi `iou_score` của một người với đồ vật tăng vượt ngưỡng `0.4` (bắt đầu dùng đồ) hoặc giảm xuống dưới `0.2` (ngừng dùng).
- **Hành động đặc biệt**: `current_action` chuyển sang trạng thái "Nga!".

### B. Chức năng Cảnh báo người lạ xâm nhập
Backend chỉ cần quét mảng `detections`.
- Lọc ra những người có `identity_status == "unknown"`.
- Nếu trong mảng `detections` **KHÔNG CÓ AI** có `identity_status == "known"` (nghĩa là người lạ vào nhà mà không có người thân đi cùng).
- => Lập tức "bóp cò" báo động đỏ!
