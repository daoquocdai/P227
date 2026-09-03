# Cài đặt, vận hành và troubleshooting

Tài liệu này áp dụng cho implementation trong current checkout. Xem
[QUICKSTART.md](../QUICKSTART.md) nếu chỉ cần luồng chạy ngắn nhất.

## 1. Yêu cầu

- Git.
- Python 3.11 64-bit.
- Node.js 20+ và npm.
- Windows 10/11 hoặc Linux 64-bit.
- Webcam, video local hoặc RTSP nếu dùng source thật.
- Đủ model assets trong `SDA-GCN` như mô tả bên dưới.

## 2. Tạo môi trường Python

Chạy từ thư mục gốc repository:

```cmd
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
```

Chỉ chọn **một** profile phù hợp với máy:

```cmd
rem Intel Iris Xe / Windows
python -m pip install -r requirements\vision-intel.txt

rem Hoặc NVIDIA CUDA 12.4
python -m pip install -r requirements\vision-cuda.txt

rem Hoặc AMD / Windows DirectML
python -m pip install -r requirements\vision-amd.txt

rem Hoặc CPU
python -m pip install -r requirements\vision-cpu.txt
```

Không trộn nhiều profile trong cùng `.venv`. Nếu cài nhầm, tạo lại môi trường
thay vì uninstall riêng Torch, ONNX Runtime hoặc OpenCV.

Cài Identity và public SDA package:

```cmd
python -m pip install --no-deps -r requirements\vision-identity.txt
python -m pip install -e .\SDA-GCN
```

InsightFace được cài bằng `--no-deps` để không kéo thêm ONNX Runtime/OpenCV gây
xung đột. Chỉ nên có một package `onnxruntime*` và một OpenCV trong môi trường.
`pip check` có thể vẫn báo dependency metadata `onnxruntime`/`opencv-python`
thiếu vì tên package thay thế không khớp metadata của InsightFace. Không cài
ORT CPU hoặc `opencv-python` trùng chỉ để xóa cảnh báo này.

Nếu cần chạy pytest và Ruff:

```cmd
python -m pip install -r requirements\dev.txt
```

`requirements/base.txt` chỉ phù hợp cho backend/test không chạy native Vision.

## 3. Frontend và file môi trường

```cmd
cd frontend
npm.cmd ci
cd ..
copy /Y .env.example .env
```

Không commit `.env`, API key, database, snapshots hoặc face embeddings.

## 4. Cấu hình runtime

`.env.example` là cấu hình mẫu chuẩn. Baseline an toàn:

```dotenv
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=8000
FRONTEND_PORT=5173
CORS_ORIGINS=http://localhost:5173
API_BASE_URL=http://localhost:8000
DATABASE_URL=sqlite:///./data/app.db

VISION_ENGINE=sda
VISION_DEVICE=auto
VISION_IDENTITY_PROVIDER=auto
VISION_INSIGHTFACE_ROOT=~/.insightface

ALERT_AGENT_ENABLED=false

FALL_ESCALATION_ENABLED=true
FALL_CALL_AFTER_SECONDS=30
FALL_ESCALATION_POLL_SECONDS=2
FALL_CALL_MAX_ATTEMPTS=3
FALL_CALL_RETRY_SECONDS=10
EMERGENCY_CALL_PROVIDER=twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_FROM_PHONE_NUMBER=
```

- `VISION_ENGINE=sda` là production engine duy nhất được hỗ trợ.
- `VISION_DEVICE` nhận `auto`, `cpu`, `cuda`, `amd`, `intel`.
- Core application không cần OpenAI API key khi Alert Agent OFF.
- Identity nên để OFF cho đến khi `buffalo_l` sẵn sàng.
- Uvicorn CLI bên dưới truyền host/port trực tiếp; các đối số CLI đó thắng giá
  trị `APP_HOST`/`APP_PORT` trong `.env`.

Fall escalation là policy deterministic, không phụ thuộc Alert Agent: `Đã xem`
vẫn tiếp tục đếm thời gian, `Xác nhận an toàn`/`Báo sai` hủy escalation, còn
`Cần trợ giúp` làm incident đủ điều kiện gọi ngay. Quản lý số E.164 qua API
`/api/v1/emergency-contacts` (quyền `manage_persons`). Twilio dùng inline TwiML;
thiếu credentials không ngăn app khởi động và attempt sẽ được ghi là thất bại.

Để test không tốn cuộc gọi, đặt `EMERGENCY_CALL_PROVIDER=logging`, thêm contact,
gửi một `FALL_CONFIRMED` qua API Vision rồi xem các trường `escalation_*` của
alert. Provider này chỉ log destination suffix và luôn ghi `DEV_LOG_ONLY`, không
bao giờ giả báo đã liên hệ thành công. Chỉ chuyển sang `twilio` sau khi điền đủ
ba biến `TWILIO_*` bằng credentials/số gọi thật.

## 5. Model assets

Fall Detection sử dụng assets do SDA package sở hữu:

```text
SDA-GCN/pose_landmarker_full.task
SDA-GCN/work_dir/fall_detection/fall/config.yaml
SDA-GCN/work_dir/fall_detection/fall/runs-best_val.pt
```

Identity cần:

```text
<VISION_INSIGHTFACE_ROOT>/models/buffalo_l/
```

Integrated Identity lấy gallery từ SQLite `persons` và `face_profiles`; không
cần `VISION_KNOWN_FACES_DIR`. Không đổi checkpoint, preprocessing, window hoặc
class mapping chỉ để bỏ qua lỗi asset.

## 6. Device selection

Với `VISION_DEVICE=auto`, runtime chọn backend khả dụng và báo kết quả thực tế
qua startup log và Vision status. Profile dependency quyết định các provider có
thể sử dụng:

| Profile | Mục đích |
|---|---|
| Intel | OpenVINO cho action model; DirectML/CPU cho Identity |
| NVIDIA | CUDA Torch và ONNX Runtime GPU |
| AMD Windows | Torch DirectML và ONNX Runtime DirectML |
| CPU | Portable CPU, cũng là profile Docker |

MediaPipe Pose chạy CPU. Privacy detector one-shot ưu tiên đường chạy an toàn;
không suy luận device chỉ từ tên package đã cài.

Action auto-selection theo thứ tự NVIDIA CUDA → AMD ROCm/Windows DirectML →
Intel OpenVINO GPU → CPU. Identity resolve độc lập: NVIDIA CUDAExecutionProvider,
Windows DmlExecutionProvider cho Intel/AMD, rồi CPU; AMD Linux GPU Identity
không có provider được hỗ trợ trong profile hiện tại. Manual selection không
khả dụng sẽ fail rõ ràng. Đây là capability support từ code, không phải tuyên
bố mọi hardware đã được kiểm thử vật lý.

### Admin bootstrap lần đầu

Trước lần chạy đầu, có thể đặt `ANTAM_INITIAL_ADMIN_PASSWORD` trong environment.
Database bootstrap tạo `admin@example.local`, dùng giá trị đó hoặc fallback
development `AnTam@123`, và bật `force_password_change`. UI yêu cầu đổi password
tối thiểu 8 ký tự sau login. `.env.example` hiện chưa liệt kê biến tùy chọn này.

## 7. Khởi động native

Terminal 1, từ thư mục gốc:

```cmd
.venv\Scripts\python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

Terminal 2:

```cmd
cd frontend
npm.cmd run dev
```

Kiểm tra:

```cmd
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/api/v1/status
curl http://127.0.0.1:8000/api/v1/cameras
```

- Web: <http://localhost:5173>
- Swagger: <http://127.0.0.1:8000/docs>

Backend restore persisted Camera/Vision desired state; Identity đi cùng Vision. Một source lỗi
không làm toàn bộ FastAPI startup fail.

## 8. Runtime status

```text
GET /api/v1/cameras/{camera_id}/runtime/status
GET /api/v1/cameras/{camera_id}/vision/status
```

Camera status có `status`, `error`, `capture_fps`, `source_frames_read` và
`frames_published`. Vision status độc lập và có thể là `disabled`,
`waiting_for_source`, `running`, `error`.

Các trường chính gồm `processed_frames`, `last_processed_frame_id`,
`current_error`, `identity_status`, `identity_error`, `realtime` và `hardware`. `realtime` chứa
`vision_fps`, `vision_processing_latency_ms`, `vision_frames_processed` cùng
stage metrics từ SDA. `pending=0` và `max_pending=1` là compatibility metrics;
production scheduling thực tế lấy latest snapshot theo fixed-rate scheduler.

## 9. Controls

- Vision ON bật pipeline Pose/Action/Fall và yêu cầu Identity.
- `Hiện khung` chỉ ảnh hưởng presentation.
- Identity unavailable không làm dừng Fall hoặc privacy detection cho Fall snapshot.

## 10. Kiểm thử

Sau khi đã cài `requirements/dev.txt`:

```cmd
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests
.venv\Scripts\python.exe -m ruff format --check src tests
cd frontend
npm.cmd run build
cd ..
git diff --check
```

Xem checklist đầy đủ tại [testing.md](testing.md).

## 11. Runtime data và backup

Runtime data chính:

```text
data/app.db
snapshots/
```

Dừng backend trước khi backup:

```cmd
if not exist backup mkdir backup
copy data\app.db backup\app-backup.db
xcopy snapshots backup\snapshots\ /E /I
```

Không xóa database, alerts, events hoặc snapshots nếu chưa backup và chưa xác
định chính xác dữ liệu cần xóa.

## 12. Docker Compose

Docker Compose chạy backend bằng CPU profile và frontend qua web server. Phù
hợp nhất với video file hoặc RTSP; webcam index trên Docker Desktop/Windows có
thể không được chuyển vào container, nên dùng native khi demo webcam USB.

Chuẩn bị `.env`, thư mục dữ liệu và khởi động:

```cmd
copy /Y .env.example .env
if not exist data mkdir data
if not exist snapshots mkdir snapshots
docker compose up --build --detach
docker compose ps
docker compose logs --follow --tail=200
```

Truy cập:

- Frontend: <http://localhost:5173>
- Backend health: <http://localhost:8000/health>
- Swagger: <http://localhost:8000/docs>

Compose mount `data/`, `snapshots/` và demo files dưới `frontend/public/`.
Backend container ép `VISION_DEVICE=cpu` và
`VISION_IDENTITY_PROVIDER=cpu`. Identity được yêu cầu khi Vision chạy.

Để Identity khả dụng trong Docker:

1. Đảm bảo model `buffalo_l` tồn tại trong named volume
   `insightface_models` tại `/home/appuser/.insightface/models/buffalo_l/`.
2. Recreate backend container và kiểm tra startup log.

Dừng dịch vụ:

```cmd
docker compose down
```

Lệnh này không xóa named volume. Chỉ dùng `docker compose down --volumes` khi
chủ động muốn xóa model volume và đã xác nhận dữ liệu không cần giữ.

## 13. Troubleshooting

### Backend hoặc frontend báo `ECONNREFUSED`

```cmd
curl http://127.0.0.1:8000/health
netstat -ano | findstr :8000
```

Nếu nhiều API cùng lỗi, kiểm tra backend trước. Không chạy hai backend cùng ghi
một SQLite database.

### Camera đen hoặc không có preview

1. Kiểm tra runtime `status` và `error`.
2. Kiểm tra `/preview` trả `200 image/jpeg`, `X-Frame-Id` tăng.
3. Xác nhận source path/index/RTSP hợp lệ.
4. Đóng ứng dụng khác đang giữ webcam.

Raw preview không phụ thuộc Vision; nếu preview lỗi, xử lý source trước model.

### Vision lỗi hoặc chậm

Kiểm tra `current_error`, `realtime`, `hardware` và startup diagnostics. Khi
Vision chậm hơn capture, fixed-rate scheduler đọc latest snapshot và có thể bỏ
frame trung gian; raw stream vẫn phải tiếp tục.

Kiểm tra ba SDA assets ở mục 5. Không tăng queue hoặc đổi temporal window để
che lỗi throughput.

### Identity không bật

- Xác nhận `buffalo_l` đúng dưới configured root.
- Kiểm tra effective ONNX provider trong hardware/startup log.
- Bật Vision trước Identity.
- Kiểm tra persisted Identity state và active face profiles trong SQLite.

### Có event nhưng không có snapshot

Đây có thể là privacy fail-closed đúng thiết kế. Event, alert và SSE vẫn được
giữ khi không tìm được vùng blur an toàn hoặc media write thất bại.

### SQLite integrity

```cmd
python -c "import sqlite3; c=sqlite3.connect('data/app.db'); print(c.execute('PRAGMA integrity_check').fetchone()[0])"
```

Kết quả mong đợi: `ok`.

### Docker không healthy

```cmd
docker compose ps
docker compose logs backend --tail=200
docker compose config
```

Kiểm tra port trùng, quyền ghi `data/`/`snapshots/`, model assets trong image và
giá trị `.env`. Nếu chỉ Identity lỗi, kiểm tra `identity_status`/`identity_error`;
Fall/runtime cốt lõi vẫn phải tiếp tục chạy.
