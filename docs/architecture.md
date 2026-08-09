# Kiến trúc kỹ thuật GuardianCam Local Hub

## 1. Mục tiêu tài liệu

Tài liệu này mô tả các quyết định kỹ thuật và invariant của production Local Hub. Sơ đồ được tách riêng tại [architecture_diagram.md](architecture_diagram.md).

Phạm vi V1 là **một tiến trình FastAPI** sở hữu:

- camera runtime;
- FrameHub;
- Vision worker;
- event pipeline;
- SQLite access;
- API cho frontend.

Không có AI node riêng cho từng camera và không cần Redis/Kafka/Celery trong V1.

## 2. Nguyên tắc thiết kế

### 2.1 Camera capture có một owner

`CameraRuntime` là nơi duy nhất được sở hữu `cv2.VideoCapture`.

Nó:

1. mở source;
2. đọc frame;
3. gắn metadata/source time;
4. publish `FramePacket`;
5. release capture trong lifecycle của chính capture thread.

MJPEG, preview và Vision không được mở lại cùng camera.

### 2.2 FrameHub dùng latest-frame semantics

`FrameHub` giữ frame mới nhất theo camera.

Mục tiêu:

- camera producer không bị consumer chậm block;
- không tích backlog frame vô hạn;
- streaming và Vision cùng đọc từ cùng nguồn frame đã publish.

### 2.3 Streaming và event là hai loại dữ liệu khác nhau

- **MJPEG:** video live.
- **JPEG preview:** latest static frame cho Overview/thumbnail.
- **SSE:** business alert/status event.

Không dùng SSE/base64 để truyền video.

### 2.4 Vision temporal buffer tách khỏi FrameHub

Vision cần temporal semantics riêng nên có `VisionSampleBuffer` bounded.

Buffer:

- bám `source_timestamp`;
- theo dõi `source_epoch`;
- xử lý discontinuity;
- ghi nhận input/temporal drop;
- báo overload/fidelity;
- không dùng capacity vô hạn để che throughput thiếu.

## 3. Runtime components

### CameraRuntime

Trách nhiệm:

- sole VideoCapture ownership;
- source webcam/video/RTSP;
- publish FramePacket;
- observed source state;
- release resource đúng thread.

Camera status không được suy ra từ Vision status.

### FrameHub

Trách nhiệm:

- lưu latest packet theo camera;
- cung cấp packet cho stream/preview;
- không tích queue vô hạn.

### StreamService

Trách nhiệm:

- MJPEG endpoint cho camera đang xem;
- encode/latest JPEG preview;
- không persist mọi frame.

### VisionSampleBuffer

Trách nhiệm:

- bounded temporal ingestion;
- preserve source-time contract;
- report drop/overload;
- clear/reset khi disable/discontinuity.

### VisionWorker

Một background worker xử lý camera đã bật Vision.

Worker:

- không block FastAPI event loop;
- không tạo `asyncio.run()` cho mỗi event;
- gọi VisionEngine;
- chuyển event qua dispatcher thread-safe.

### VisionEngine

V1 production dùng `LegacyVisionEngine`.

Pipeline:

```text
sampled frame
→ YOLO
→ person crop
→ MediaPipe Pose
→ skeleton preprocess
→ 64-sample window
→ SDA-GCN
→ fall state machine

person crop
→ InsightFace
→ FaceGallery
→ known / unknown
```

### Thread-safe event boundary

`ThreadsafeVisionEventDispatcher` là biên giữa Vision thread và asyncio.

Yêu cầu:

- dùng event loop đang chạy;
- handoff bằng thread-safe primitive;
- bounded delivery;
- không block Vision thread;
- không thao tác `asyncio.Queue` từ sai thread;
- shutdown phải từ chối delivery mới một cách an toàn.

### EventService / Repository

Trách nhiệm:

- normalize event;
- idempotency theo external event ID;
- transaction persistence;
- event/alert/media/history;
- publish SSE chỉ sau persistence thành công.

## 4. Lifecycle

Startup:

1. initialize/migrate SQLite;
2. tạo runtime services;
3. load FaceGallery;
4. bind async event sink/dispatcher;
5. start Vision worker;
6. load persisted camera/Vision desired state;
7. auto-start các camera desired ON;
8. auto-enable Vision desired ON.

Shutdown:

1. stop accepting work mới;
2. stop Vision/session/sampler;
3. stop camera runtime;
4. stop dispatcher/event consumer;
5. release remaining resources.

Một camera source lỗi không được làm application lifespan thất bại.

## 5. Desired state và observed state

Database lưu **desired state**. Runtime giữ **observed state**.

Ví dụ:

```text
Persisted:
camera desired = ON
vision desired = ON

Runtime:
camera = error
vision = waiting_for_source
```

Source lỗi không được tự đổi persisted desired state về OFF.

Camera observed state có thể gồm:

- `connecting`
- `online`
- `offline`
- `error`

Vision observed state có thể gồm:

- `disabled`
- `waiting_for_source`
- `running`
- `error`

`degraded` là fidelity/capacity status, không đồng nghĩa Vision `error`.

## 6. Vision V1 contract

### Model

- Input SDA-GCN: `(1, 3, 64, 25, 1)`.
- NTU 25-joint graph theo config/checkpoint hiện tại.
- Binary output theo class mapping đã train.
- Checkpoint strict load.

### Temporal semantics

Các metadata quan trọng:

- `source_timestamp`
- `source_time_kind`
- `source_epoch`
- `discontinuity`

Fall confirmation dùng source time, không dùng wall-clock CPU để thay ý nghĩa window.

Khi hardware không đủ throughput:

- bounded buffer được phép drop;
- camera/MJPEG phải tiếp tục;
- `temporal_fidelity` phải phản ánh `degraded`;
- không tăng buffer vô hạn;
- không đổi model window/stride chỉ để “chạy được”.

### Device

Các stage không nhất thiết cùng device:

| Stage | Runtime |
|---|---|
| YOLO | PyTorch device |
| MediaPipe Pose | CPU/TFLite trong profile hiện tại |
| Preprocess | CPU |
| SDA-GCN | PyTorch device |
| InsightFace | provider khả dụng theo cấu hình |

Không suy luận GPU support từ tên wheel. Chỉ báo acceleration khi provider/runtime thực tế có.

## 7. Face identity

Production identity dùng database:

```text
persons + face_profiles
        ↓
FaceGallery cache
        ↓
LegacyVisionEngine
```

Quy tắc:

- không query SQLite mỗi frame;
- embedding phải có dimension hợp lệ và finite;
- chỉ active person/profile được nạp;
- mutation Persons/face profiles làm gallery reload/invalidate;
- image enrollment không trở thành public static asset mặc định;
- `register face/` chỉ là compatibility fallback cho legacy/standalone nếu code còn hỗ trợ.

Face embedding là dữ liệu sinh trắc học nhạy cảm.

## 8. Snapshot và media

Có hai khái niệm tách biệt:

### Camera preview

- latest JPEG từ FrameHub;
- dùng cho Overview/thumbnail;
- không persist mọi frame;
- khi chưa có frame, API/UI biểu diễn `null`/placeholder.

### Event evidence snapshot

- gắn với business event;
- backing file nằm dưới snapshot root hợp lệ;
- DB chỉ trả URL nếu file hợp lệ tồn tại;
- record lịch sử thiếu file vẫn được giữ;
- UI dùng placeholder thay vì broken image.

## 9. Database

V1 dùng SQLite và `sqlite3`.

Nguồn schema:

- `database/schema.sql`: schema đầy đủ;
- `src/database.py`: connection + runtime idempotent migrations;
- `data/app.db`: runtime database, không version control.

Nhóm dữ liệu chính:

| Miền | Bảng |
|---|---|
| User/quyền | `users`, `user_permissions` |
| Người thân | `persons`, `face_profiles` |
| Camera | `cameras`, `camera_sources` |
| Vision event | `events`, `event_persons`, `fall_event_details` |
| Alert | `alerts`, `alert_actions` |
| Media | `media_assets` |
| Settings | `system_settings` |
| Evaluation | `evaluation_runs`, `inference_metrics` |

Các rule quan trọng:

- mọi connection bật `PRAGMA foreign_keys=ON`;
- external event ID phải idempotent;
- human correction/audit không được thay bằng overwrite lịch sử;
- camera đang chạy hoặc còn history có thể bị chặn xóa theo contract;
- media path phải chống traversal/URL tùy ý;
- database và snapshots phải được coi là một bộ khi backup bằng chứng.

## 10. Frontend data architecture

Frontend không giữ một “source of truth” riêng cho product data.

Các trang:

- **Overview:** REST + static previews.
- **Camera:** REST + một live MJPEG stream cho camera được chọn.
- **Alerts:** initial REST + SSE updates.
- **Persons:** REST CRUD + face enrollment.
- **Settings:** persisted backend settings.
- **History:** persisted event/media audit.

Không hard-code camera/person/alert/settings production data.

## 11. Failure isolation

| Failure | Expected behavior |
|---|---|
| Một camera source lỗi | Camera đó `error/offline`; backend và camera khác tiếp tục |
| Vision lỗi | Camera stream vẫn hoạt động |
| Vision quá chậm | Fidelity `degraded`; camera không bị block |
| Snapshot write lỗi | Event vẫn có thể được persist/deliver; UI báo thiếu bằng chứng |
| SSE client disconnect | Persistence vẫn hợp lệ; client reconnect |
| Missing historical snapshot | API không giả URL hợp lệ; UI placeholder |
| Invalid RTSP credential/path | Không phản chiếu secret ra frontend |

## 12. Security & privacy boundary

Không đưa vào Git:

- `.env`;
- API keys;
- RTSP credentials;
- runtime SQLite;
- snapshots;
- face images/embeddings.

API không được trả raw `source_uri` chứa credential về frontend.

Vision/business event không gửi raw frame/video qua JSON.

## 13. Những gì V1 cố ý không có

- distributed broker;
- nhiều database writer service;
- WebSocket video;
- agent quyết định sự kiện;
- per-camera AI service;
- cloud video upload mặc định;
- runtime model retraining.

## 14. Tài liệu liên quan

- [Architecture diagrams](architecture_diagram.md)
- [Gate 1](gate1.md)
- [API](api.md)
- [Setup](setup.md)
- [Testing](testing.md)
