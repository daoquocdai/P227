# Cài đặt, vận hành và troubleshooting

Xem [QUICKSTART.md](../QUICKSTART.md) nếu chỉ cần luồng chạy ngắn nhất.

## 1. Dependency profiles

Yêu cầu Python 3.11 64-bit và Node.js 20+.

```cmd
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

Chọn một profile:

```cmd
python -m pip install -r requirements/vision-intel.txt
python -m pip install -r requirements/vision-cuda.txt
python -m pip install -r requirements/vision-cpu.txt
```

Sau khi chọn đúng một profile:

```cmd
python -m pip install --no-deps -r requirements/vision-identity.txt
```

Không cài nhiều profile trong cùng `.venv`. Nếu cài nhầm, xóa toàn bộ `.venv`
và tạo lại theo [Quickstart](../QUICKSTART.md); không uninstall riêng từng biến
thể ONNX Runtime/OpenCV vì chúng dùng chung module Python.

`requirements/base.txt` chỉ dành cho backend/test không chạy Real Vision.

Frontend:

```cmd
cd frontend
npm.cmd ci
cd ..
copy /Y .env.example .env
```

## 2. Cấu hình canonical production

```dotenv
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8000
CORS_ORIGINS=http://localhost:5173
DATABASE_URL=sqlite:///./data/app.db

VISION_ENGINE=canonical
VISION_DEVICE=auto
VISION_YOLO_PATH=yolov8n.pt
VISION_CONFIG_PATH=work_dir/fall_detection/joint/config.yaml
VISION_CHECKPOINT_PATH=work_dir/fall_detection/joint/runs-best_val.pt
VISION_MODEL_CACHE_DIR=data/vision-cache

VISION_IDENTITY_ENABLED=false
VISION_IDENTITY_PROVIDER=auto
VISION_INSIGHTFACE_ROOT=~/.insightface
```

Path Vision tương đối được resolve từ `src/vision`. Không thêm
`VISION_KNOWN_FACES_DIR`; production known-person data lấy từ SQLite.

Các setting temporal target-rate/buffer còn tồn tại trong config để tương thích
cũ nhưng canonical production không đọc chúng. Scheduling thực tế là even
source-frame eligibility + latest slot capacity 1.

## 3. Model assets

Fall pipeline cần:

```text
src/vision/yolov8n.pt
src/vision/work_dir/fall_detection/joint/config.yaml
src/vision/work_dir/fall_detection/joint/runs-best_val.pt
```

Identity cần:

```text
<VISION_INSIGHTFACE_ROOT>/models/buffalo_l/
```

Giữ Identity OFF nếu bộ model chưa tồn tại. Fall không phụ thuộc InsightFace.
Không sửa model graph, weights, preprocessing, window, class mapping hoặc
threshold để né lỗi artifact.

## 4. Device selection

`VISION_DEVICE=auto`:

1. NVIDIA CUDA;
2. Intel OpenVINO GPU;
3. CPU fallback.

Trong Intel profile:

- YOLO: OpenVINO Intel GPU;
- SDA-GCN: OpenVINO Intel GPU;
- MediaPipe Pose: CPU;
- InsightFace: DirectML nếu khả dụng, CPU fallback;
- one-shot privacy detector: CPU provider để tránh DirectML native crash.

Luôn kiểm tra startup/status logs để biết provider thực tế.

## 5. Khởi động

Backend:

```cmd
.venv\Scripts\python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

Frontend:

```cmd
cd frontend
npm.cmd run dev
```

Sau startup:

```cmd
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/status
curl http://127.0.0.1:8000/api/v1/cameras
```

Backend tự restore desired Camera/Vision/Identity state. Camera source lỗi được
cô lập và không làm FastAPI startup fail.

## 6. Runtime status

```text
GET /api/v1/cameras/{id}/runtime/status
GET /api/v1/cameras/{id}/vision/status
```

Camera status phản ánh capture health. Vision status độc lập:

- `disabled`;
- `waiting_for_source`;
- `running`;
- `error`.

Realtime Vision metrics quan trọng:

- `vision_frames_seen`;
- `vision_frames_eligible`;
- `vision_frames_offered`;
- `vision_frames_overwritten`;
- `vision_frames_processed`;
- `pending`/`max_pending`;
- `vision_drop_ratio`;
- `vision_fps`;
- `vision_result_staleness`.

`max_pending` phải không vượt 1.

## 7. Controls

- Vision ON: Fall Detection luôn ON.
- `Hiện khung`: presentation-only, không restart runtime/model.
- `Phát hiện người lạ`: camera-level Identity inference setting; thay đổi ảnh
  hưởng mọi viewer của camera đó.
- Identity OFF không ảnh hưởng Fall hoặc one-shot privacy detection cho Fall
  snapshot.

## 8. Runtime data và backup

```text
data/app.db
snapshots/
```

Backup sau khi dừng backend:

```cmd
if not exist backup mkdir backup
copy data\app.db backup\app-backup.db
xcopy snapshots backup\snapshots\ /E /I
```

Không xóa alerts/events/snapshots trong quá trình troubleshooting nếu chưa có
backup và yêu cầu rõ ràng.

## 9. Troubleshooting

### Frontend đồng loạt `ECONNREFUSED`

Nếu `/alerts`, `/cameras`, `/overview` cùng lỗi, backend không listen:

```cmd
curl http://127.0.0.1:8000/health
netstat -ano | findstr :8000
```

### Port 8000 bị giữ

```cmd
netstat -ano | findstr :8000
tasklist /FI "PID eq <PID>"
```

Xác định đúng process trước khi dừng. Không chạy hai backend cùng ghi một DB.

### Camera đen

Kiểm tra lần lượt:

1. camera `status=online`;
2. `stream_ready=true`;
3. `/preview` trả `200 image/jpeg` và `X-Frame-Id` tăng;
4. MJPEG trả `multipart/x-mixed-replace`;
5. source file/index/RTSP hợp lệ;
6. không có process khác giữ webcam.

Raw preview không phụ thuộc Vision. Nếu preview cũng đen/lỗi, đừng debug model
trước capture/source.

### Vision lỗi hoặc chậm

Đọc `current_error`, device diagnostics và realtime metrics. Latest-slot drop là
expected khi Vision chậm hơn capture; raw stream phải tiếp tục và memory không
tăng theo thời gian.

Không tăng queue, đổi window hoặc tune threshold để che throughput.

### Identity không bật

Kiểm tra:

- `buffalo_l` tồn tại dưới configured root;
- ONNX Runtime provider có trong log;
- camera Vision đang enabled;
- persisted camera Identity state;
- FaceGallery có active face profiles.

### Có event nhưng không có snapshot

Đây có thể là privacy fail-closed đúng thiết kế. Snapshot bị omit nếu không tìm
được face/head ROI an toàn. Event, alert và SSE vẫn phải tồn tại.

### SQLite integrity

```cmd
python -c "import sqlite3; c=sqlite3.connect('data/app.db'); print(c.execute('PRAGMA integrity_check').fetchone()[0])"
```

Kết quả mong đợi là `ok`.

## 10. Docker

Docker Compose dùng CPU profile và phù hợp với file/RTSP hơn webcam index trên
Windows:

```cmd
docker compose up --build --detach
docker compose logs --follow --tail=200
docker compose down
```
