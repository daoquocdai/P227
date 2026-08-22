# GuardianCam Local Hub

GuardianCam là hệ thống giám sát an toàn local-first cho gia đình. Backend nhận
webcam, video file hoặc RTSP, phát video realtime cho frontend, đồng thời chạy
Vision để phát hiện té ngã và người chưa được nhận diện. Event, alert và ảnh
bằng chứng được lưu cục bộ trong SQLite/snapshot storage.

> GuardianCam là công cụ hỗ trợ cảnh báo, không thay thế thiết bị y tế, người
> chăm sóc hoặc dịch vụ khẩn cấp.

## Chức năng hiện tại

- Camera và trạng thái Camera/Vision/Identity được lưu trong SQLite và tự khôi
  phục khi backend khởi động.
- Raw MJPEG chạy theo source cadence, độc lập với tốc độ Vision.
- Production dùng reusable `SDA-GCN/sda_vision`; FastAPI chỉ truy cập Vision
  qua `src/integrations/sda_vision.py`.
- Một capacity-one latest-frame slot cho mỗi camera giữ latency bounded khi
  inference chậm; không có queue/backlog trước Vision.
- Video file dùng media/source timestamp; camera live dùng monotonic capture
  timestamp. Temporal decisions không phụ thuộc tốc độ máy xử lý.
- Fall Detection luôn hoạt động khi Vision ON. `Hiện khung` chỉ điều khiển
  presentation. `Phát hiện người lạ` điều khiển toàn bộ identity workflow.
- Event snapshot lấy đúng event frame và chỉ được lưu khi privacy blur an toàn.
- Event/alert vẫn được lưu và phát SSE nếu snapshot hoặc media metadata lỗi.
- CUDA được ưu tiên khi có; tiếp theo là OpenVINO Intel GPU; cuối cùng CPU.
  InsightFace dùng DirectML hoặc CPU theo provider thực tế.

## Stack

| Thành phần | Công nghệ |
|---|---|
| Vision | Ultralytics YOLO, MediaPipe, SDA-GCN, InsightFace |
| Accelerator | CUDA, OpenVINO Intel GPU, ONNX Runtime DirectML, CPU fallback |
| Backend | Python 3.11, FastAPI, Uvicorn, SSE |
| Frontend | React, TypeScript, Vite |
| Persistence | SQLite, local snapshot files |
| Kiểm thử | pytest, Ruff, TypeScript/Vite build |

## Yêu cầu

- Python 3.11 64-bit.
- Node.js 20+.
- Windows 10/11 hoặc Linux 64-bit.
- Webcam, video local hoặc RTSP nếu dùng source thật.
- Model/runtime assets do package `sda_vision` sở hữu.
- InsightFace `buffalo_l` chỉ khi bật Identity.

## Cài nhanh trên Windows

Chi tiết đầy đủ nằm tại [QUICKSTART.md](QUICKSTART.md).

```cmd
git clone https://github.com/AI20K-Build-Phase-Cohort-3/P-227.git
cd P-227
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements/vision-intel.txt
python -m pip install --no-deps -r requirements/vision-identity.txt
python -m pip install -e .\SDA-GCN
python -m pip install -r requirements/dev.txt
cd frontend
npm.cmd ci
cd ..
copy /Y .env.example .env
```

Chọn đúng dependency profile:

| Profile | File |
|---|---|
| Intel Iris Xe / Windows | `requirements/vision-intel.txt` |
| NVIDIA CUDA 12.4 | `requirements/vision-cuda.txt` |
| AMD / Windows DirectML | `requirements/vision-amd.txt` |
| CPU | `requirements/vision-cpu.txt` |
| Identity, cài sau profile với `--no-deps` | `requirements/vision-identity.txt` |
| Backend/test không chạy Real Vision | `requirements/base.txt` |

Repo không dùng `requirements.txt` chung vì Torch và ONNX Runtime phải khớp
hardware. Luôn cài đúng một `vision-*.txt`, sau đó cài
`vision-identity.txt` với `--no-deps` như Quickstart. Cài thêm
`requirements/dev.txt` nếu cần chạy pytest/Ruff; `requirements/base.txt` không
đủ để chạy Real Vision.

## Cấu hình

Copy `.env.example` thành `.env`. Cấu hình Vision chính:

```dotenv
DATABASE_URL=sqlite:///./data/app.db

VISION_ENGINE=sda
VISION_DEVICE=auto

VISION_IDENTITY_ENABLED=false
VISION_IDENTITY_PROVIDER=auto
VISION_INSIGHTFACE_ROOT=~/.insightface
```

- `VISION_ENGINE=sda` là production path duy nhất được cấu hình hỗ trợ.
- `VISION_DEVICE=auto` chọn CUDA → OpenVINO Intel GPU → CPU và log runtime thật.
- Giữ `VISION_IDENTITY_ENABLED=false` nếu chưa có
  `<VISION_INSIGHTFACE_ROOT>/models/buffalo_l/`.
- Integrated Identity dùng `persons` và `face_profiles` trong SQLite làm nguồn
  dữ liệu. Filesystem/NPZ chỉ còn dành cho SDA CLI standalone.
- Các biến temporal target-rate/buffer cũ không điều khiển SDA production path.
- Không commit `.env`, credential, database, snapshots hoặc dữ liệu sinh trắc.

FastAPI truy cập SDA runtime qua `src/integrations/sda_vision.py`.

## Chạy ứng dụng

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

- Web: <http://localhost:5173>
- Swagger: <http://127.0.0.1:8000/docs>
- Health: <http://127.0.0.1:8000/health>

Vite proxy `/api` và `/snapshots` sang backend. `ECONNREFUSED` đồng thời ở nhiều
endpoint nghĩa là backend không listen, không phải một API riêng trả lỗi.

## Kiến trúc runtime

### Nguồn Identity gallery

FastAPI tích hợp dùng SQLite `persons` và `face_profiles` làm source of truth.
Backend phát snapshot có version gồm `person_id`, tên và embedding tới các SDA
session khi startup và sau mutation Family; runtime không giữ ảnh enrollment.

CLI standalone `SDA-GCN/realtime.py` vẫn dùng `register face/` và NPZ cache.
Integrated session luôn chọn supplied-gallery rõ ràng và không fallback sang
filesystem, kể cả khi SQLite gallery rỗng.

```mermaid
flowchart LR
    SOURCE[Webcam / Video / RTSP] --> SDA[sda_vision source + 15 Hz Vision]
    SDA --> RAW[Raw FrameHub]
    RAW --> STREAM[MJPEG / Preview]
    SDA --> ADAPTER[src/integrations/sda_vision.py]
    ADAPTER --> POLICY[VisionProductPolicy]
    POLICY --> SNAP[Exact-frame privacy snapshot]
    SNAP --> PROCESSED[Processed FrameHub]
    POLICY --> DISPATCH[Thread-safe dispatcher]
    DISPATCH --> EVENT[EventService]
    EVENT --> DB[(SQLite)]
    EVENT --> SSE[SSE]
    STREAM --> UI[React]
    DB --> UI
    SSE --> UI
```

Renderer kết hợp raw frame hiện tại với latest VisionResult chỉ khi cùng
`source_epoch` và không stale quá `0.75s`. Viewer không tạo model, capture hoặc
inference riêng.

## Controls và semantics

| Control | Behavior |
|---|---|
| Vision OFF | Không xử lý Vision |
| Vision ON | Fall Detection luôn ON |
| Hiện khung OFF | Chỉ ẩn bbox/overlay; inference và event vẫn chạy |
| Phát hiện người lạ OFF | Tắt identity inference/retry/event/overlay; Fall không đổi |

Unknown cần 5 face+embedding observations hợp lệ, cách nhau tối thiểu 1 giây
source time. Face miss không tăng confirmation count. Unknown score trên UI là:

```text
Mức độ không khớp = 1 - clamp(closest known cosine similarity, 0, 1)
```

Đây không phải calibrated probability. `general.stranger_threshold` được đọc
từ database và áp dụng live, không cần restart.

## API chính

| Method | Endpoint | Chức năng |
|---|---|---|
| `GET` | `/health` | Process health |
| `GET` | `/api/v1/cameras` | Camera desired/observed state |
| `POST` | `/api/v1/cameras/{id}/start` | Bật camera |
| `POST` | `/api/v1/cameras/{id}/stop` | Tắt camera |
| `GET` | `/api/v1/cameras/{id}/stream` | MJPEG |
| `GET` | `/api/v1/cameras/{id}/preview` | Latest raw JPEG |
| `POST` | `/api/v1/cameras/{id}/vision/enable` | Bật Vision |
| `POST` | `/api/v1/cameras/{id}/vision/disable` | Tắt Vision |
| `PATCH` | `/api/v1/cameras/{id}/vision/identity` | Bật/tắt Unknown workflow |
| `GET` | `/api/v1/cameras/{id}/vision/status` | Vision/device/realtime metrics |
| `GET` | `/api/v1/alerts` | Alerts persisted |
| `GET` | `/api/v1/alerts/stream` | Realtime SSE |
| `GET` | `/api/v1/settings` | Settings persisted |
| `PATCH` | `/api/v1/settings/general` | Threshold/general settings áp dụng live |

### Ví dụ Queries (Sample Queries)

**1. Kiểm tra trạng thái hệ thống (Health Check)**
```bash
curl -X GET http://127.0.0.1:8000/health
```

**2. Lấy danh sách camera & trạng thái observed**
```bash
curl -X GET http://127.0.0.1:8000/api/v1/cameras
```

**3. Khởi chạy camera, bật Vision Engine & bật tính năng Nhận diện người lạ**
```bash
# Bật camera
curl -X POST "http://127.0.0.1:8000/api/v1/cameras/cam-1/start?loop_video=true"

# Bật Vision Engine (Fall Detection luôn ON)
curl -X POST http://127.0.0.1:8000/api/v1/cameras/cam-1/vision/enable

# Bật Identity Workflow (Phát hiện người lạ)
curl -X PATCH http://127.0.0.1:8000/api/v1/cameras/cam-1/vision/identity \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

**4. Xem trạng thái chi tiết Vision (Metrics, Latency, Device runtime)**
```bash
curl -X GET http://127.0.0.1:8000/api/v1/cameras/cam-1/vision/status
```

**5. Gửi sự kiện Vision mẫu (Vision Event Ingestion Adapter)**
```bash
curl -X POST http://127.0.0.1:8000/api/v1/vision/events \
  -H "Content-Type: application/json" \
  -d '{
    "schema_version": 1,
    "event_id": "evt-sample-001",
    "camera_id": "cam-1",
    "camera_location": "Phòng khách",
    "event_type": "FALL_CONFIRMED",
    "occurred_at": "2026-08-16T10:00:00Z",
    "confidence": 0.95,
    "track_id": "1",
    "identity_status": "UNKNOWN",
    "identity_name": null,
    "immobile_seconds": 3.5
  }'
```

**6. Lấy danh sách cảnh báo & Đánh giá xác minh (Human-in-the-loop Review)**
```bash
# Lấy danh sách alerts
curl -X GET http://127.0.0.1:8000/api/v1/alerts

# Cập nhật trạng thái xác minh cảnh báo
curl -X PATCH http://127.0.0.1:8000/api/v1/alerts/alt-1 \
  -H "Content-Type: application/json" \
  -d '{
    "status": "safe",
    "note": "Đã kiểm tra người thân an toàn"
  }'
```

**7. Thay đổi cấu hình ngưỡng hệ thống trực tiếp (General Settings Live Patch)**
```bash
curl -X PATCH http://127.0.0.1:8000/api/v1/settings/general \
  -H "Content-Type: application/json" \
  -d '{
    "stranger_threshold": 85,
    "fall_threshold": 80
  }'
```

**8. Lắng nghe cảnh báo thời gian thực qua SSE Stream**
```bash
curl -N http://127.0.0.1:8000/api/v1/alerts/stream
```

Xem contract đầy đủ tại [docs/api.md](docs/api.md).

## Kiểm thử

```cmd
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests
cd frontend
npm.cmd run build
cd ..
git diff --check
```

API tests cô lập native AI ở application boundary. Các pipeline/service tests
vẫn kiểm tra temporal state, latest-frame race, privacy, DB và event contracts.
Mock tests không thay thế native runtime smoke.

## Repository

```text
P-227/
├── src/                    # Production backend và SDA integration
├── frontend/               # React/Vite UI
├── database/schema.sql     # SQLite schema
├── tests/                  # API/service/Vision regressions
├── docs/                   # Tài liệu kỹ thuật
├── SDA-GCN/                # Model, preprocessing, config, weight và public runtime
├── tools/                  # Benchmark utilities
├── data/app.db             # Runtime data, không commit
└── snapshots/              # Event evidence, không commit
```

`src/integrations/sda_vision.py` là integration boundary giữa FastAPI runtime
và public package `SDA-GCN/sda_vision`.

## Privacy và persistence

- Raw video không được gửi cloud bởi Vision pipeline.
- Snapshot chỉ dùng đúng event frame.
- Privacy fallback: exact face bbox → CPU full-frame face detector → person crop
  → rotated crops → pose/head ROI → omit snapshot nếu vẫn không an toàn.
- Không blur toàn frame và không lưu khuôn mặt visible để “có ảnh”.
- Snapshot/media lỗi không rollback event/alert hoặc chặn SSE.
- SQLite, snapshot và face embedding là dữ liệu nhạy cảm; backup database và
  snapshot cùng nhau.

## Tài liệu

- [Quickstart](QUICKSTART.md)
- [Setup và troubleshooting](docs/setup.md)
- [Architecture](docs/architecture.md)
- [Architecture diagrams](docs/architecture_diagram.md)
- [API](docs/api.md)
- [Testing](docs/testing.md)
- [Gate 1 report](docs/Gate1.md)
