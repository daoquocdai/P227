# Báo cáo kiểm thử hiệu năng GuardianCam

Ngày thực hiện: 15/08/2026  
Môi trường: Windows 10 build 26200, Python 3.11.9, 4 nhân/8 luồng CPU, RAM 15,75 GB  
Phạm vi: backend FastAPI, SSE, SQLite, payload và recovery; không bao gồm AI inference hay độ chính xác mô hình.

## 1. Cấu hình và nguyên tắc

- Event được sinh tự động nhưng đi qua schema, FastAPI, queue, service và SQLite thật.
- Test cô lập dùng database tạm; test live dùng `tests/performance/.tmp/live-report.db`.
- Backend live chạy ở `APP_ENV=test`, URL `http://127.0.0.1:18765`.
- Warm-up từ 1–2 giây và không tính vào latency chính thức.
- Không chạy 50–100 event/giây hoặc soak 2 giờ vì chưa có xác nhận tải cao.
- Duration dùng đồng hồ monotonic/performance; SSE đối chiếu timestamp UTC trên cùng máy.

## 2. Tổng hợp kết quả

| Phần kiểm thử | Cách chạy | Kết quả | Nhận xét |
|---|---|---|---|
| Smoke cô lập | 3 request tuần tự, chạy 3 lần | FAIL theo ngưỡng hiệu năng | Cả 3 lần đều lưu đủ, không mất/trùng; latency và CPU biến động lớn |
| SQLite | 5 warm-up, 40 lượt ghi bằng 4 luồng | FAIL | Xuất hiện `sqlite3.OperationalError: database is locked` |
| Payload JSON | Không snapshot và có `snapshot_path` | PASS | Kích thước payload thay đổi đúng theo contract |
| Upload ảnh 100/500/1024 KB | Endpoint nhị phân không tồn tại | NOT MEASURED | 3 test được SKIPPED có chủ đích |
| Recovery | Timeout, mất kết nối, retry giới hạn | PASS | 2/2 test đạt; retry tối đa 3 lần và exponential backoff |
| API live 1 event/giây | 10 request sau warm-up | FAIL | 10/10 response thành công, không mất/trùng event, nhưng P50/P95 vượt ngưỡng |
| Client nhận SSE | 5 event | FAIL | P50 client receive là 569,892 ms, vượt mục tiêu 500 ms |
| Throughput 10 event/giây | 100 request trong 10 giây | FAIL | Chỉ 18 response thành công; 82% lỗi/timeout, latency tăng lên nhiều giây |
| Throughput 50 và 100 event/giây | Không chạy | NOT RUN | Cần xác nhận rõ môi trường local/test và chấp nhận tải cao |
| Soak 2 giờ | Không chạy | NOT RUN | Theo yêu cầu chỉ chuẩn bị lệnh, không tự chạy |

## 3. Smoke test cô lập

Ba lần chạy được thực hiện bằng FastAPI ASGI in-process với đầy đủ lifespan và database tạm.

| Lần | Requests | Success | P50 (ms) | P95 (ms) | P99 (ms) | CPU P95 | RAM max (MB) | Mất | Trùng | Đánh giá lại |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | 3 | 3 | 204,18 | 210,49 | 211,05 | 103,18% | 96,63 | 0 | 0 | FAIL |
| 2 | 3 | 3 | 1.573,55 | 1.603,66 | 1.606,34 | 71,70% | 96,22 | 0 | 0 | FAIL |
| 3 | 3 | 3 | 404,72 | 406,29 | 406,43 | 95,38% | 96,55 | 0 | 0 | FAIL |

Ngưỡng API là P50 ≤ 100 ms, P95 ≤ 300 ms, P99 ≤ 500 ms; CPU P95 ≤ 70%. RAM của cả ba lần đều đạt ngưỡng ≤ 1 GB. Dữ liệu cho thấy độ trễ có độ biến động cao ngay ở tải tuần tự thấp.

Lưu ý: báo cáo JSON đầu tiên từng ghi `PASS` vì hàm kết luận cũ chỉ kiểm tra P95 và bỏ sót P50/P99/CPU. Harness đã được sửa để kiểm tra đầy đủ các ngưỡng; bảng trên là kết luận đã hiệu chỉnh.

## 4. API live ở 1 event/giây

Kết quả chính thức sau khi sửa việc tách `test_run_id` của warm-up:

| Requests | Success | Error rate | Throughput | P50 | P95 | P99 | CPU P95 | RAM max | Stored | Lost | Duplicate | Kết quả |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 10 | 10 | 0% | 1,054 event/s | 389,09 ms | 454,79 ms | 471,50 ms | 12,47%* | 38,80 MB* | 10 | 0 | 0 | FAIL |

`*` Không truyền `PERF_BACKEND_PID`, do đó CPU/RAM trên là của tiến trình chạy test, không phải backend. Hai chỉ số này không được dùng để kết luận tài nguyên backend.

API thất bại ở P50 và P95; P99, error rate, lưu trữ, mất và trùng event đạt yêu cầu.

Test assertion riêng chạy sau đó cũng FAIL với P50 616,878 ms > 100 ms.

## 5. Client receive latency qua SSE

- Số mẫu: 5 event.
- Metric: `client_receive_latency_ms`.
- P50 đo được: 569,892 ms.
- Mục tiêu P50: ≤ 500 ms.
- Kết quả: FAIL.

Đây là lúc client giả lập nhận SSE, không phải thời gian DOM render. Muốn đo DOM thật cần bổ sung `Performance.mark` trong React sau khi cảnh báo tương ứng được render.

## 6. Throughput 10 event/giây

| Sent | Success response | Failed/timeout | Error rate | Throughput thực tế | P50 | P95 | P99 | Kết quả |
|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 100 | 18 | 82 | 82% | 0,904 event/s | 5.615,32 ms | 9.977,68 ms | 10.337,93 ms | FAIL |

Backend tiếp tục xử lý một phần request sau khi client timeout, tạo nhiều kết nối `CLOSE_WAIT`. Lần chạy lại phải dừng ở warm-up do `ReadTimeout`, cho thấy hệ thống chưa phục hồi kịp sau tải. Số event mất/trùng của lần này được ghi `NOT MEASURED` vì phiên bản harness lúc chạy so sánh với số response thành công thay vì toàn bộ ID đã gửi. Harness đã được sửa cho các lần chạy sau.

Mức tải cao nhất đã chứng minh đáp ứng điều kiện hiện tại là 1 event/giây về error rate và tính toàn vẹn dữ liệu, nhưng mức này vẫn không đạt ngưỡng latency. Vì vậy chưa thể tuyên bố hệ thống đạt hoàn chỉnh bất kỳ mức tải mục tiêu nào.

## 7. SQLite

Test dùng database tạm và 4 writer đồng thời. Kết quả:

```text
sqlite3.OperationalError: database is locked
```

Lỗi xảy ra trong `initialize_database()` khi `_apply_runtime_migrations()` ghi `system_settings`. Mỗi lần mở `database_connection()` lại gọi initialization/migration, nên các writer tranh khóa trước khi insert event hoàn tất. Do bài test dừng tại lỗi này, các percentile query còn lại không đủ dữ liệu để kết luận và được xem là `NOT MEASURED` trong lần chạy này.

## 8. Payload và snapshot

- JSON không snapshot và JSON có `snapshot_path`: PASS.
- Upload nhị phân 100 KB, 500 KB, 1 MB: NOT MEASURED.

Contract production chỉ nhận đường dẫn `snapshot_path`; không có endpoint multipart/binary upload. Bộ test không nhúng Base64 để tránh đo một contract không tồn tại.

## 9. Network failure và recovery

Hai test sử dụng test double an toàn, không thay đổi firewall hay cấu hình mạng:

- Timeout/mất kết nối hai lần rồi thành công ở lần thứ ba: PASS.
- Luôn timeout và dừng đúng sau 3 lần: PASS.

Backoff dùng `base_delay × 2^attempt`; số retry có giới hạn. Idempotency phía persistence được hỗ trợ bởi việc ánh xạ ổn định `event_id` thành khóa chính và trả `duplicate=True` khi gửi lại.

## 10. Vấn đề và khuyến nghị

1. Ưu tiên sửa initialization SQLite: chỉ migration/seed một lần lúc startup, không thực hiện trong từng kết nối request.
2. Đo lại database concurrency và toàn bộ query sau khi hết `database is locked`.
3. Profile phần xử lý event vì mỗi request tuần tự mất khoảng 0,4 giây và tải 10/s nhanh chóng tạo backlog.
4. Truyền `PERF_BACKEND_PID` ở lần đo chính thức để tách CPU/RAM backend khỏi test process.
5. Bổ sung instrumentation backend/database và `Performance.mark` phía React nếu cần phân rã latency.
6. Chỉ chạy 50/100 event/giây sau khi hệ thống ổn định ở 10 event/giây.
7. Chạy soak 2 giờ sau khi các lỗi latency, timeout và SQLite locking được xử lý.

## 11. Tệp bằng chứng

- API live 1 event/giây: `tests/performance/reports/perf-20260815T034242Z.json` và các bản `.csv`, `.md` cùng tên.
- Throughput 10 event/giây: `tests/performance/reports/perf-20260815T034342Z.json` và các bản `.csv`, `.md` cùng tên.
- Mã test và hướng dẫn tái lập: `tests/performance/README.md`.

Backend test tại cổng 18765 đã được dừng sau khi hoàn thành; database demo không bị thay đổi.
