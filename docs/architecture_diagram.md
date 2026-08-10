# GuardianCam — Architecture Diagrams

Tài liệu này chỉ chứa các sơ đồ kiến trúc chính để dùng khi review, trình bày hoặc làm deliverable. Giải thích chi tiết nằm trong [architecture.md](architecture.md).

## 1. System context

```mermaid
flowchart LR
    USER[Người thân / Người chăm sóc]
    UI[React Web]
    HUB[GuardianCam Local Hub]
    CAM[Webcam / Video / RTSP]
    DB[(SQLite)]
    SNAP[(Local Snapshots)]

    CAM --> HUB
    USER --> UI
    UI <--> HUB
    HUB <--> DB
    HUB --> SNAP
```

## 2. Runtime architecture

```mermaid
flowchart LR
    SOURCE[Webcam / Video / RTSP]
    CAMERA[CameraRuntime]
    HUB[FrameHub\nlatest-frame]
    PREVIEW[JPEG Preview]
    MJPEG[MJPEG Stream]
    BUFFER[VisionSampleBuffer\nbounded]
    WORKER[VisionWorker]
    ENGINE[Selected VisionEngine\nV1 / V2 / Mock]
    SNAP[Event Snapshot]
    DISPATCH[Thread-safe Dispatcher]
    SINK[Async Event Sink]
    SERVICE[EventService]
    DB[(SQLite)]
    SSE[SSE Alerts]
    UI[React Frontend]

    SOURCE --> CAMERA
    CAMERA --> HUB

    HUB --> PREVIEW
    HUB --> MJPEG
    HUB --> BUFFER

    BUFFER --> WORKER
    WORKER --> ENGINE
    ENGINE --> SNAP
    ENGINE --> DISPATCH
    DISPATCH --> SINK
    SINK --> SERVICE

    SERVICE --> DB
    SERVICE --> SSE

    PREVIEW --> UI
    MJPEG --> UI
    DB --> UI
    SSE --> UI
```

## 3. Vision pipeline

```mermaid
flowchart LR
    FRAME[Sampled Frame]
    YOLO[YOLO\nPerson Detection]
    CROP[Person Crop]
    POSE[MediaPipe Pose]
    PRE[Preprocess / Normalize]
    WINDOW[64 Skeleton Samples]
    GCN[SDA-GCN]
    FACE[InsightFace]
    FALL[Fall State Machine]
    ID[Known / Unknown]
    RESULT[VisionResult]

    FRAME --> YOLO
    YOLO --> CROP
    CROP --> POSE
    POSE --> PRE
    PRE --> WINDOW
    WINDOW --> GCN
    CROP --> FACE
    GCN --> FALL
    FACE --> ID
    FALL --> RESULT
    ID --> RESULT
```

## 4. Identity data flow

```mermaid
flowchart LR
    UI[Người thân Page]
    API[Persons API]
    PERSON[(persons)]
    PROFILE[(face_profiles)]
    SERVICE[Face Identity Service]
    GALLERY[FaceGallery\nin-memory cache]
    ENGINE[Real VisionEngine\nV1 or V2]
    FACE[Camera Face Embedding]
    MATCH[Known / Unknown]

    UI --> API
    API --> PERSON
    API --> SERVICE
    SERVICE --> PROFILE

    PERSON --> GALLERY
    PROFILE --> GALLERY

    GALLERY --> ENGINE
    FACE --> ENGINE
    ENGINE --> MATCH
```

**Production source of truth:** `persons` + `face_profiles` trong SQLite. Thư mục `register face/` không phải nguồn dữ liệu production.

## 5. Startup restore

```mermaid
sequenceDiagram
    participant APP as FastAPI lifespan
    participant DB as SQLite
    participant RT as LocalRuntime
    participant CAM as CameraRuntime
    participant VIS as VisionManager/Worker

    APP->>DB: initialize + idempotent migrations
    APP->>RT: create runtime services
    RT->>DB: load face gallery
    RT->>DB: load camera/Vision desired state

    loop từng camera desired ON
        RT->>CAM: start source
    end

    loop từng camera Vision desired ON
        RT->>VIS: enable
    end

    Note over CAM,VIS: Một source lỗi không làm toàn application startup fail
```

## 6. Event flow

```mermaid
sequenceDiagram
    participant VW as VisionWorker
    participant VE as VisionEngine
    participant D as Dispatcher
    participant S as Async Sink
    participant ES as EventService
    participant DB as SQLite
    participant SSE as SSE
    participant UI as React UI

    VW->>VE: process(FramePacket, Session)
    VE-->>VW: VisionResult + business event
    VW->>D: dispatch(event)
    D->>S: thread-safe handoff
    S->>ES: consume(event)
    ES->>DB: persist transaction
    DB-->>ES: success
    ES->>SSE: publish alert
    SSE-->>UI: realtime update
```

## 7. Desired state vs observed state

```mermaid
flowchart TB
    DB[(Persisted Desired State)]
    RESTORE[Startup Restore]
    RUNTIME[Observed Runtime State]
    API[Camera / Settings Controls]

    API --> DB
    API --> RUNTIME
    DB --> RESTORE
    RESTORE --> RUNTIME

    RUNTIME --> C1[Camera: online / connecting / offline / error]
    RUNTIME --> VS[Vision: disabled / waiting_for_source / running / error]
```

Một camera desired ON có thể tạm `offline/error`; điều đó không được tự đổi persisted desired state thành OFF.

## 8. Deployment boundary

```mermaid
flowchart TB
    subgraph LOCAL["Một GuardianCam Local Hub"]
        FASTAPI[FastAPI]
        CAMERA[Camera Runtime]
        VISION[Vision Worker]
        EVENT[Event Pipeline]
        SQLITE[(SQLite)]
        SNAP[Snapshots]
        FRONTEND[React/Vite]
    end

    SOURCES[Camera Sources] --> CAMERA
    FRONTEND <--> FASTAPI

    CAMERA --> VISION
    VISION --> EVENT
    EVENT --> SQLITE
    EVENT --> SNAP
    FASTAPI <--> SQLITE
```

Runtime không yêu cầu Redis, Kafka, Celery hoặc một AI service riêng cho từng camera.
