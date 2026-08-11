# Cài đặt, vận hành và troubleshooting

[`QUICKSTART.md`](../QUICKSTART.md) là luồng CMD ngắn nhất từ lúc clone. Tài
liệu này giải thích cấu hình, vận hành và lỗi thường gặp.

## 1. Yêu cầu môi trường

- Python 3.11 64-bit.
- Node.js 20+.
- Windows 10/11 hoặc Linux 64-bit.
- Webcam, video local hoặc RTSP nếu dùng camera thật.
- Model local của canonical VisionV2.

Nên chạy command từ root repository để path database/snapshot/model nhất quán.

## 2. Clone và cài backend

Windows CMD:

```cmd
git clone https://github.com/AI20K-Build-Phase-Cohort-3/P-227.git
cd P-227
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements/vision-intel.txt
```

NVIDIA CUDA 12.4 dùng `requirements/vision-cuda.txt`; portable CPU/Docker dùng
`requirements/vision-cpu.txt`. Chỉ phát triển backend/test chung, không chạy
Real Vision, có thể cài `requirements/base.txt`.

Nếu cần tái tạo đúng CPU environment cũ đã khóa:

```cmd
python -m pip install -r requirements-lock-cpu.txt
```

Kiểm tra:

```cmd
python --version
python -m pip check
```

## 3. Cài frontend

```cmd
cd frontend
npm.cmd ci
cd ..
copy /Y .env.example .env
```

## 4. Cấu hình `.env`

Ví dụ canonical runtime:

```dotenv
APP_ENV=development
APP_HOST=127.0.0.1
APP_PORT=8000
LOG_LEVEL=INFO
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
VISION_INSIGHTFACE_ROOT=C:/Users/<user>/.insightface

VISION_TEMPORAL_TARGET_SAMPLE_RATE=5
VISION_TEMPORAL_BUFFER_CAPACITY=8
```

Lưu ý:

- `VISION_ENGINE=canonical` là production path duy nhất; `mock` chỉ dùng cho test/backend smoke.
- `VISION_DEVICE=auto` ưu tiên native CUDA, sau đó OpenVINO Intel GPU, cuối cùng
  CPU; runtime/device/fallback thực tế đều xuất hiện trong startup log.
- Intel Iris Xe hiện được acceptance ở 5 Hz cho tối đa hai concurrent cameras.
- Identity production lấy gallery từ SQLite và chỉ nên bật sau khi có đủ `buffalo_l`.
- `register face/` không phải production source of truth.
- Không commit `.env`, credential, database, snapshot, face data.
- Path Vision tương đối được resolve từ `src/vision`.

## 5. Model local

Canonical production cần các artifact tương ứng:

```text
src/vision/yolov8n.pt
src/vision/work_dir/fall_detection/joint/config.yaml
src/vision/work_dir/fall_detection/joint/runs-best_val.pt
<VISION_INSIGHTFACE_ROOT>/models/buffalo_l/
```

V2 dùng chung YOLO nhưng thay model action bằng:

```text
src/vision/work_dir/fall_detection/joint/config.yaml
src/vision/work_dir/fall_detection/joint/runs-best_val.pt
```

InsightFace `buffalo_l` chỉ bắt buộc khi identity được bật. Thiếu model identity
không nên được xử lý bằng cách sửa thuật toán; hãy tắt identity hoặc cung cấp
đúng artifact.

Checkpoint SDA-GCN load strict. Thiếu/sai artifact phải sửa artifact/config, không thay model math để né lỗi.

## 6. Khởi động hệ thống

Backend:

```cmd
cd /d <duong-dan-den-P-227>
.venv\Scripts\activate
python -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

Frontend ở terminal khác:

```cmd
cd /d <duong-dan-den-P-227>\frontend
npm.cmd run dev
```

Truy cập:

- Web: `http://localhost:5173`
- Swagger: `http://127.0.0.1:8000/docs`
- Health: `http://127.0.0.1:8000/health`

Backend phải tự restore camera/Vision desired state. Bình thường không cần gọi Swagger để start camera/enable Vision sau mỗi restart.

## 7. Checklist sau startup

1. `/health` trả healthy.
2. `/docs` mở được.
3. Frontend không báo proxy error.
4. Camera desired ON tự restore.
5. Camera source lỗi được cô lập.
6. Overview tải preview/placeholder đúng.
7. Camera page mở live stream của camera được chọn.
8. Alerts/Persons/Settings/History tải từ backend/database.
9. Vision status đúng với desired/observed state.
10. SSE `/api/v1/alerts/stream` mở được.

## 8. Hardware profiles

- Torch có CUDA: `VISION_DEVICE=auto` có thể chọn CUDA.
- Không CUDA: YOLO/Pose/SDA-GCN chạy CPU theo profile hiện tại.
- Identity provider phụ thuộc environment/config.
- CPU không đủ target rate vẫn có thể chạy product ở `SUPPORTED-DEGRADED`.
- Không gọi profile degraded là realtime strict.

Các metric nên xem:

- `service_rate`
- `effective_sample_rate`
- `dropped_frames`
- `buffer_depth`
- `overload`
- `temporal_fidelity`

Docker Compose cố định Vision và identity provider ở CPU. Đây là profile dễ
tái tạo, không phải tuyên bố strict realtime. Webcam USB theo index thường
không đi qua Docker Desktop trên Windows; chạy native cho trường hợp đó.

## 9. Runtime data

```text
data/app.db     SQLite runtime
snapshots/      Event evidence images
```

Không chạy demo seed lên database người dùng đang có dữ liệu.

### Backup khi backend đã dừng

```cmd
if not exist backup mkdir backup
copy data\app.db backup\app-backup.db
```

Snapshot và database nên được backup cùng nhau nếu cần giữ đầy đủ evidence.

## 10. Troubleshooting

### Port 8000 đã được dùng — `Errno 10048`

```cmd
netstat -ano | findstr :8000
tasklist /FI "PID eq <PID>"
```

Dừng đúng process cũ hoặc đổi port và cập nhật proxy/frontend tương ứng.

Không chạy nhiều backend cùng ghi một SQLite database production chỉ để thử lỗi.

### Frontend `ECONNREFUSED`

Kiểm tra backend:

```cmd
curl http://127.0.0.1:8000/health
```

`ECONNREFUSED` khác `404`:

- `ECONNREFUSED`: không kết nối được process.
- `404`: backend đang chạy nhưng resource không tồn tại.

### Import/model path lỗi

Chạy từ root repo:

```cmd
python -c "from src.config import get_settings; print(get_settings())"
python -c "from src.main import app; print(app.title)"
```

Kiểm tra YOLO, YAML config, SDA-GCN checkpoint và InsightFace model root.

### Camera không có hình

Kiểm tra:

1. `GET /api/v1/cameras`.
2. observed state và error.
3. source file có tồn tại.
4. webcam index đúng.
5. RTSP URI đúng.
6. không có script OpenCV khác đang tranh webcam.
7. MJPEG endpoint trả `multipart/x-mixed-replace`.

`CameraRuntime` phải là capture owner duy nhất.

Preview có thể chưa tồn tại trước frame đầu tiên.

### Vision không chạy/cảnh báo

Xem:

```text
GET /api/v1/cameras/{id}/vision/status
```

Interpretation:

- `disabled`: desired Vision OFF.
- `waiting_for_source`: source chưa publish frame.
- `running`: Vision worker đang xử lý.
- `error`: xem current/last error.

Fall cần đủ temporal evidence; một person detection không đồng nghĩa event ngay.

Identity phải bật và FaceGallery/model phải load thành công để unknown-person behavior hoạt động.

### CPU quá tải

Dấu hiệu:

- service rate thấp;
- buffer gần capacity;
- drop tăng;
- fidelity `degraded`.

Không:

- tăng buffer vô hạn;
- giảm model window/stride chỉ để che throughput;
- gọi degraded là strict.

Có thể giảm số camera Vision đồng thời hoặc dùng hardware profile mạnh hơn đã kiểm chứng.

### Có event nhưng frontend không cập nhật

1. `GET /api/v1/alerts` phải có record.
2. SSE stream phải nhận initial `ready`.
3. Kiểm tra dispatcher counters trong Vision status.
4. Browser Network phải giữ SSE connection.
5. Restart backend sau khi đổi Python; Vite HMR chỉ reload frontend.

### Snapshot không hiện

- historical record cũ có thể thiếu backing file;
- API phải trả `null`/missing state thay vì URL giả;
- alert mới cần file snapshot hợp lệ nếu snapshot write thành công;
- frontend dùng placeholder;
- snapshot write failure không được làm event pipeline chết.

### SQLite lỗi

Integrity check:

```cmd
python -c "import sqlite3; c=sqlite3.connect('data/app.db'); print(c.execute('PRAGMA integrity_check').fetchone()[0])"
```

Kết quả mong đợi:

```text
ok
```

Trước maintenance destructive:

1. dừng backend;
2. backup database;
3. xác định target;
4. thao tác có chủ đích;
5. chạy integrity check lại.

### MediaPipe warning

Warning/deprecation message không tự động đồng nghĩa inference fail.

Chỉ coi là runtime failure khi:

- Vision status vào `error`;
- traceback cho thấy pipeline dừng;
- model/result không còn được cập nhật.

## 11. Khi nào dùng tài liệu nào

- Không chạy được hệ thống → file này.
- Không hiểu service/thread/data flow → [architecture.md](architecture.md).
- Cần endpoint → [api.md](api.md).
- Cần acceptance/release evidence → [testing.md](testing.md).
