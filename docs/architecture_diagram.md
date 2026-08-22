# GuardianCam — Architecture Diagrams

Các sơ đồ dưới đây phản ánh production runtime dùng `sda_vision` hiện tại.

## 1. Runtime

```mermaid
flowchart LR
    SRC[Webcam / Video / RTSP] --> SESSION[sda_vision VisionSession per camera]
    SESSION --> RAWCB[on_source_frame callback]
    RAWCB --> RAW[Raw FrameHub latest]
    RAW --> PREVIEW[Preview JPEG]
    RAW --> MJPEG[MJPEG]
    SESSION --> VISION[Pose + SDA-GCN + optional Identity]
    VISION --> RESULTCB[on_result_frame callback]
    RESULTCB --> MAP[Application VisionResult mapping]
    MAP --> WORKER[Bounded SdaEventMediaWorker]
    WORKER --> POLICY[VisionProductPolicy]
    POLICY --> SNAP[Exact-frame privacy snapshot]
    SNAP --> DISPATCH[Thread-safe dispatcher]
    DISPATCH --> SINK[Async event sink]
    SINK --> SERVICE[EventService]
    SERVICE --> DB[(SQLite)]
    SERVICE --> SSE[SSE]
    PREVIEW --> CLIENT[Client]
    MJPEG --> CLIENT
    DB --> CLIENT
    SSE --> CLIENT
```

## 2. Session scheduling

```mermaid
flowchart TD
    CAPTURE[Source capture thread] --> STORE[Latest source snapshot store]
    CAPTURE --> CALLBACK[Raw callback immediately]
    CALLBACK --> HUB[Raw FrameHub]
    CLOCK[Fixed-rate Vision scheduler] --> READ[Read newest snapshot]
    STORE --> READ
    READ -->|No newer frame| WAIT[Wait next tick]
    READ -->|New frame| INFER[Vision inference]
    INFER --> RESULT[VisionFrameResult]
```

Capture không chờ inference. Scheduler lấy snapshot mới nhất nên không tạo
queue frame vô hạn khi Vision chậm.

## 3. Stream overlay

```mermaid
flowchart TD
    RAW[Current raw FramePacket] --> CHECK{Latest result hợp lệ?}
    RESULT[Latest VisionResult] --> CHECK
    CHECK -->|khác camera/epoch| PLAIN[Render raw]
    CHECK -->|future hoặc age > 0.75s| PLAIN
    CHECK -->|cùng epoch và fresh| OVERLAY[Render raw + overlay]
    FLAGS[Viewer boxes/identity flags] --> OVERLAY
    OVERLAY --> JPEG[MJPEG JPEG]
    PLAIN --> JPEG
```

## 4. Identity gallery

```mermaid
flowchart LR
    DB[(persons + face_profiles)] --> PROVIDER[SqliteFaceGalleryProvider]
    PROVIDER --> COORD[FaceGalleryCoordinator]
    COORD --> PUBLISH[SdaGalleryPublisher]
    PUBLISH --> SNAP[IdentityGallerySnapshot]
    SNAP --> S1[VisionSession camera 1]
    SNAP --> S2[VisionSession camera N]
```

Integrated mode chỉ dùng supplied gallery từ SQLite. Filesystem/NPZ chỉ dành
cho SDA CLI standalone.

## 5. Identity OFF race protection

```mermaid
sequenceDiagram
    participant UI as Client
    participant API as Cameras API
    participant DB as SQLite desired state
    participant R as SdaSessionRegistry
    participant S as VisionSession
    participant E as Event boundary

    UI->>API: Identity OFF
    API->>DB: persist OFF first
    API->>R: set_identity_enabled(false)
    R->>S: stop/reset Identity stage
    S-->>R: possible in-flight result
    R->>R: omit identity event/metadata
    E->>DB: reject invalid Unknown before persistence
    Note over R,E: Fall event remains independent
```

## 6. Snapshot privacy và optional media

```mermaid
flowchart TD
    EVENT[Fall/Unknown event] --> EXACT{Exact-frame face bbox?}
    EXACT -->|yes| BLUR[Blur face ROI]
    EXACT -->|no| FULL[CPU full-frame detector]
    FULL -->|miss| CROP[Person crop / rotated crops]
    CROP -->|miss| POSE[Pose/head safe ROI]
    POSE -->|miss| OMIT[Omit snapshot]
    FULL -->|found| BLUR
    CROP -->|found| BLUR
    POSE -->|safe| BLUR
    BLUR --> MEDIA[Optional media savepoint]
    OMIT --> PERSIST[Persist event + alert]
    MEDIA --> PERSIST
    PERSIST --> SSE[SSE alert]
```

## 7. Startup restore

```mermaid
sequenceDiagram
    participant APP as FastAPI lifespan
    participant DB as SQLite
    participant RT as LocalRuntime
    participant G as FaceGalleryCoordinator
    participant REG as SdaSessionRegistry

    APP->>DB: initialize/migrate
    APP->>APP: start event sink/dispatcher
    APP->>RT: create runtime
    RT->>G: load and publish supplied gallery
    APP->>REG: start event-media worker
    APP->>RT: restore persisted state
    loop each desired Camera ON
        RT->>REG: create VisionSession/source
    end
    Note over APP,REG: one unavailable source does not fail application startup
```
