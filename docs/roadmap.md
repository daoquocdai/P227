# Roadmap

## Đã có

- Backend FastAPI, SQLite và event persistence.
- API alerts, cameras, history, overview, persons và settings.
- SSE alert stream và human review.
- Dashboard React/Vite.
- Vision code phát hiện ngã và nhận diện khuôn mặt.
- Docker backend, CI, test suite và tài liệu kỹ thuật.

## Ưu tiên tiếp theo

1. Chuẩn hóa adapter để vision publish trực tiếp `VisionEventRequest`.
2. Đưa model weights vào release artifact/Git LFS kèm checksum.
3. Thêm temporal confirmation và benchmark false alerts/hour.
4. Hợp nhất quản lý face profile giữa filesystem vision và database backend.
5. Hoàn thiện RTSP reconnect, multi-camera scheduling và health metrics.
6. Tách Docker image backend/vision và hỗ trợ device mapping.
7. Thêm frontend unit/E2E tests.
8. Thực hiện threat model, retention job và backup/restore drill.

## Tiêu chí MVP hoàn chỉnh

- Một event té ngã và một event người lạ chạy end-to-end từ video tới dashboard.
- Alert realtime xuất hiện trong SLA đã công bố.
- Human review được lưu và truy xuất trong history.
- Restart backend không mất dữ liệu.
- Hệ thống hoạt động local khi tắt Internet.
- Metric model được báo cáo trên tập test tách biệt.
