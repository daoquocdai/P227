# API contract

Base URL: `/api/v1`. `/docs` và `/openapi.json` là schema runtime chính xác
nhất khi API thay đổi.

## System và Authentication

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/health` | Process health và môi trường |
| `GET` | `/api/v1/status` | Service readiness |
| `GET` | `/api/v1/overview` | Tổng quan hệ thống |
| `POST` | `/api/v1/auth/login` | Đăng nhập, trả `token` và `user` |
| `GET` | `/api/v1/auth/me` | Người dùng của Bearer token |
| `POST` | `/api/v1/auth/change-password` | Đổi mật khẩu hiện tại |
| `POST` | `/api/v1/auth/logout` | Thu hồi session; trả `204` |

Frontend yêu cầu login cho toàn UI. Trong backend hiện tại, auth dependency chỉ
được gắn trực tiếp vào `/auth/me`, `/auth/change-password` và endpoint
admin-only `/statistics`; các router Camera/Alert/Person/Settings chưa enforce
Bearer auth. Đây là contract code hiện tại, không phải khuyến nghị security.
Token sai trả `401`; tài khoản bị vô hiệu hóa hoặc thiếu quyền trả `403` tại
những endpoint có dependency.

## Cameras

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/cameras` | Danh sách desired + observed state |
| `GET` | `/api/v1/cameras/{camera_id}` | Chi tiết camera |
| `PATCH` | `/api/v1/cameras/{camera_id}` | Cập nhật tên, vị trí và source |
| `PATCH` | `/api/v1/cameras/{camera_id}/source` | Đổi source; restart nếu desired ON |
| `DELETE` | `/api/v1/cameras/{camera_id}` | Xóa camera đã tắt, không vướng history |
| `POST` | `/api/v1/cameras/{camera_id}/start` | Persist ON và start; trả `202` |
| `POST` | `/api/v1/cameras/{camera_id}/stop` | Persist OFF và stop |
| `GET` | `/api/v1/cameras/{camera_id}/runtime/status` | Capture/runtime metrics |
| `GET` | `/api/v1/cameras/{camera_id}/preview` | Latest raw JPEG |
| `GET` | `/api/v1/cameras/{camera_id}/stream` | MJPEG stream |

Source hỗ trợ `video_file`, `webcam`, `rtsp`. Stream nhận `boxes=true` và
`identity=true`; hai flag chỉ điều khiển presentation. Preview trả `404` trước
frame đầu tiên; stream trả `409` nếu camera chưa online.

## Vision controls

| Method | Path | Ý nghĩa |
|---|---|---|
| `POST` | `/api/v1/cameras/{camera_id}/vision/enable` | Persist và bật inference |
| `POST` | `/api/v1/cameras/{camera_id}/vision/disable` | Persist, tắt và reset inference state |
| `GET` | `/api/v1/cameras/{camera_id}/vision/status` | Device, result và metrics |

Identity được start/stop cùng Vision. Nếu Identity unavailable, Vision và Fall
Detection vẫn tiếp tục và lỗi được phản ánh trong Vision status diagnostics.

## Alerts

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/alerts` | Cảnh báo đã persist |
| `GET` | `/api/v1/alerts/{alert_id}` | Chi tiết cảnh báo |
| `GET` | `/api/v1/alerts/stream` | SSE `ready`, `alert`, heartbeat |
| `PATCH` | `/api/v1/alerts/{alert_id}` | Review status/note |
| `POST` | `/api/v1/alerts/{alert_id}/read` | Đánh dấu đã đọc |
| `POST` | `/api/v1/alerts/confirm` | Compatibility endpoint cũ |

Compatibility endpoint nhận query `alert_id` và `feedback`. SSE chỉ phát sau
persistence. `snapshot_url` có thể `null`; alert vẫn hợp lệ.

## Vision event ingestion

`POST /api/v1/vision/events` nhận event ngoài và trả `202`; Local Hub bình
thường dùng in-process dispatcher, không HTTP loopback.

```json
{
  "schema_version": 1,
  "event_id": "incident-id:fall_confirmed",
  "camera_id": "camera-id",
  "camera_location": "Phòng khách",
  "event_type": "FALL_CONFIRMED",
  "occurred_at": "2026-08-15T10:00:00Z",
  "confidence": 0.91,
  "track_id": "37",
  "identity_status": "UNKNOWN",
  "identity_name": null,
  "snapshot_path": null,
  "immobile_seconds": null,
  "metadata": {}
}
```

Event type: `FALL_SUSPECTED`, `FALL_CONFIRMED`, `UNKNOWN_PERSON`,
`PERSON_RECOGNIZED`, `INACTIVITY_DETECTED`, `CAMERA_OFFLINE`, `CAMERA_ONLINE`.
Cùng `event_id` được xử lý idempotent.

## Persons và Face Gallery

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/persons` | Danh sách người thân/face profile |
| `POST` | `/api/v1/persons` | Tạo person; trả `201` |
| `PATCH` | `/api/v1/persons/{person_id}` | Cập nhật person |
| `POST` | `/api/v1/persons/{person_id}/faces` | Validate data URL, tạo embedding; trả `201` |
| `DELETE` | `/api/v1/persons/{person_id}/faces/{face_id}` | Xóa face profile; trả `200` |

Face mutation refreshes supplied gallery trong các SDA session. Ảnh enrollment
không trở thành public static asset mặc định.

## Settings

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/settings` | General, notifications, users, cameras |
| `PATCH` | `/api/v1/settings/general` | Retention, threshold, sensitive hours |
| `PATCH` | `/api/v1/settings/notifications` | Notification preferences |
| `POST` | `/api/v1/settings/users` | Tạo user; trả `201` |
| `PATCH` | `/api/v1/settings/users/{user_id}` | Kích hoạt/vô hiệu hóa user |
| `PATCH` | `/api/v1/settings/users/{user_id}/permissions/{permission}` | Cập nhật quyền |
| `PATCH` | `/api/v1/settings/cameras/{camera_id}` | Camera/Vision desired state |

`stranger_threshold` nhận 50–99; `fall_threshold` nhận 70–99. Product policy
đọc giá trị từ SQLite, không cần restart model.

## History và statistics

| Method | Path | Ý nghĩa |
|---|---|---|
| `GET` | `/api/v1/history` | Event/media đã persist |
| `GET` | `/api/v1/statistics` | Thống kê; chỉ admin |

Statistics nhận `period=today|7d|30d|custom` (mặc định `7d`), cùng `start` và
`end` dạng datetime cho custom range. API này yêu cầu Bearer token của admin đã
hoàn tất đổi mật khẩu bắt buộc.

## Status codes và invariants

| Code | Ý nghĩa |
|---|---|
| `200` | Thành công |
| `201` | Đã tạo |
| `202` | Đã chấp nhận |
| `204` | Thành công, không body |
| `401` | Session không hợp lệ |
| `403` | Tài khoản/quyền không hợp lệ |
| `404` | Resource/preview không tồn tại |
| `409` | Xung đột state, tên hoặc history |
| `422` | Payload/source/query không hợp lệ |

- Camera online phản ánh source capture, không phản ánh Vision inference.
- Vision error không làm camera khác hoặc FastAPI dừng.
- Start/Stop/Enable/Disable thay đổi persisted desired state.
- RTSP credentials không được phản chiếu trong public payload.
- Viewer count không tạo thêm Vision session.
- Identity chạy cùng Vision; Identity failure không chặn Vision/Fall.
