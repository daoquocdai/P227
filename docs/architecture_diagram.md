# Sơ đồ kiến trúc GuardianCam — Central Local Hub

```mermaid
flowchart LR
    subgraph CAM[Camera thường]
        C1[RTSP Camera 1]
        C2[RTSP Camera 2]
        C3[USB/RTSP Camera N]
    end

    subgraph HUB[Local Smart Hub]
        ING[Video Ingest]
        VIS[YOLO + Tracker]
        AUX[Pose + Face<br/>on demand]
        EVT[Temporal Event Engine]
        Q[In-memory Event Queue]
        BE[FastAPI + LangGraph]
        DB[(Local DB)]
        FS[(Encrypted Media)]
    end

    UI[React/PWA<br/>LAN or VPN]

    C1 --> ING
    C2 --> ING
    C3 --> ING
    ING --> VIS --> AUX --> EVT
    EVT --> Q --> BE
    AUX --> FS
    BE --> DB
    FS --> BE
    BE <-->|REST + WebSocket/SSE| UI
```

Video thô chỉ đi từ camera đến Local Hub trong mạng nội bộ. Vision truyền event object qua bounded queue; snapshot và clip nằm trên shared local volume. Event Engine quyết định cảnh báo an toàn trước khi phần diễn giải tùy chọn hoạt động.

Chi tiết contract, trách nhiệm thành phần và ràng buộc bảo mật nằm tại [`../ARCHITECTURE.md`](../ARCHITECTURE.md).
