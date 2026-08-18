# Kiến trúc kỹ thuật GuardianCam Local Hub

Tài liệu này mô tả production runtime hiện tại. Repository có một pipeline tại
`src/vision` và một subsystem classifier có thể thay thế tại `SDA-GCN`.

## 1. Process và dependency direction

Một FastAPI process sở hữu camera runtime, Vision sessions, event pipeline và
SQLite access. Không cần Redis, Kafka, Celery hoặc AI service theo viewer.

```text
FastAPI lifespan
  └── LocalRuntime
      ├── CameraRuntime
      ├── raw FrameHub
      ├── SynchronousVisionManager
      │   ├── LatestFrameSlot per camera
      │   ├── VisionSession per camera
      │   ├── CanonicalVisionPipeline
      │   └── processed FrameHub
      └── StreamService
```

`MockVisionEngine` + `VisionManager` là compatibility/test path. Canonical
production dùng `SynchronousVisionManager`; tên class được giữ để tránh đổi API
nội bộ, dù worker hiện chạy asynchronous với capture.

## 2. Capture và streaming

### Sole capture owner

`CameraRuntime` là nơi duy nhất mở `cv2.VideoCapture`. MJPEG, preview và Vision
không reopen source.

Mỗi frame được đóng gói trong `FramePacket` gồm:

- `frame_id`;
- raw frame;
- `captured_at`;
- `source_timestamp` và `source_time_kind`;
- `source_frame_index`;
- `source_epoch`;
- `discontinuity`.

### Raw-first fan-out

Sau capture:

1. raw packet được publish vào `FrameHub` ngay;
2. packet đủ điều kiện được offer non-blocking vào Vision latest slot.

Raw stream vì vậy chạy theo source cadence, không chờ YOLO/MediaPipe/SDA-GCN.
`FrameHub` chỉ giữ packet mới nhất; consumer chậm không tạo backlog.

### Presentation overlay

`StreamService` lấy raw frame hiện tại và latest VisionResult. Overlay chỉ được
dùng khi:

- cùng camera;
- cùng `source_epoch`;
- result observation time không ở tương lai;
- age không quá `0.75s`.

Viewer flags (`boxes`, `identity`) chỉ ảnh hưởng renderer. Fall overlay luôn bật
khi Vision chạy. Viewer connect/disconnect không restart camera, không reload
model và không tăng inference count.

## 3. Vision scheduling

Mỗi camera Vision-enabled có:

- một `VisionSession`;
- một `LatestFrameSlot` capacity 1;
- một worker thread.

Khi Vision bận, packet pending cũ bị thay bằng packet mới nhất. Đây là
latest-wins controlled dropping, không phải sampler/queue trước Vision.

Canonical pipeline giữ rule lấy zero-based even source frames. Rule này được
đánh giá trước khi packet chiếm slot; không dựa trên số lần consumer gọi.

### Sticky discontinuity

Nếu boundary packet bị overwrite trước khi worker consume, marker
`discontinuity=true` được chuyển sang packet mới nhất. Marker chỉ clear sau một
packet discontinuity đã được consume. Epoch cũ pending không được commit sau khi
source đã sang epoch mới.

## 4. Temporal semantics

Temporal AI dùng observation time từ capture boundary:

| Source | Timestamp |
|---|---|
| Video file | Media/source timestamp; deterministic frame/FPS fallback |
| Webcam/RTSP live | `time.monotonic()` ngay sau capture |

Pipeline không dùng inference-completion wall clock cho window, fall
confirmation, identity retry hoặc stranger cooldown.

Khi `source_epoch` đổi, giữ control-plane:

- `vision_identity_enabled`;
- `vision_identity_generation`;
- Vision desired state.

Reset temporal/source-dependent state:

- fall buffers/windows/pending decisions;
- tracking/Pose context state;
- face retry/cache;
- action/incident state.

Không có temporal window nào được nối qua hai source epochs.

## 5. Canonical Vision

```text
Eligible frame
  → YOLO person tracking
  → padded person crop
  → MediaPipe Pose
  → existing preprocessing
  → source-time 2-second window
  → linear resample to 64
  → SDA-GCN (1, 3, 64, 25, 1)
  → five classes; class 1 is fall candidate
  → existing confirmation/recovery state machine
```

Hardware selection:

1. native NVIDIA CUDA nếu khả dụng;
2. OpenVINO Intel GPU cho YOLO/SDA-GCN nếu khả dụng;
3. CPU fallback.

MediaPipe Pose chạy CPU. InsightFace chọn provider theo config/runtime;
DirectML thường dùng trên Intel Windows, CPU là fallback. Startup/status phải
report provider thật, không suy luận từ tên package.

## 6. Identity và Unknown

`FaceGallery` lấy known-person embeddings từ `persons` và `face_profiles` trong
SQLite. Gallery được cache và reload sau mutation; không query database mỗi
frame.

Identity behavior:

- threshold known match: cosine similarity `> 0.45`;
- 5 qualifying face+embedding observations;
- minimum interval 1 giây observation time;
- face miss update cadence timestamp nhưng không tăng confirmation count;
- cache/retry độc lập theo track;
- Unknown cooldown 60 giây observation time theo camera/epoch/track.
- Fall cooldown 60 giây observation time theo camera/epoch, ngoài cơ chế chỉ
  phát một cảnh báo trong cùng một fall incident của pipeline.

Product mismatch score:

```text
1 - clamp(closest_known_cosine_similarity, 0, 1)
```

`VisionProductPolicy` đọc `general.stranger_threshold` live từ SQLite.

Identity OFF có ba hard boundaries có chủ đích:

1. runtime không chạy continuous identity workflow;
2. manager xóa stale metadata/Unknown event tại commit boundary;
3. `EventService` re-check persisted identity state trước DB/SSE.

Các guard này chống in-flight race; không được xem là accidental duplication.
Fall không đọc identity gate.

## 7. Event commit và snapshots

Per-camera feature lock serialize:

1. final Identity guard;
2. product policy;
3. exact-frame snapshot;
4. processed packet publish;
5. event dispatch.

Heavy inference chạy ngoài feature lock.

Privacy evidence fallback:

1. exact-frame identity face bbox;
2. CPU-only full-frame detection;
3. person crop + upscale;
4. rotated person crop +90;
5. rotated person crop -90;
6. safe pose/head ROI;
7. omit snapshot nếu không tìm được vùng blur an toàn.

Privacy detection là detection-only, không tạo embedding hoặc Unknown state.
Không blur toàn frame và không dùng face bbox từ frame khác.

`ThreadsafeVisionEventDispatcher` chuyển event sang bounded async sink.
`EventService` persist trước rồi mới publish SSE. Event ID idempotent.

Media là optional evidence: repository dùng savepoint riêng cho media insert.
Snapshot/media failure được log nhưng không rollback event/alert hoặc chặn SSE.

## 8. Desired và observed state

SQLite lưu desired state; runtime giữ observed state.

```text
desired camera ON + source unavailable
→ camera observed error/offline
→ desired state vẫn ON

desired Vision ON + chưa có frame
→ Vision waiting_for_source
```

Startup load FaceGallery, bind event loop/dispatcher, start runtime rồi restore
Camera/Vision/Identity state. Một camera lỗi không làm application startup fail.

Shutdown dừng camera capture trước, sau đó Vision/model resources và event
transport.

## 9. Persistence và frontend

SQLite domains:

| Domain | Tables |
|---|---|
| Camera | `cameras`, `camera_sources` |
| Identity | `persons`, `face_profiles` |
| Events | `events`, `event_persons`, `fall_event_details` |
| Alerts | `alerts`, `alert_actions` |
| Evidence | `media_assets` |
| Configuration | `system_settings` |

Frontend data flow:

- Overview: REST + static preview.
- Camera: REST + một selected MJPEG stream.
- Alerts: initial REST + SSE refresh.
- Persons: REST CRUD/enrollment.
- Settings: persisted API; thresholds áp dụng live.
- History: persisted events/media.

## 10. State ownership

| State | Owner |
|---|---|
| Camera/Vision/Identity desired state | SQLite + camera/settings services |
| Identity generation/feature flag | `SynchronousVisionManager` session |
| Fall/face temporal state | canonical pipeline `VisionSession` |
| Raw latest frame | raw `FrameHub` |
| Latest structured result | Vision manager |
| Exact processed packet | processed `FrameHub` |
| Overlay flags | viewer/frontend + renderer |
| Event/alert/media | EventService/repository |

## 11. Failure isolation

| Failure | Expected behavior |
|---|---|
| Camera source failure | Camera lỗi; backend/camera khác tiếp tục |
| Vision frame/model exception | Raw stream tiếp tục; worker xử lý frame sau |
| Vision chậm | Slot giữ latest frame; raw stream không chậm theo |
| Viewer disconnect | Generator kết thúc; runtime/model không đổi |
| Snapshot unsafe/write failure | Event/alert/SSE sống; media omitted |
| Media DB insert failure | Event/alert transaction sống; media omitted |
| SSE disconnect | Persistence không đổi; client reconnect |

## 12. SDA-GCN boundary

```text
Camera -> FrameHub -> src/vision (YOLO + pose)
       -> src/vision/sda_gcn.py -> SDA-GCN/sda_gcn.SdaGcnRuntime
       -> class probabilities -> P-227 confirmation/cooldown/event flow
```

SDA-GCN owns model inference and model-specific NTU-25 preprocessing. P-227 owns
source-time windows, pending/confirmation state, cooldown, database, snapshots,
and frontend delivery. Retraining is: train -> export -> replace
`SDA-GCN/weights/fall-detection-joint.pt` -> run vision tests -> restart P-227.

## 13. Intentional non-goals

- không queue/backlog vô hạn;
- không capture/model theo viewer;
- không cloud video upload mặc định;
- không LLM trên critical detection path;
- không runtime retraining;
- chỉ import SDA-GCN qua public integration boundary `src/vision/sda_gcn.py`.

Xem thêm [architecture_diagram.md](architecture_diagram.md), [api.md](api.md),
[setup.md](setup.md) và [testing.md](testing.md).
