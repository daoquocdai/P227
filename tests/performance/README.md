# Kiểm thử hiệu năng tự động cho GuardianCam

Bộ kiểm thử đo theo contract thật trong mã nguồn:

- Nhận sự kiện AI: `POST /api/v1/vision/events` (`VisionEventRequest`, HTTP 202).
- Kiểm tra backend: `GET /health`.
- Chuyển cảnh báo đến client: SSE `GET /api/v1/alerts/stream`.
- Lưu trữ: SQLite ở chế độ WAL; `event_id` được ánh xạ ổn định thành khóa chính.
- Frontend nhận SSE rồi gọi lại API danh sách cảnh báo; hệ thống chưa ghi timestamp khi DOM render xong.

`test_client_receive_latency.py` đo thời gian sự kiện đến client SSE giả lập với metric
`client_receive_latency_ms`. Đây không phải độ trễ render giao diện. Muốn đo DOM thật, frontend cần
tạo `Performance.mark` sau khi `event_id` tương ứng được React commit, rồi đối chiếu với
`metadata.ai_completed_at`. Các máy khác nhau phải đồng bộ đồng hồ bằng NTP hoặc tương đương.
Thời gian inference AI không nằm trong phạm vi đo.

## Yêu cầu

- Windows PowerShell, Python 3.11 và môi trường `.venv` của dự án.
- Chạy lệnh từ thư mục gốc `D:\DuAnCAm`.

```powershell
.\.venv\Scripts\python.exe -m pip install -r tests\performance\requirements.txt
```

## Chạy nhanh, không cần mở backend

```powershell
.\.venv\Scripts\python.exe -m pytest `
  tests\performance\test_smoke.py `
  tests\performance\test_payload_size.py `
  tests\performance\test_recovery.py -v
```

Chạy riêng SQLite:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\performance\test_database.py -v
```

Test SQLite hiện có thể `FAIL` với `database is locked`. Đây là lỗi cạnh tranh khóa được phát hiện
trong backend, không phải lỗi cài đặt pytest.

## Chạy với backend thật

### 1. Khởi động backend bằng database test riêng

Trong PowerShell thứ nhất:

```powershell
New-Item -ItemType Directory -Force tests\performance\.tmp | Out-Null
$env:APP_ENV='test'
$env:DATABASE_URL='sqlite:///./tests/performance/.tmp/perf.db'
.\.venv\Scripts\python.exe -m uvicorn src.main:app --host 127.0.0.1 --port 8000
```

Không trỏ `DATABASE_URL` đến database demo chứa dữ liệu quan trọng.

### 2. Chạy smoke test tải nhỏ

Trong PowerShell thứ hai:

```powershell
$env:PERF_BASE_URL='http://127.0.0.1:8000'
$env:PERF_DATABASE_PATH='tests/performance/.tmp/perf.db'
$env:PERF_WARMUP_SECONDS='2'
.\.venv\Scripts\python.exe -m tests.performance.runner --rate 1 --duration 10
```

Báo cáo JSON, CSV và Markdown được tạo trong `tests/performance/reports/`.

### 3. Đo API và thời gian client nhận SSE

```powershell
$env:PERF_RUN_LIVE='true'
.\.venv\Scripts\python.exe -m pytest `
  tests\performance\test_api_latency.py `
  tests\performance\test_client_receive_latency.py -v
```

## Chạy throughput

Mức 1 và 10 sự kiện/giây:

```powershell
$env:PERF_RUN_MATRIX='true'
$env:PERF_DURATION_SECONDS='60'
.\.venv\Scripts\python.exe -m pytest tests/performance/test_throughput.py -k '1 or 10' -v
```

Mức 50 và 100 sự kiện/giây chỉ chạy sau khi xác nhận môi trường local/test:

```powershell
$env:PERF_RUN_MATRIX='true'
$env:PERF_DURATION_SECONDS='60'
$env:PERF_CONFIRM_HIGH_LOAD='true'
.\.venv\Scripts\python.exe -m pytest tests/performance/test_throughput.py -k '50 or 100' -v
```

## Chạy soak test

Mặc định chạy 2 giờ. Không chạy lệnh này nếu chỉ muốn kiểm tra nhanh:

```powershell
$env:PERF_DURATION_SECONDS='7200'
$env:PERF_RATE='1'
$env:PERF_SNAPSHOT_RATIO='0'
.\.venv\Scripts\python.exe -m tests.performance.soak_test
```

Trong CI có thể giảm `PERF_DURATION_SECONDS`, ví dụ xuống `60` giây.

## Cơ chế an toàn

- Mặc định chỉ gửi 1 sự kiện/giây đến `127.0.0.1`.
- URL không phải local bị từ chối, trừ khi đặt `PERF_ALLOW_PRODUCTION=true`.
- Tải trên 10 sự kiện/giây yêu cầu `PERF_CONFIRM_HIGH_LOAD=true`.
- Test database luôn tạo database tạm riêng và dọn sau khi hoàn tất.
- Không nhúng ảnh Base64 vào JSON vì API production không yêu cầu.

## Biến cấu hình

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `PERF_BASE_URL` | `http://127.0.0.1:8000` | URL backend |
| `PERF_DATABASE_PATH` | `tests/performance/.tmp/perf.db` | Database test để đối soát |
| `PERF_EVENT_ENDPOINT` | `/api/v1/vision/events` | Endpoint nhận sự kiện |
| `PERF_HEALTH_ENDPOINT` | `/health` | Endpoint kiểm tra trạng thái |
| `PERF_STREAM_ENDPOINT` | `/api/v1/alerts/stream` | Endpoint SSE |
| `PERF_RATE` | `1` | Số sự kiện mỗi giây |
| `PERF_DURATION_SECONDS` | `10` | Thời gian chạy chính thức |
| `PERF_CONCURRENCY` | `4` | Mức đồng thời |
| `PERF_WARMUP_SECONDS` | `2` | Warm-up, không tính vào kết quả |
| `PERF_SNAPSHOT_SIZE_KB` | `0` | Kích thước snapshot dự kiến |
| `PERF_SNAPSHOT_RATIO` | `0` | Tỷ lệ sự kiện có snapshot |
| `PERF_RESOURCE_SAMPLE_SECONDS` | `5` | Chu kỳ lấy mẫu CPU/RAM |
| `PERF_REPORT_DIR` | `tests/performance/reports` | Thư mục báo cáo |
| `PERF_BACKEND_PID` | trống | PID backend để đo riêng tài nguyên |

## Ngưỡng đánh giá

- API: P50 ≤ 100 ms; P95 ≤ 300 ms; P99 ≤ 500 ms; tỷ lệ lỗi < 1%.
- Client nhận cảnh báo: P50 ≤ 500 ms; P95 ≤ 1.000 ms; P99 ≤ 2.000 ms.
- Backend: CPU P95 ≤ 70%; RAM tối đa ≤ 1 GB.
- SQLite: P95 ghi event ≤ 50 ms; lấy 20 event mới nhất ≤ 100 ms; thống kê ngày ≤ 300 ms.
- Không mất event, không trùng event và không có `database is locked`.

## Cách đo và giới hạn

- Duration cùng máy dùng đồng hồ monotonic/performance; warm-up bị loại khỏi kết quả.
- Báo cáo có min, max, trung bình, độ lệch chuẩn và P50/P95/P99.
- Upload ảnh 100 KB, 500 KB và 1 MB là `NOT MEASURED`: API chỉ nhận `snapshot_path`, không có endpoint upload nhị phân.
- Thời gian riêng của backend, database và DOM render là `NOT MEASURED` khi chưa có instrumentation.
- Có `PERF_BACKEND_PID` thì đo CPU/RAM backend; nếu không, số liệu thuộc tiến trình test.
- Monitoring lấy một mẫu `psutil` mỗi chu kỳ cấu hình và có overhead nhỏ.

## Đọc báo cáo

Mỗi lần chạy tạo ba tệp cùng timestamp: `.json` cho CI, `.csv` cho Excel/phân tích và `.md` cho
báo cáo đồ án. `PASS` là đạt mọi ngưỡng áp dụng; `FAIL` là có ngưỡng không đạt; `NOT MEASURED`
là chưa đủ contract, timestamp hoặc instrumentation để kết luận, không phải số liệu giả định.
