# Xử lý lỗi

## `DATABASE_URL` không được hỗ trợ

```text
ValueError: Baseline only supports DATABASE_URL=sqlite:///...
```

Sửa `.env`:

```dotenv
DATABASE_URL=sqlite:///./data/app.db
```

Backend hiện chưa hỗ trợ PostgreSQL dù tài liệu template cũ từng có URL ví dụ.

## PyTorch `+cu121` không tìm thấy

Dùng bộ wheel PyPI tương thích Python 3.11:

```text
torch==2.5.1
torchvision==0.20.1
torchaudio==2.5.1
```

Không thêm `+cu121` khi không cấu hình PyTorch CUDA index riêng. Máy không có NVIDIA dùng CPU build.

## `protobuf` xung đột TensorBoard/MediaPipe

Project dùng `mediapipe==0.10.14` và `tensorboard==2.17.1`; không nâng TensorBoard độc lập lên bản yêu cầu protobuf 6+.

## Thiếu model `.pt`

Checkpoint bị Git ignore. Đặt model theo [vision.md](vision.md). Kiểm tra file tồn tại và checksum trước khi chạy.

## `ModuleNotFoundError`

Đảm bảo dùng đúng virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -e vision\torchlight
.\.venv\Scripts\python.exe -m pip check
```

## Camera không mở được

- Đóng ứng dụng khác đang giữ webcam.
- Thử camera index 0/1.
- Trên Windows thử backend `cv2.CAP_DSHOW`.
- Kiểm tra quyền camera của hệ điều hành.
- Với RTSP, kiểm tra URL nội bộ và firewall nhưng không ghi URL có password vào log.

## Frontend không gọi được backend

- Backend phải chạy port 8000.
- Đặt `VITE_API_MODE=api`.
- Kiểm tra `VITE_API_BASE_URL` và `CORS_ORIGINS`.
- Restart Vite sau khi thay `.env`.

## Test kỳ vọng 2 camera nhưng nhận 0

Database mới chỉ có schema, chưa có dữ liệu demo. Tạo database test từ cả `database/schema.sql` và `database/seed.sql`, hoặc điều chỉnh fixture để tự seed dữ liệu cần thiết.

## Git hiển thị hàng nghìn changes

Không commit `.venv/`, `__pycache__/`, `.env`, model weights, TensorBoard runs hoặc face data. Kiểm tra bằng:

```powershell
git status --short --ignored
```

## Windows báo kiến trúc `AMD64` trên CPU Intel

`AMD64`/`win_amd64` là tên chuẩn x86-64 dùng cho cả Intel và AMD. Đây là wheel đúng nếu Python báo 64-bit.
