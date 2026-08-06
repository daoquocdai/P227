# Backend API

Base URL local: `http://localhost:8000`. API nghiệp vụ dùng prefix `/api/v1`.

Swagger/OpenAPI là tài liệu schema chính xác nhất tại `/docs` và `/openapi.json`.

## Health và trạng thái

| Method | Path | Mô tả |
|---|---|---|
| GET | `/health` | Health check và môi trường |
| GET | `/api/v1/status` | Trạng thái hệ thống |
| GET | `/api/v1/overview` | Tổng quan dashboard |

## Vision integration

### `POST /api/v1/vision/events`

```json
{
  "schema_version": 1,
  "event_id": "cam-living-20260806-001",
  "camera_id": "living-room",
  "camera_location": "Phòng khách",
  "event_type": "FALL_CONFIRMED",
  "occurred_at": "2026-08-06T10:20:31+07:00",
  "confidence": 0.93,
  "track_id": "37",
  "identity_status": "KNOWN",
  "identity_name": "Nguyễn Văn An",
  "snapshot_path": "snapshots/event-001.jpg",
  "immobile_seconds": 8.2,
  "metadata": {"vision_version": "sdagcn-v1"}
}
```

Response HTTP 202:

```json
{
  "id": "internal-record-id",
  "event_id": "cam-living-20260806-001",
  "accepted": true,
  "duplicate": false,
  "status": "pending"
}
```

Gửi lại cùng `event_id` phải trả `duplicate: true` thay vì tạo cảnh báo mới.

## Alerts

| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/v1/alerts` | Danh sách mới nhất trước |
| GET | `/api/v1/alerts/stream` | SSE: `ready`, `alert`, heartbeat |
| GET | `/api/v1/alerts/{alert_id}` | Chi tiết cảnh báo |
| PATCH | `/api/v1/alerts/{alert_id}` | Review trạng thái và ghi chú |
| POST | `/api/v1/alerts/{alert_id}/read` | Đánh dấu đã đọc |
| POST | `/api/v1/alerts/confirm` | Endpoint tương thích client cũ |

Trạng thái review: `pending`, `checking`, `resolved`, `safe`, `false_alarm`, `need_help`.

## Cameras

| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/v1/cameras` | Danh sách camera |
| GET | `/api/v1/cameras/{camera_id}` | Chi tiết camera |
| PATCH | `/api/v1/cameras/{camera_id}/source` | Đổi `video_file`, `webcam` hoặc `rtsp` |

`source_uri` có thể chứa credential RTSP và không được trả về frontend. Frontend chỉ nhận playback URL đã được phép công khai.

## Người thân, lịch sử và settings

| Method | Path | Mô tả |
|---|---|---|
| GET/POST | `/api/v1/persons` | Danh sách/tạo người thân |
| PATCH | `/api/v1/persons/{id}` | Cập nhật hồ sơ |
| POST | `/api/v1/persons/{id}/faces` | Thêm metadata ảnh khuôn mặt |
| DELETE | `/api/v1/persons/{id}/faces/{face_id}` | Xóa face profile |
| GET | `/api/v1/history` | Lịch sử sự kiện |
| GET | `/api/v1/settings` | Toàn bộ settings |
| PATCH | `/api/v1/settings/general` | Cấu hình chung |
| PATCH | `/api/v1/settings/notifications` | Cấu hình thông báo |

## Snapshot

Backend mount thư mục local `snapshots/` tại `/snapshots`. Chỉ lưu relative path trong database. Không chấp nhận path traversal hoặc URL tùy ý từ client công khai.

## Error handling

- `404`: camera, person, face profile hoặc alert không tồn tại.
- `422`: payload/schema hoặc source camera không hợp lệ.
- `202`: vision event đã được nhận vào pipeline bất đồng bộ.
- Client phải chịu được duplicate event và kết nối lại SSE.
