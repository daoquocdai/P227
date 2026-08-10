# Kiểm thử và Acceptance

Không gộp mọi mức kiểm thử thành một câu “tests passed”. GuardianCam có các lớp bằng chứng độc lập.

## 1. Unit / Regression

Mục tiêu:

- adapter contract;
- sampler;
- Vision session;
- repository;
- CRUD;
- device selection;
- snapshot/media validation;
- FaceGallery;
- desired-state persistence.

Chạy backend regression bằng Mock khi muốn độc lập model/hardware:

```cmd
set VISION_ENGINE=mock
set VISION_LEGACY_IDENTITY_ENABLED=false
python -m pytest -q
```

Mock engine không phải bằng chứng cho Vision V1/V2 thật.

## 2. Integration

Phải bao phủ:

- CameraRuntime → FrameHub.
- FrameHub → MJPEG/preview.
- VisionWorker → dispatcher → async sink.
- EventService → SQLite → SSE.
- Startup restore camera/Vision desired state.
- Failure isolation giữa cameras.
- Overview/Persons/Settings/History dùng database.
- FaceGallery load/invalidation.
- Snapshot path validation và missing snapshot behavior.

## 3. Golden Vision

Golden test so standalone oracle bất biến với engine Local Hub tương ứng trên cùng:

- video;
- model/config/checkpoint;
- source-time/sampling contract;
- device/provider khi so numeric output.

Evidence cần ghi:

- expected/oracle source;
- video/checksum;
- model/config/checkpoint checksum;
- input shape;
- sampled frame/source timestamps;
- logits/probabilities/class;
- fall state transitions;
- emitted events;
- numeric tolerance.

Unit test count không thay thế golden evidence.

V1:

```cmd
.venv\Scripts\python.exe tests\test_vision\golden_regression.py --frames 127
```

V2:

```cmd
.venv\Scripts\python.exe tests\test_vision\v2_golden_regression.py --frames 127
```

Kết quả exact mong đợi cho từng stage: `first_divergence=null`, `max_abs=0.0`
và `exact_equal=true`. Các runner cần model/video fixture thật và có thể tốn
nhiều thời gian hơn unit tests.

## 4. System E2E

Chạy backend + frontend thật.

Acceptance tối thiểu:

1. DB camera desired state được restore sau startup.
2. Không cần Swagger để start camera/enable Vision.
3. Overview hiển thị DB cameras + static preview/placeholder.
4. Camera page mở live MJPEG đúng source.
5. Một source lỗi không làm camera khác/backend lỗi.
6. Settings thay đổi desired state và persist.
7. Persons CRUD/face profile dùng database.
8. FaceGallery cập nhật sau mutation.
9. Alerts tải persisted state.
10. SSE nhận realtime update.
11. History tải persisted event/media.
12. Event snapshot đúng hoặc missing state trung thực.
13. Vision error không làm Camera offline.

Real Vision acceptance bổ sung:

14. Engine V1 hoặc V2 được chọn load strict thành công.
15. Vision `running` hoặc `degraded`, không integration `error`.
16. Fixed-video/person test đi qua model thật.
17. Event thật đi tới DB/SSE/frontend.

## 5. Stability

Theo từng hardware profile, theo dõi:

- runtime duration;
- camera continuity;
- MJPEG continuity;
- processed/drop;
- buffer depth;
- dispatcher drop/error;
- memory;
- CPU/GPU utilization;
- shutdown cleanliness;
- thread/resource leak.

Một camera lỗi hoặc SSE client disconnect không được làm toàn hub mất hoạt động.

## 6. Performance

Ghi theo từng hardware profile:

- target sample rate;
- effective sample rate;
- service rate;
- processing p50/p95;
- input drop;
- temporal drop;
- overload;
- temporal fidelity;
- CPU/GPU/RAM;
- single/multi-camera count và duration.

`SUPPORTED-DEGRADED` được chấp nhận cho product smoke nếu:

- camera/MJPEG vẫn hoạt động;
- bounded resources;
- event pipeline không deadlock;
- system báo degraded trung thực.

Strict Vision capacity yêu cầu profile hardware chứng minh được contract tương ứng.

## 7. Quality gates

### Python dependency

```cmd
python -m pip check
```

### Ruff toàn repository

Hai oracle standalone có per-file ignore hẹp trong `ruff.toml` để giữ byte-identical;
không auto-fix chúng. Toàn repository phải lint sạch:

```cmd
python -m ruff check .
python -m ruff check src tests
```

### Frontend build

```cmd
cd frontend
npm.cmd run build
```

### Diff whitespace

```cmd
git diff --check
```

## 8. Release candidate gate

Trước demo/release candidate:

- [ ] Dependency install/import smoke PASS.
- [ ] `pip check` PASS.
- [ ] Backend unit/regression PASS.
- [ ] Integration tests PASS.
- [ ] Frontend production build PASS.
- [ ] Startup restore PASS.
- [ ] Camera failure isolation PASS.
- [ ] Preview/MJPEG PASS.
- [ ] Persons/Settings/History database-backed behavior PASS.
- [ ] FaceGallery persistence/invalidation PASS.
- [ ] Real engine được chọn strict model load PASS.
- [ ] Golden regression của engine được chọn PASS.
- [ ] Fixed-video Real Vision smoke PASS.
- [ ] Event → DB → SSE → frontend E2E PASS.
- [ ] Snapshot evidence/missing behavior PASS.
- [ ] Known hardware limitations được ghi.
- [ ] Worktree scope được review.
- [ ] `git diff --check` PASS.
- [ ] Secret/runtime-data review PASS.

Nếu chưa có hardware đạt strict temporal fidelity, có thể phát hành product candidate ở profile `SUPPORTED-DEGRADED`, nhưng không được tuyên bố strict capacity.

## 9. Acceptance report template

Mỗi acceptance report nên ghi:

```text
Date:
Git commit / worktree:
OS:
Python:
Vision engine:
Vision device:
Identity provider:
Camera source:
Camera count:
Duration:

Unit:
Integration:
Frontend build:
Real Vision:
Event E2E:
Snapshot:
SSE:
Persons/FaceGallery:
Settings:
History:

Target rate:
Effective rate:
Service rate:
Drops:
Overloads:
Temporal fidelity:
CPU:
GPU:
RAM:

Known limitations:
Final verdict:
```

## 10. Không được dùng làm bằng chứng duy nhất

- Chỉ một con số tổng tests passed mà không ghi commit, profile và test command.
- Mock engine.
- Một screenshot frontend.
- Một model prediction.
- Training accuracy không có evaluation protocol.
- FPS của camera không đồng nghĩa Vision sample rate.
- Không có traceback không đồng nghĩa temporal fidelity strict.
