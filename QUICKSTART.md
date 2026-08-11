# GuardianCam Quickstart — Windows CMD

Hướng dẫn này bắt đầu từ máy Windows chưa có source code và dùng **Command
Prompt (CMD)**. Cách chạy native được ưu tiên vì hỗ trợ webcam USB; Docker phù
hợp hơn với video file và RTSP.

## 1. Chuẩn bị

Cài trước:

- Git
- Python 3.11 64-bit
- Node.js 20 trở lên

Kiểm tra trong CMD:

```cmd
git --version
python --version
node --version
npm.cmd --version
```

## 2. Clone và cài dependency

```cmd
git clone https://github.com/AI20K-Build-Phase-Cohort-3/P-227.git
cd P-227
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements/vision-intel.txt
cd frontend
npm.cmd ci
cd ..
copy /Y .env.example .env
```

Máy NVIDIA CUDA 12.4 dùng profile sau thay cho Intel:

```cmd
python -m pip install -r requirements/vision-cuda.txt
```

CPU/Docker portable dùng `requirements/vision-cpu.txt`. Nếu cần tái tạo đúng
môi trường Windows/Torch CPU cũ đã khóa:

```cmd
python -m pip install -r requirements-lock-cpu.txt
```

## 3. Chọn Vision engine

File `.env.example` mặc định dùng canonical VisionV2:

```dotenv
VISION_ENGINE=canonical
VISION_DEVICE=auto
```

Các lựa chọn hợp lệ:

| Giá trị | Ý nghĩa |
|---|---|
| `mock` | Chạy sản phẩm không cần model; không tự sinh cảnh báo giả |
| `canonical` | Production VisionV2 năm lớp/joint; raw class `1` là fall candidate |

Model canonical đi cùng repository tại `src\vision`. Nếu bật nhận diện
người lạ, InsightFace còn cần bộ `buffalo_l` trong thư mục được trỏ bởi
`VISION_INSIGHTFACE_ROOT`. Có thể chạy smoke không cần model nhận diện
bằng cách đặt:

```dotenv
VISION_IDENTITY_ENABLED=false
```

Muốn xác nhận riêng backend/frontend trước khi chạy AI thật, đặt:

```dotenv
VISION_ENGINE=mock
VISION_IDENTITY_ENABLED=false
```

## 4. Chạy dự án

Mở **hai cửa sổ CMD** tại thư mục `P-227`.

CMD 1 — backend:

```cmd
cd /d <duong-dan-den-P-227>
.venv\Scripts\activate
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

CMD 2 — frontend:

```cmd
cd /d <duong-dan-den-P-227>\frontend
npm.cmd run dev
```

Mở:

- Giao diện: <http://localhost:5173>
- Swagger: <http://127.0.0.1:8000/docs>
- Health check: <http://127.0.0.1:8000/health>

Không đóng CMD backend khi frontend đang chạy. Dừng từng process bằng
`Ctrl+C` và chờ shutdown hoàn tất.

## 5. Kiểm tra sau khi chạy

Trong CMD thứ ba:

```cmd
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/cameras
curl http://127.0.0.1:8000/api/v1/alerts
```

Backend tự khôi phục trạng thái bật/tắt camera và Vision từ SQLite. Không cần
gọi Swagger để bật lại sau mỗi lần restart. Camera page dùng MJPEG live;
Dashboard dùng preview tĩnh gần nhất.

## 6. Chạy bằng Docker (tùy chọn)

Cài Docker Desktop, rồi chạy từ root repository:

```cmd
docker compose config --quiet
docker compose up --build --detach
docker compose ps
docker compose logs --follow --tail=200
```

Docker image hiện tại là CPU-only. SQLite nằm trong `data`, snapshot nằm trong
`snapshots`, còn InsightFace dùng volume `insightface_models`. Webcam theo index
như `0` thường không hoạt động qua Docker Desktop trên Windows; dùng video file
hoặc RTSP, hoặc chạy native như phần trên.

Dừng Docker:

```cmd
docker compose down
```

Không thêm `--volumes` nếu muốn giữ model InsightFace đã tải.

## 7. Lỗi thường gặp

Backend báo `Errno 10048`:

```cmd
netstat -ano | findstr :8000
tasklist /FI "PID eq <PID>"
```

Frontend báo `ECONNREFUSED`: backend chưa chạy tại port 8000. Kiểm tra bằng:

```cmd
curl http://127.0.0.1:8000/health
```

Camera video báo `moov atom not found`: file MP4 bị thiếu, hỏng hoặc chưa ghi
xong; kiểm tra lại đường dẫn và thay bằng file video hợp lệ.

Chi tiết cấu hình và xử lý lỗi nằm tại [docs/setup.md](docs/setup.md).
