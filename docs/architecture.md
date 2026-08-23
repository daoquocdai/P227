# Kiến trúc kỹ thuật GuardianCam Local Hub

Tài liệu này mô tả production runtime trong current checkout. FastAPI
tích hợp public package `SDA-GCN/sda_vision` qua
`src/integrations/sda_vision.py`. `src/vision` và `VisionManager` chỉ còn là
explicit model-free test seam, không phải production path.

## 1. Process và dependency

```text
FastAPI lifespan
  ├── SQLite + optional Alert Agent/metrics
  ├── vision event sink + ThreadsafeVisionEventDispatcher
  └── LocalRuntime
      ├── SdaSessionRegistry
      │   ├── một VisionSession cho mỗi camera đang chạy
      │   └── SdaEventMediaWorker
      ├── SdaCameraFacade + SdaVisionFacade
      ├── raw FrameHub
      └── StreamService
```

Production dependency đi một chiều:

```text
src/runtime.py
  -> src/integrations/sda_vision.py
  -> SDA-GCN/sda_vision public API
```

FastAPI không import model internals trực tiếp. Hai facade giữ interface cho
API/service hiện tại.

## 2. Session và source ownership

Mỗi camera đang chạy có đúng một `sda_vision.VisionSession` do
`SdaSessionRegistry` quản lý. Session sở hữu `CameraSource` (webcam),
`VideoFileSource` hoặc `StreamSource` (RTSP).

Source callback được map thành `FramePacket` và publish vào raw `FrameHub`.
Preview/MJPEG đọc hub này; viewer không mở source hoặc tạo model/session mới.
Mỗi lần tạo/reconnect source dùng `source_epoch`; frame/result epoch cũ không
được ghép với epoch mới.

## 3. Capture và scheduling

1. Source thread đọc frame theo source/playback timeline.
2. Raw callback publish frame mới nhất ngay cho streaming.
3. `VisionSession` chạy fixed-rate scheduler theo `VISION_FPS` (mặc định 15 Hz).
4. Scheduler lấy snapshot mới hơn gần nhất; frame trung gian có thể bị bỏ để
   tránh backlog.

Vision OFF không dừng source/raw stream. Source lỗi chỉ cập nhật observed state
của camera đó, không làm FastAPI process dừng.

## 4. Production Vision pipeline

```text
Latest source frame
  -> resize/letterbox
  -> MediaPipe Pose async
  -> pose samples theo source timeline
  -> cửa sổ 2 giây, resample 64 frame
  -> SDA-GCN action classifier
  -> fall state/confirmation
  -> optional InsightFace Identity
  -> VisionFrameResult callback
```

`VISION_DEVICE=auto` chọn backend khả dụng; status báo device/provider thực tế.
Identity chỉ khởi tạo khi được bật và có `buffalo_l`. Temporal state reset khi
`source_epoch` đổi. Video dùng media timeline; nguồn live dùng monotonic arrival
timeline, không dùng inference-completion time cho quyết định temporal.

## 5. Mapping và presentation

Integration map source/result/detection/event của SDA sang model ứng dụng.
Registry giữ latest structured result. `StreamService` chỉ ghép overlay khi
camera và `source_epoch` trùng, result không ở tương lai và age không quá
`0.75s`. `boxes`/`identity` chỉ ảnh hưởng presentation, không restart source hay
thay đổi inference.

## 6. Identity supplied gallery

```text
SQLite persons + face_profiles
  -> SqliteFaceGalleryProvider
  -> FaceGalleryCoordinator
  -> SdaGalleryPublisher
  -> IdentityGallerySnapshot
  -> các VisionSession đang chạy
```

Mutation người thân/khuôn mặt refresh gallery sau commit. Integrated session
luôn dùng `identity_gallery_mode="supplied"`; không fallback filesystem/NPZ khi
SQLite rỗng. Filesystem/NPZ chỉ thuộc SDA CLI standalone.

Identity OFF được persist trước, dừng/reset Identity stage và chặn Unknown
event/metadata trước persistence. Fall Detection không phụ thuộc Identity.

Identity state là `UNVERIFIED`, `KNOWN`, `UNKNOWN`, `LOCKED_KNOWN`,
`LOCKED_UNKNOWN`. Mặc định recognition threshold là cosine 0.45; Known lock
ngay, Unknown lock sau 3 usable-face mismatches với retry 1 giây, revalidate
locked Unknown sau 15 giây và reset presence sau 1,5 giây vắng. Không tìm thấy
khuôn mặt dùng được là inconclusive, không phải mismatch.

## 7. Event, policy và snapshot

```text
VisionFrameResult
  -> map_vision_result
  -> bounded SdaEventMediaWorker
  -> VisionProductPolicy
  -> exact-frame privacy snapshot
  -> ThreadsafeVisionEventDispatcher
  -> async event sink -> EventService
  -> SQLite -> SSE
```

ProductPolicy chỉ xét Unknown khi có track/association,
`LOCKED_UNKNOWN` và `identity_face_verified=true`. Nó đọc live threshold SQLite
(mặc định stranger 78%, fall 72%); mismatch score là
`1 - clamp(cosine similarity, 0, 1)`, không phải probability. Unknown/Fall có
cooldown mặc định 60 giây, và Fall suppress Unknown notification gần đó.

Unknown candidates cùng camera/epoch/track được coalesce ở pending và inflight.
Semantic queue được phục vụ trước repeated candidates. Nếu semantic queue đầy,
semantic event vẫn được dispatch nhưng có thể không có snapshot. Privacy worker
chỉ lưu bằng chứng khi tạo được vùng blur an toàn. Snapshot/media lỗi không
rollback event/alert và không chặn SSE. `EventService` persist trước broadcast;
`event_id` là idempotency key.

## 8. Desired và observed state

SQLite lưu desired Camera/Vision/Identity state; registry giữ observed source
và session state. Desired ON vẫn được giữ nếu source tạm lỗi. Startup theo thứ
tự: database -> event pipeline -> `LocalRuntime`/gallery -> registry -> restore
persisted state. Một camera lỗi không làm startup toàn ứng dụng fail.

Shutdown do FastAPI lifespan quản lý: agent/metrics, camera sessions,
Vision/event worker và event transport được dừng có kiểm soát.

## 9. Persistence và ownership

| State/domain | Owner |
|---|---|
| Camera/Vision/Identity desired state | SQLite + application services |
| Running sessions/observed status | `SdaSessionRegistry` |
| Source capture/temporal Vision state | `sda_vision.VisionSession` |
| Supplied Identity gallery | `FaceGalleryCoordinator` + SDA sessions |
| Raw latest frame | raw `FrameHub` |
| Latest structured result | `SdaSessionRegistry` |
| Viewer overlay flags | `StreamService`/request |
| Product cooldown/snapshot work | `SdaEventMediaWorker` |
| Event/incident/alert/media | `EventService`/repositories |
| Realtime alerts | alert broadcaster/SSE |

Persistence gồm camera tables, `persons`, `face_profiles`, events, alerts,
media assets, settings và operational metrics. SQLite, snapshot và embedding là
dữ liệu nhạy cảm; raw video không được Vision pipeline tải lên cloud mặc định.

## 10. Failure isolation

| Failure | Hành vi mong đợi |
|---|---|
| Source failure | Camera đó lỗi; API/camera khác tiếp tục |
| Vision/model exception | Session báo lỗi; FastAPI tiếp tục |
| Vision chậm | Scheduler lấy latest frame, không backlog capture |
| Viewer disconnect | Session/model không đổi |
| Identity model thiếu | Identity unavailable; Fall độc lập |
| Snapshot unsafe/write failure | Event sống, media có thể bị bỏ |
| Event-media queue đầy | Semantic event vẫn dispatch không snapshot |
| SSE disconnect | Persistence không đổi; client reconnect |
| Alert Agent tắt/lỗi | Detection, alert và history cốt lõi vẫn chạy |

## 11. Public boundary và trách nhiệm

`src/integrations/sda_vision.py` chỉ import public contracts:
`VisionSession`, `VisionSessionConfig`, `VisionCallbacks` và
`IdentityGallerySnapshot`.

`SDA-GCN/sda_vision` sở hữu source, scheduling, Pose, SDA-GCN, Identity stage
và preprocessing. P-227 sở hữu API, desired state, SQLite supplied gallery,
product policy, privacy snapshot, persistence và SSE.

Xem thêm [architecture_diagram.md](architecture_diagram.md), [api.md](api.md),
[setup.md](setup.md) và [testing.md](testing.md).
