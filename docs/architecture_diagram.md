# GuardianCam — Architecture Diagrams

Các sơ đồ dưới đây phản ánh production runtime hiện tại.

## 1. Runtime

```mermaid
flowchart LR
    SRC[Webcam / Video / RTSP] --> CAP[CameraRuntime sole capture owner]
    CAP --> RAW[Raw FrameHub latest]
    RAW --> PREVIEW[Preview JPEG]
    RAW --> MJPEG[MJPEG source cadence]
    CAP --> ELIGIBLE[Even source-frame eligibility]
    ELIGIBLE --> SLOT[LatestFrameSlot capacity 1]
    SLOT --> WORKER[Per-camera Vision worker]
    WORKER --> PIPE[Canonical Vision pipeline]
    PIPE --> POLICY[VisionProductPolicy]
    POLICY --> SNAP[Exact-frame privacy snapshot]
    SNAP --> PROCESSED[Processed FrameHub]
    POLICY --> DISPATCH[Thread-safe dispatcher]
    DISPATCH --> SINK[Async event sink]
    SINK --> SERVICE[EventService]
    SERVICE --> DB[(SQLite)]
    SERVICE --> SSE[SSE]
    PREVIEW --> UI[React]
    MJPEG --> UI
    DB --> UI
    SSE --> UI
```

## 2. Stream overlay

```mermaid
flowchart TD
    RAW[Current raw FramePacket] --> CHECK{Latest result exists?}
    RESULT[Latest VisionResult] --> CHECK
    CHECK -->|different epoch| PLAIN[Render raw]
    CHECK -->|future or age > 0.75s| PLAIN
    CHECK -->|same epoch and fresh| OVERLAY[Render raw + latest overlay]
    FLAGS[Viewer boxes/identity flags] --> OVERLAY
    OVERLAY --> JPEG[MJPEG JPEG]
    PLAIN --> JPEG
```

## 3. Vision and events

```mermaid
flowchart LR
    FRAME[Eligible packet] --> YOLO[YOLO person]
    YOLO --> CROP[Person crop]
    CROP --> POSE[MediaPipe Pose CPU]
    POSE --> WINDOW[Source-time window]
    WINDOW --> RESAMPLE[64-frame resample]
    RESAMPLE --> GCN[SDA-GCN]
    GCN --> FALL[Fall state machine]
    CROP --> IDGATE{Identity enabled?}
    IDGATE -->|yes| FACE[InsightFace]
    FACE --> RETRY[Per-track retry/cache]
    RETRY --> KNOWN[Known / Locked Unknown]
    FALL --> RESULT[VisionResult]
    KNOWN --> RESULT
    RESULT --> PRODUCT[Threshold/cooldown policy]
    PRODUCT --> PRIVACY[Privacy-safe snapshot]
    PRIVACY --> EVENT[Event adapter/dispatcher]
```

## 4. Source discontinuity

```mermaid
sequenceDiagram
    participant C as CameraRuntime
    participant S as LatestFrameSlot
    participant V as Vision worker
    participant P as Pipeline session

    C->>S: epoch N boundary, discontinuity=true
    C->>S: newer epoch N packet overwrites pending
    Note over S: discontinuity remains sticky
    S->>V: latest packet + discontinuity=true
    V->>P: process observation
    P->>P: keep control-plane flags/generation
    P->>P: reset temporal fall/face/tracking state
    C->>S: next normal packet
    S->>V: discontinuity=false
```

## 5. Identity OFF race protection

```mermaid
sequenceDiagram
    participant UI as Camera UI
    participant API as Cameras API
    participant DB as SQLite desired state
    participant M as Vision manager
    participant E as In-flight inference
    participant ES as EventService

    E->>E: computing possible Unknown
    UI->>API: Identity OFF
    API->>DB: persist OFF first
    API->>M: invalidate generation/cache
    E-->>M: stale Unknown result
    M->>M: strip identity metadata/event
    ES->>DB: final persisted gate if event was queued
    Note over M,ES: Fall event is preserved
```

## 6. Snapshot privacy and optional media

```mermaid
flowchart TD
    EVENT[Fall or Unknown event] --> EXACT{Exact-frame face bbox?}
    EXACT -->|yes| BLUR[Blur face ROI]
    EXACT -->|no| FULL[CPU full-frame detector]
    FULL -->|miss| CROP[Person crop + upscale]
    CROP -->|miss| ROTATE[Rotate +90 / -90]
    ROTATE -->|miss| POSE[Pose/head safe ROI]
    POSE -->|miss| OMIT[Omit snapshot]
    FULL -->|found| BLUR
    CROP -->|found| BLUR
    ROTATE -->|found| BLUR
    POSE -->|safe| BLUR
    BLUR --> MEDIA[Optional media savepoint]
    OMIT --> PERSIST[Persist event + alert]
    MEDIA -->|success| PERSIST
    MEDIA -->|failure| PERSIST
    PERSIST --> SSE[SSE alert]
```

## 7. Startup restore

```mermaid
sequenceDiagram
    participant APP as FastAPI lifespan
    participant DB as SQLite
    participant RT as LocalRuntime
    participant VIS as Vision manager
    participant CAM as CameraRuntime

    APP->>DB: initialize/migrate
    APP->>RT: create services and bind dispatcher
    RT->>DB: load FaceGallery and desired state
    loop each desired Vision ON
        RT->>VIS: enable session + restore Identity
    end
    loop each desired Camera ON
        RT->>CAM: start source
    end
    Note over APP,CAM: one unavailable source does not fail application startup
```
