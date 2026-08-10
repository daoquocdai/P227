# Kiểm thử và chất lượng

## Backend tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Test bao phủ agent graph, tools, API alerts/cameras/history/overview/persons/settings và event service.

Tests cần SQLite. Đặt tạm cho shell nếu `.env` local đang dùng giá trị khác:

```powershell
$env:DATABASE_URL='sqlite:///./data/test.db'
.\.venv\Scripts\python.exe -m pytest -q
```

Database test mới có thể cần `database/seed.sql` nếu test kỳ vọng hai camera demo.

## Lint và format

```powershell
.\.venv\Scripts\python.exe -m ruff check src tests
.\.venv\Scripts\python.exe -m ruff format --check src tests
```

## Frontend

```powershell
cd frontend
npm run build
```

Build TypeScript là quality gate tối thiểu. Khi bổ sung test UI, ưu tiên Vitest/Testing Library cho component và Playwright cho luồng end-to-end.

## Vision

Kiểm tra tối thiểu:

- Import được OpenCV, MediaPipe, ONNX Runtime và PyTorch.
- Load đúng config/checkpoint.
- Camera/video mở được và giải phóng resource khi thoát.
- Event JSON validate qua `VisionEventRequest`.
- Benchmark theo video chưa xuất hiện trong train set.

Metric nên theo dõi: precision/recall/F1 cho fall và unknown person, false alerts/hour, detection latency p50/p95 và tỷ lệ camera reconnect.

## CI

Workflow `.github/workflows/ci.yml` chạy trên Python 3.11, cài `requirements.txt`, Ruff và pytest cho push vào `main`/`develop` và pull request vào `main`.

## Trước khi merge

```text
[ ] Không có .env, database, face image hoặc model weight trong diff
[ ] pip check không có dependency hỏng
[ ] pytest đạt hoặc failure đã được giải thích
[ ] frontend build đạt
[ ] docs và OpenAPI khớp code
[ ] event contract giữ backward compatibility hoặc tăng schema_version
```
