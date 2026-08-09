# Chạy nhanh GuardianCam bằng Docker

## 1. Chuẩn bị

Cài Docker Desktop và bảo đảm Docker Desktop đang chạy. Không cần cài Python,
Node.js, CUDA hoặc các thư viện Vision trên máy đích.

Tạo file cấu hình từ mẫu. Giá trị mặc định đã được đặt cho Vision thực tế chạy
CPU-only:

```cmd
copy .env.example .env
```

PowerShell hoặc Linux/macOS có thể dùng `Copy-Item .env.example .env` hoặc
`cp .env.example .env`. Chỉ điền `OPENAI_API_KEY` nếu cần tính năng trợ lý.
Không chia sẻ hoặc commit API key.

## 2. Khởi động

Mở CMD hoặc PowerShell tại thư mục dự án:

```cmd
docker compose up --build --detach
```

Lần build đầu tiên có thể lâu vì image phải tải PyTorch CPU và các thư viện
Vision. Kiểm tra trạng thái:

```cmd
docker compose ps
docker compose logs --follow --tail=200
```

Khi hai service đã chạy, mở:

- Giao diện: <http://localhost:5173>
- API documentation: <http://localhost:8000/docs>
- Health check: <http://localhost:8000/health>

## 3. Các lệnh thường dùng

```cmd
docker compose stop
docker compose start
docker compose restart
docker compose down
```

Build lại sau khi mã nguồn hoặc dependencies thay đổi:

```cmd
docker compose up --build --detach
```

Xem riêng log backend:

```cmd
docker compose logs --follow --tail=200 backend
```

Nếu máy có GNU Make, có thể dùng các lệnh tương đương:

```cmd
make docker-up
make docker-ps
make docker-logs
make docker-down
```

## 4. Dữ liệu và camera

- SQLite và Chroma được lưu trong `data/`.
- Ảnh cảnh báo được lưu trong `snapshots/`.
- Model InsightFace được giữ trong Docker volume `insightface_models`.
- Video mẫu trong `frontend/public/` được mount read-only cho backend.
- Camera RTSP và video file có thể chạy trong container.
- Webcam USB theo index như `0` thường không được Docker Desktop trên Windows
  truyền trực tiếp vào Linux container. Camera này có thể báo offline dù video
  mẫu và camera mạng vẫn hoạt động.

Lệnh `docker compose down` không xóa database, snapshots hoặc model volume.
Không dùng `docker compose down --volumes` nếu muốn giữ model đã tải.

## 5. Xử lý lỗi nhanh

Nếu port `8000` hoặc `5173` đang được sử dụng, đóng tiến trình cũ hoặc đặt port
khác trước khi chạy:

```cmd
set APP_PORT=8080
set FRONTEND_PORT=5174
docker compose up --build --detach
```

Khi đó giao diện ở `http://localhost:5174` và API ở
`http://localhost:8080/docs`.

Nếu frontend chưa tải được API, kiểm tra backend trước:

```cmd
docker compose ps
docker compose logs --tail=200 backend
```
